import pandas as pd
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection
from itertools import cycle
from spacepy import pycdf
import matplotlib.dates as mdates
import numpy as np
import matplotlib.pyplot as plt
from fancy_plot import fancy_plot
from datetime import datetime
from multiprocessing import Pool
from functools import partial
import multi_dtw as md
import os
import threading
import sys
import time
import mlpy #for dynamic time warping 
from dtaidistance import dtw #try new dynamic time warping function that creates penalty for compression
import load_cdf_files as lcf #reading cdfs to pandas arrays


from scipy.stats.mstats import theilslopes
import scipy.optimize


#Defination of a plane
#def plane_func(a,b,c,d,x,y,z):
#    """
#    The solution of a pl
#
#    Returns
#    -------
#    value: float
#        The value of the plane at a given X, Y, and Z
#    """
#    return a*x+b*y+c*z+d
#

def solve_plane(p,t):
    """
    Velocity plane for given time and position of spacecraft
    
    Parameters
    ---------
    p: np.array or np.matrix
        Position vectors in x,y,z for three spacecraft with respect to wind
        The First row is the X,Y,Z values for spacecraft 1
        The Second row is the X,Y,Z values for spacecraft 2
        The Thrid row is the X,Y,Z values for spacecraft 3
    t: np.array or np.matrix
        Time offset array from Wind for three spacecraft
    """
    vna = np.linalg.solve(p,t) #solve for the velocity vectors normal
    vn  = vna/np.linalg.norm(vna)
    vm  = 1./np.linalg.norm(vna) #get velocity magnitude
    return vna,vn,vm


def solve_plane_cadence(p,t,dt):
    """
    Velocity plane for given time and position of spacecraft
    
    Parameters
    ---------
    p: np.array or np.matrix
        Position vectors in x,y,z for three spacecraft with respect to wind
        The First row is the X,Y,Z values for spacecraft 1
        The Second row is the X,Y,Z values for spacecraft 2
        The Thrid row is the X,Y,Z values for spacecraft 3
    t: np.array or np.matrix
        Time offset array from Wind for three spacecraft
    dt: np.array or np.matrix
        The limiting time cadence for each observation
    """
    vna = np.linalg.solve(p,t) #solve for the velocity vectors normal
    vn  = vna/np.linalg.norm(vna)
    vm  = 1./np.linalg.norm(vna) #get velocity magnitude
    return vna,vn,vm

def solve_coeff(pi,vn):
    """
    Plane coefficients for given time and position of spacecraft
    
    Parameters
    ----------
    pi: np.array or np.matrix
        Position of earth spacecraft in GSE corrected for time offsets
        The First row is the X,Y,Z values for spacecraft 1
        The Second row is the X,Y,Z values for spacecraft 2
        The Thrid row is the X,Y,Z values for spacecraft 3
    vn: np.array or np.matrix
        Normal vector to planar front
  
    Returns
    --------
    a,b,c,d: float
        Solution for a plane at time t where plane has the solution 0=a*x+b*y+c*z+d
        
    """

    #solve (a*x0+b*y0+c*z0+d)/||v|| = 0
    #where ||v|| = sqrt(a^2+b^2+c^2)
    #and distance from the plane to the origin is  dis = d/||v||
    

    #get the magnitude of the normal vector on the plane from the origin
    pm = float(np.linalg.norm(pi))

    #Use definition parameter 
    coeff = np.squeeze(np.asarray(vn*pm)) #.reshape(-1)


    #store coefficients
    a = float(coeff[0])
    b = float(coeff[1])
    c = float(coeff[2])
    d = -float(np.matrix(coeff).dot(pi))
    
    return [a,b,c,d]

def arb_rotation_matrix(a,b):
    """
    Creates a rotation matrix between two unit vectors a and b.
    U.dot(a) = b
 
    Parameters
    ------------
    a,b: np.array
        Two 3 element numpy array unit vectors

    Returns
    -----------
    rot_mat: np.array
        3x3 rotation matrix between unit vectors
    
    """

    v = np.cross(a,b)
    s = np.linalg.norm(v)
    c = np.dot(a,b)

    I = np.identity(3)

    #skew-symmetric cross product of matrix v
    vx = np.array([[0,-v[2],v[1]],
                   [v[2],0,-v[0]],
                   [-v[1],v[0],0]])

    rot_mat = I+vx+vx.dot(vx)/(1+c)
    return rot_mat



#Function to read in spacecraft
def read_in(k,p_var='predict_shock_500',arch='../cdf/cdftotxt/',
            mag_fmt='{0}_mag_2015_2017_formatted.txt',pls_fmt='{0}_pls_2015_2017_formatted.txt',
            orb_fmt='{0}_orb_2015_2017_formatted.txt',
            start_t='2016/12/01',end_t='2017/09/24',center=False):
    """
    A function to read in text files for a given spacecraft. Also replaces out of range and flagged values.

    Parameters
    ----------
    k: string
        Then name of a spacecraft so to format for file read in
    arch: string, optional
        The archive location for the text file to read in (Default = '../cdf/cdftotxt/')
    mag_fmt: string, optional
        The file format for the magnetic field observations (Default = '{0}_mag_2015_2017_formatted.txt',
        where 0 is the formatted k).
    pls_fmt: string, optional
        The file format for the plasma observations (Default = '{0}_pls_2015_2017_formatted.txt',
        where 0 is the formatted k).
    orb_fmt: string, optional
        The file format for the orbital data (Default = '{0}_orb_2015_2017_formatted.txt',
        where 0 is the formatted k).
    center = boolean, optional
        Whether the analyzed point to be center focused (center = True) or right focus (Default = False).
        Center focus gives you a better localized point, however, the model is trained with a right focus
        in order to reject spikes and increase S/N.
    start_t: string, optional
        Date in YYYY/MM/DD format to start looking for events (Default = '2016/06/04')
    end_t: string, optional
        Date in YYYY/MM/DD format to stop looking for events (inclusive, Default = '2017/07/31')

    Returns
    -------
    plsm: Pandas DataFrame
        A pandas dataframe with probability values and combined mag and plasma observations.
    
    """
    #Read in plasma and magnetic field data from full res
    if k.lower() == 'soho':
        pls = pd.read_csv(arch+pls_fmt.format(k.lower()),delim_whitespace=True)
        pls['Bt'] = 0.
    #Change to function that reads cdf files for less data intense loads 2018/05/17 J. Prchlik
    else:
        outp = lcf.main(pd.to_datetime(start_t),pd.to_datetime(end_t),scrf=[k.lower()],pls=True,mag=True,orb=True)
     
        #Add data quality cut 2018/05/18 J. Prchlik
        if k.lower() == 'dscovr':
            good_pls = (outp[k.lower()]['pls'].DQF == 0)
            pls = outp[k.lower()]['pls'][good_pls]
        else:
            pls = outp[k.lower()]['pls']


    Re = 6371.0# Earth radius in km 

    #no magnetic field data from SOHO
    if k.lower() != 'soho':
        #Change to function that reads cdf files for less data intense loads 2018/05/17 J. Prchlik
        #Add data quality cut 2018/05/18 J. Prchlik
        if k.lower() == 'dscovr':
            good_mag = (outp[k.lower()]['mag'].DQF == 0)
            mag = outp[k.lower()]['mag'][good_mag]
        else:
            mag = outp[k.lower()]['mag']


        orb = outp[k.lower()]['orb']

        #create datetime objects from time
        pls['time_dt_pls'] = pd.to_datetime(pls['Time'])
        mag['time_dt_mag'] = pd.to_datetime(mag['Time'])
        orb['time_dt_orb'] = pd.to_datetime(orb['Time'])

        #setup index
        pls.set_index(pls.time_dt_pls,inplace=True)
        mag.set_index(mag.time_dt_mag,inplace=True)
        orb.set_index(orb.time_dt_orb,inplace=True)

        #multiply each component by Earth Radius for Themis observations
        if 'themis' in k.lower():
            orb.loc[:,'GSEx'] *= Re
            orb.loc[:,'GSEy'] *= Re
            orb.loc[:,'GSEz'] *= Re
            #Convert from GSM to GSE 2018/04/25 J. Prchlik
            mag.loc[:,'By'] *= -1
            mag.loc[:,'Bz'] *= -1

        #Add total magnetic field 2018/09/07 J. Prchlik
        mag['Bt'] = np.sqrt((mag.Bx**2+mag.By**2+mag.Bz**2).values.astype('float'))

        #replace bad values in thermal velocity
        pls.loc[pls.Vth.between(0,8000) == False,'Vth']  = np.nan
        #replace bad values in density
        pls.loc[pls.Np.between(0,8000) == False,'Np']  = np.nan
        #replace bad values in Speed
        pls.loc[pls.SPEED.between(0,8000) == False,'SPEED']  = np.nan

        #cut for testing reasons
        pls = pls[start_t:end_t]
        mag = mag[start_t:end_t]
        orb = orb[start_t:end_t]

        #pls = pls['2016/07/18':'2016/07/21']
        #mag = mag['2016/07/18':'2016/07/21']
        #pls = pls['2017/01/25':'2017/01/27']
        #mag = mag['2017/01/25':'2017/01/27']

        #join magnetic field and plasma dataframes
        com_df  = pd.merge(mag,pls,how='outer',left_index=True,right_index=True,suffixes=('_mag','_pls'),sort=True)

        #make sure data columns are numeric
        cols = ['SPEED','Np','Vth','Bx','By','Bz','Bt']
        com_df[cols] = com_df[cols].apply(pd.to_numeric, errors='coerce')

        #add Time string
        com_df['Time'] = com_df.index.to_datetime().strftime('%Y/%m/%dT%H:%M:%S')

        plsm = com_df
        #replace NaN with previously measured value
        #com_df.fillna(method='bfill',inplace=True)

        #add orbital data
        plsm  = pd.merge(plsm,orb,how='outer',left_index=True,right_index=True,suffixes=('','_orb'),sort=True)
        #make sure data columns are numeric
        cols = ['SPEED','Np','Vth','Bx','By','Bz','GSEx','GSEy','GSEz']
        plsm[cols] = plsm[cols].apply(pd.to_numeric, errors='coerce')

        #add Time string
        plsm['Time'] = plsm.index.to_datetime().strftime('%Y/%m/%dT%H:%M:%S')

        #fill undersampled orbit
        for cor in ['x','y','z']: plsm['GSE'+cor].interpolate(inplace=True)

    else:
        plsm = pls   
        #work around for no Mag data in SOHO
        pls.loc[:,['Bx','By','Bz','Bt']] = 0.0
        pls['time_dt_pls'] = pd.to_datetime(pls['Time'])
        pls['time_dt_mag'] = pd.to_datetime(pls['Time'])
        pls.set_index(pls.time_dt_pls,inplace=True)
        plsm = pls[start_t:end_t]
        plsm.loc[:,['Bx','By','Bz','Bt']] = -9999.0

        Re = 6371.0 # Earth radius

        #multiply each component by Earth Radius
        plsm.loc[:,'X'] *= Re
        plsm.loc[:,'Y'] *= Re
        plsm.loc[:,'Z'] *= Re

        #chane column name from X, Y, Z to GSEx, GSEy, GSEz 
        plsm.rename(columns={'X':'GSEx', 'Y':'GSEy', 'Z':'GSEz'},inplace=True)

    #force index to sort
    plsm.sort_index(inplace=True)
    #for rekeying later
    plsm['craft'] = k

    return plsm




class dtw_plane:
    """
    Class to get planar DTW solutions for L1 spacecraft.      
 
    Parameters
    ----------
    start_t: string
        Any string format recongized by pd.to_datetime indicating when to start looking for events
    end_t: string
        Any string format recongized by pd.to_datetime indicating when to stop looking for events
    center: boolean, optional
        Whether to use the center pixel for a running mean (Default = True). Otherwise running mean
        is set by preceding pixels
    events: int,optional
        Number of Events to find planar solution for in given time period (Default = 1)
    par: string or list, optional
        Parameter to use when matching via DTW (Default = None). The default solution is to use 
        flow speed for SOHO CELIAS and maximum difference in a 3 minute window for magnetic 
        field component for every other spacecraft.
    justparm: boolean, optional
        Just do DTW solution but do not create animation of solution as a funciton of time
        (Default = True)
    nproc: integer, optional
        Number of processors to use for matching (Default = 1). Currently, there is no reason
        to change this value, but is a place holder incase someday it becomes useful
    earth_craft: list, optional 
        Show Themis/Artemis space craft and the best solutions (Default = None). Can be 
        any combinateion of ['THEMIS_B','THEMIS_C','THEMIS_A'] 
    penalty: boolean, optional
        Include a penalty in the DTW solution for compression of time (Default = True)
    pad_earth: pandas time delta object, optional
        Time offset to apply when reading in spacecraft data near earth (Default = pd.to_timedelta('1 hour'))
    speed_pen: float
        Penatly in km/s for squashing speed time in DTW (Default = 10.). Only works if penalty is set to True
    mag_pen: float
        Penatly in nT for squashing magnetic field time in DTW (Default = 0.2). Only works if penalty is set to True.

    Example 
    ----------
    import model_time_range as mtr
    plane = mtr.dtw_plane('2016/07/19 21:00:00','2016/07/20 01:00:00',earth_craft=['THEMIS_B'],penalty=False)
    plane.init_read()
    plane.dtw()
    """


    def __init__(self,start_t,end_t,center=True,events=1,par=None,justparm=True,nproc=1,earth_craft=None,penalty=True,pad_earth=pd.to_timedelta('1 hour'),speed_pen=10.,mag_pen=0.2):
        self.start_t = start_t
        self.end_t = end_t
        self.center = center
        self.par = par
        self.justparm = justparm
        self.nproc = nproc
        self.Re = 6371.0 #km
        self.events = events
        self.earth_craft = earth_craft
        self.penalty = penalty
        self.pad_earth = pad_earth

        self.first = True


        #store penanalties
        self.speed_pen = speed_pen
        self.mag_pen = mag_pen


        #set use to use all spacecraft
        self.craft = ['Wind','DSCOVR','ACE','SOHO','THEMIS_A','THEMIS_B','THEMIS_C']
        self.col   = ['blue','black','red','teal','purple','orange','cyan']
        self.mar   = ['D','o','s','<','>','^','8']
        self.marker = {}
        self.color  = {}
        self.trainer = 'Wind'

        #create dictionaries for labels
        for j,i in enumerate(self.craft):
            self.marker[i] = self.mar[j]
            self.color[i]  = self.col[j]



        #reset craft variable and add earth craft as requested
        self.craft = ['Wind','DSCOVR','ACE','SOHO']
      
        
    



    def init_read(self):
        """
        Reads in text files containing information on solar wind parameters measured at different space craft

        Parameters
        ----------
        self: class
            Variables contained in self variable
        """
        #Parameters for file read in and parsing
        #Could be an issue with downwind THEMIS craft 2018/04/25 J. Prchlik
        par_read_in = partial(read_in,start_t=self.start_t,end_t=self.end_t,center=self.center)
        #read in and format spacecraft in parallel
        #Switched to single loop solution 2018/03/24 J. Prchlik 
        if self.first: #only do read in on the first pass
            if self.nproc > 1.5:
                pool = Pool(processes=len(self.craft))
                outp = pool.map(par_read_in,self.craft)
                pool.terminate()
                pool.close()
                pool.join()

                self.plsm = {}
                #create global plasma key
                for i in outp:
                    self.plsm[i.craft.values[0]] = i
            else:
                self.plsm = {}
                #create global plasma key
                for i in self.craft:
                    self.plsm[i] = par_read_in(i)
        
            #set readin to first attempt to false
            #prevent multiple readin of big files
            self.first = False


            #do the same for the Earth spacecraft 
            if self.earth_craft is not None:  
                for i in self.earth_craft: self.craft.append(i)
 
                 
                #Add an hour to the data to approximate time delay
                self.earth_start = str(pd.to_datetime(self.start_t)+self.pad_earth)
                self.earth_end = str(pd.to_datetime(self.end_t)+self.pad_earth)
                par_read_in_e = partial(read_in,start_t=self.earth_start,end_t=self.earth_end,center=self.center)

                if self.nproc > 1.5:
                    pool = Pool(processes=len(self.earth_craft))
                    outp = pool.map(par_read_in_e,self.earth_craft)
                    pool.terminate()
                    pool.close()
                    pool.join()

                    #create global plasma key
                    for i in outp:
                        self.plsm[i.craft.values[0]] = i
                else:
                    #create global plasma key
                    for i in self.earth_craft:
                        self.plsm[i] = par_read_in_e(i)
        
            #set readin to first attempt to false
            #prevent multiple readin of big files

    def iterate_dtw(self,pr_1=85.,pr_2=30.):
        """
        Iteratively find the best DTW solution. In the first iteration get the best time offset between spacecraft.
        In the second iteration find the best DTW solution.

        Parameters
        -----------------
        pr_1: float, optional
            Number of minutes allowed when scanning for a DTW solution in the first iteration (Default = 85.)
        pr_2: float, optional
            Number of minutes allowed when scanning for a DTW solution in the second iteration (Default = 30.)
  
        """

        #run the initial DTW solution
        self.dtw(pr_1)
        #get DTW offset keys from plasma dictionary
        off_keys = [i for i in self.plsm.keys() if (('offset' in i) & (i.replace('_offset','') 
                    not in self.earth_craft) & (i.replace('_offset','') != self.trainer))]


        #pandas start and end times as datetime objects
        pd_s = pd.to_datetime(self.start_t)
        pd_e = pd.to_datetime(self.end_t)
        pd_p = pd.to_timedelta('30m')
        #get middle point of DTW range
        pd_m = (pd_e-pd_s)/2.+pd_s


        #loop over all keys of offset non-trainer/non-earth spacecraft
        for j,i in enumerate(off_keys):
            #get average offset between Trainer craft and specific space craft in the core hour of the observations
            self.plsm['ave_offset_'+i.replace('_offset','')] = self.plsm[i].loc[pd_m-pd_p:pd_m+pd_p]['offsets'].median() #.values.astype(float)*1e-9

        #datetime format to write string out
        dfmt = '{0:%Y/%m/%d %H:%M:%S}'
        #recreate global plasma key
        for j in off_keys:
            #Need to repopulate the non-offset plasma values
            i = i.replace('_offset','') 
            new_start_t = dfmt.format(pd_s+self.plsm['ave_offset_'+i])
            new_end_t   = dfmt.format(pd_e+self.plsm['ave_offset_'+i])
            par_read_in = partial(read_in,start_t=new_start_t,end_t=new_end_t,center=self.center)
            self.plsm[i] = par_read_in(i)

        

        #recompute DTW solution with new time offsets
        self.dtw(pr=pr_2)

        #Do one at a time for now 2018/11/19 J. Prchlik
        #####Parameters for file read in and parsing
        #####Could be an issue with downwind THEMIS craft 2018/04/25 J. Prchlik
        ####par_read_in = partial(read_in,start_t=self.start_t,end_t=self.end_t,center=self.center)
        #####read in and format spacecraft in parallel
        #####Switched to single loop solution 2018/03/24 J. Prchlik 
        ####if self.first: #only do read in on the first pass
        ####    if self.nproc > 1.5:
        ####        pool = Pool(processes=len(self.craft))
        ####        outp = pool.map(par_read_in,self.craft)
        ####        pool.terminate()
        ####        pool.close()
        ####        pool.join()

        ####        self.plsm = {}
        ####        #create global plasma key
        ####        for i in outp:
        ####            self.plsm[i.craft.values[0]] = i
        ####    else:
        


    def dtw(self,pr=85.):
        """
        Finds DTW solution to 4 L1 spacecraft, whose later time offsets may be used to predict solar wind conditions at Earth

        Parameters
        -----------------
        pr: float, optional
            Number of minutes allowed when scanning for a DTW solution (Default = 85.)
     
        """
        #Creating modular solution for DTW 2018/03/21 J. Prchlik
        ##set the Start and end time
        #start_t = "2016/12/21 07:00:00"
        #end_t = "2016/12/21 13:00:00"
        #center = True
        #reset variables to local variables
        Re = self.Re # Earth radius
        start_t  = self.start_t 
        end_t    = self.end_t   
        center   = self.center  
        par      = self.par     
        justparm = self.justparm
        marker   = self.marker
        color    = self.color
        
        #set use to use all spacecraft
        craft = self.craft #['Wind','DSCOVR','ACE','SOHO']
        col   = self.col   #['blue','black','red','teal']
        mar   = self.mar   #['D','o','s','<']
        trainer = self.trainer
        
        #range to find the best maximum value
        maxrang = pd.to_timedelta('3 minutes')
        
        
        #create new plasma dictory which is a subset of the entire file readin
        plsm = {}
        for i in craft:
             plsm[i] = self.plsm[i] #[start_t:end_t] Cutting not required because already using a small sample 2018/05/03 J. Prchlik
             #remove duplicates
             plsm[i] = plsm[i][~plsm[i].index.duplicated(keep='first')]

        #get all values at full resolution for dynamic time warping
        t_mat  = plsm[trainer] #.loc[trainer_t-t_rgh_wid:trainer_t+t_rgh_wid]
  
        #add trainer matrix to self
        self.t_mat = t_mat

        #Find points with the largest speed differences in wind
        top_vs = (t_mat.SPEED.dropna().diff().abs()/t_mat.SPEED.dropna()).nlargest(self.events)
        
        
        #sort by time for event number
        top_vs.sort_index(inplace=True)
        
        #add to self
        self.top_vs = top_vs

        #plot with the best timing solution
        self.fig, self.fax = plt.subplots(ncols=2,nrows=3,sharex=True,figsize=(18,18))
        fig, fax = self.fig,self.fax

       
        #set range to include all top events (prevents window too large error
        self.pad = pd.to_timedelta('30 minutes')
        pad = self.pad
        fax[0,0].set_xlim([top_vs.index.min()-pad,top_vs.index.max()+pad])
        
        #loop over all other craft
        for k in craft[1:]:
            print('###########################################')
            print(k)
            p_mat  = plsm[k] #.loc[i_min-t_rgh_wid:i_min+t_rgh_wid]
        
            #use speed for rough esimation if possible
            if  ((k.lower() == 'soho') ): par = ['SPEED']
            elif (((par is None) | (isinstance(par,float))) & (k.lower() != 'soho')): par = ['Bx','By','Bz']
            elif isinstance(par,str): par = [par]
            else: par = par

        
            #sometimes different componets give better chi^2 values therefore reject the worst when more than 1 parameter
            #Try using the parameter with the largest difference  in B values preceding and including the event (2017/12/11 J. Prchlik)
            if len(par) > 1:
               check_min,check_max = top_vs.index[0]-maxrang,top_vs.index[0]+maxrang
               par_chi = np.array([(t_mat.loc[check_min:check_max,par_i].max()-t_mat.loc[check_min:check_max,par_i].min()).max() for par_i in par])
               use_par, = np.where(par_chi == np.max(par_chi))
               par      = list(np.array(par)[use_par])
        
            #get the median slope and offset
            #J. Prchlik (2017/11/20)
            #Dont use interpolated time for solving dynamic time warp (J. Prchlik 2017/12/15)
            #only try SPEED corrections for SOHO observations
            #Only apply speed correction after 1 iteration (J. Prchlik 2017/12/18)
            if (('themis' in k.lower())):
                try:
                    #create copy of p_mat
                    c_mat = p_mat.copy()
                    #resample the matching (nontrained spacecraft to the trained spacecraft's timegrid to correct offset (2017/12/15 J. Prchlik)
                    c_mat = c_mat.reindex(t_mat.index,method='nearest').interpolate('time')
         
                    #only comoare no NaN values
                    good, = np.where(((np.isfinite(t_mat.SPEED.values)) & (np.isfinite(c_mat.SPEED.values))))
         
                    #if few points for comparison only used baseline offset
                    if ((good.size < 1E36) & (par[0] == 'SPEED')):
                        med_m,med_i = 1.0,0.0
                        off_speed = p_mat.SPEED.median()-t_mat.SPEED.median()
                        p_mat.SPEED = p_mat.SPEED-off_speed
                        if med_m > 0: p_mat.SPEED = p_mat.SPEED*med_m+med_i
                    else:
                        off_speed = p_mat.SPEED.nsmallest(100).median()-t_mat.SPEED.nsmallest(20).median()
                        p_mat.SPEED = p_mat.SPEED-off_speed
                    #only apply slope if greater than 0
                except IndexError:
                #get median offset to apply to match spacecraft
                    off_speed = p_mat.SPEED.nsmallest(100).median()-t_mat.SPEED.nsmallest(20).median()
                    p_mat.SPEED = p_mat.SPEED-off_speed
         
         
         
            #get dynamic time warping value   
            print('WARPING TIME')
            #use dtw solution that allows penalty for time compression
            if self.penalty:
                if 'SPEED' in par:
                    penalty = self.speed_pen
                elif any('B' in s for s in par):
                    penalty = self.mag_pen
 
                print('Penalty = {0:4.3f}'.format(penalty))
                #Switching to my code for penalty (Faster and I have more control)
                ###path = dtw.warping_path(t_mat[par[0]].ffill().bfill().values,
                ###                        p_mat[par[0]].ffill().bfill().values,
                ###                        penalty=penalty)
                x1 = np.array(t_mat[par[0]].ffill().bfill().values,dtype=np.double)
                x2 = np.array(p_mat[par[0]].ffill().bfill().values,dtype=np.double)

                #regularize x1 and x2 using 5 and 95 percentiles
                x1_05,x1_95 = np.percentile(x1,[5,95])
                x2_05,x2_95 = np.percentile(x2,[5,95])

                #regularlize data
                #x1 = (x1-x1_05)/(x1_95-x1_05)
                #x2 = (x2-x2_05)/(x2_95-x2_05)
                
                #did I flip x1 and x2
                flipped =False

                #flip x1 and x2 if x1 is small than x2
                if x2.size > x1.size:
                    x2,x1 = x1,x2
                    flipped =True
                
   
                #Get average time difference
                dt1 = float(np.median(np.diff(t_mat.index))*1.e-9) #seconds
                dt2 = float(np.median(np.diff(p_mat.index))*1.e-9) #seconds
               

                #make the penalty kick in at the 10% level
                penalty_r1 = 60.*pr/np.min([dt1,dt2]) #number of pixels in 65 minutes ((s/m}*(m)/(s)))
                penalty_r2 = 60.*pr/np.max([dt1,dt2]) #number of pixels in 65 minutes ((s/m}*(m)/(s)))
                #find DTW path with some restriction on the allowed time offset 
                path = md.dtw_path_single(x1,x2,penalty_r1,penalty_r2,500.0,100.00,1.10,0)
                #unflip if flipped
                if flipped:
                    path = path[::-1]
                ####reformat in old format 2018/04/20 J. Prchlik
                ###path = np.array(path).T
            #Otherwise you quick DTW solution
            else:
                dist, cost, path = mlpy.dtw_std(t_mat[par[0]].ffill().bfill().values,p_mat[par[0]].ffill().bfill().values,dist_only=False)
            print('STOP WARPING TIME')
        
            #get full offsets for dynamic time warping
            off_sol = (p_mat.iloc[path[1],:].index - t_mat.iloc[path[0],:].index)
            print('REINDEXED')
        
            #get a region around one of the best fit times
            b_mat = p_mat.copy()
        
            #update the time index of the match array for comparision with training spacecraft (i=training spacecraft time)
            b_mat = b_mat.reindex(b_mat.iloc[path[1],:].index) #.interpolate('time')
            b_mat.index = b_mat.index-off_sol
            b_mat['offsets'] = off_sol

            #Add the indices for path1 and path2 2018/11/07 J. Prchlik
            b_mat['train_ind'] = path[0]
            b_mat['match_ind'] = path[1]
        
            #Add offset data frame to plasma diction
            plsm[k+'_offset'] = b_mat

           
            #plot plasma parameters
            #fax[0,0].scatter(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,marker=marker[k],color=color[k],label=k.upper())         
            if len(b_mat[b_mat['Np'   ] > -9990.0]) > 0:
                fax[0,0].scatter(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,marker=marker[k],color=color[k],label=k)
                fax[0,0].plot(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,color=color[k],linewidth=2,label='')
        
            if len(b_mat[b_mat['Vth'  ] > -9990.0]) > 0:
                fax[1,0].scatter(b_mat[b_mat['Vth'  ] > -9990.0].index,b_mat[b_mat['Vth'  ] > -9990.0].Vth  ,marker=marker[k],color=color[k],label=k)
                fax[1,0].plot(b_mat[b_mat['Vth'  ] > -9990.0].index,b_mat[b_mat['Vth'  ] > -9990.0].Vth  ,color=color[k],linewidth=2,label='')
        
            if len(b_mat[b_mat['SPEED'] > -9990.0]) > 0:
                fax[2,0].scatter(b_mat[b_mat['SPEED'] > -9990.0].index,b_mat[b_mat['SPEED'] > -9990.0].SPEED,marker=marker[k],color=color[k])
                fax[2,0].plot(b_mat[b_mat['SPEED'] > -9990.0].index,b_mat[b_mat['SPEED'] > -9990.0].SPEED,color=color[k],linewidth=2)
        
        
            #plot mag. parameters
            if k.lower() != 'soho':
                if len(b_mat[b_mat['Bx']    > -9990.0]) > 0:
                    fax[0,1].scatter(b_mat[b_mat['Bx']    > -9990.0].index,b_mat[b_mat['Bx']    > -9990.0].Bx,marker=marker[k],color=color[k])
                    fax[0,1].plot(b_mat[b_mat['Bx']    > -9990.0].index,b_mat[b_mat['Bx']    > -9990.0].Bx,color=color[k],linewidth=2)
        
                if len(b_mat[b_mat['By']    > -9990.0]) > 0:
                    fax[1,1].scatter(b_mat[b_mat['By']    > -9990.0].index,b_mat[b_mat['By']    > -9990.0].By,marker=marker[k],color=color[k])
                    fax[1,1].plot(b_mat[b_mat['By']    > -9990.0].index,b_mat[b_mat['By']    > -9990.0].By,color=color[k],linewidth=2)
        
                if len(b_mat[b_mat['Bz']    > -9990.0]) > 0:
                    fax[2,1].scatter(b_mat[b_mat['Bz']    > -9990.0].index,b_mat[b_mat['Bz']    > -9990.0].Bz,marker=marker[k],color=color[k])
                    fax[2,1].plot(b_mat[b_mat['Bz']    > -9990.0].index,b_mat[b_mat['Bz']    > -9990.0].Bz,color=color[k],linewidth=2)
        
        
            print('###########################################')
        
        
        #set 0 offsets for training spacecraft
        t_mat['offsets'] = pd.to_timedelta(0) 
        plsm[trainer+'_offset'] = t_mat
        
        
        #plot plasma parameters for Wind
        if len(t_mat[t_mat['Np'   ] > -9990.0]) > 0:
            fax[0,0].scatter(t_mat[t_mat['Np'   ] > -9990.0].index,t_mat[t_mat['Np'   ] > -9990.0].Np   ,marker=marker[trainer],color=color[trainer],label=trainer.upper())
            fax[0,0].plot(t_mat[t_mat['Np'   ] > -9990.0].index,t_mat[t_mat['Np'   ] > -9990.0].Np   ,color=color[trainer],linewidth=2,label='')
        
        if len(t_mat[t_mat['Vth'  ] > -9990.0]) > 0:
            fax[1,0].scatter(t_mat[t_mat['Vth'  ] > -9990.0].index,t_mat[t_mat['Vth'  ] > -9990.0].Vth  ,marker=marker[trainer],color=color[trainer],label=trainer)
            fax[1,0].plot(t_mat[t_mat['Vth'  ] > -9990.0].index,t_mat[t_mat['Vth'  ] > -9990.0].Vth  ,color=color[trainer],linewidth=2,label='')
        
        if len(t_mat[t_mat['SPEED'] > -9990.0]) > 0:
            fax[2,0].scatter(t_mat[t_mat['SPEED'] > -9990.0].index,t_mat[t_mat['SPEED'] > -9990.0].SPEED,marker=marker[trainer],color=color[trainer])
            fax[2,0].plot(t_mat[t_mat['SPEED'] > -9990.0].index,t_mat[t_mat['SPEED'] > -9990.0].SPEED,color=color[trainer],linewidth=2)
        
        
        #plot mag. parameters
        if len(t_mat[t_mat['Bx']    > -9990.0]) > 0:
            fax[0,1].scatter(t_mat[t_mat['Bx'   ] > -9990.0].index,t_mat[t_mat['Bx']    > -9990.0].Bx,marker=marker[trainer],color=color[trainer])
            fax[0,1].plot(t_mat[t_mat['Bx'   ] > -9990.0].index,t_mat[t_mat['Bx']    > -9990.0].Bx,color=color[trainer],linewidth=2)
        
        if len(t_mat[t_mat['By']    > -9990.0]) > 0:
            fax[1,1].scatter(t_mat[t_mat['By'   ] > -9990.0].index,t_mat[t_mat['By']    > -9990.0].By,marker=marker[trainer],color=color[trainer])
            fax[1,1].plot(t_mat[t_mat['By'   ] > -9990.0].index,t_mat[t_mat['By']    > -9990.0].By,color=color[trainer],linewidth=2)
        
        if len(t_mat[t_mat['Bz']    > -9990.0]) > 0:
            fax[2,1].scatter(t_mat[t_mat['Bz'   ] > -9990.0].index,t_mat[t_mat['Bz']    > -9990.0].Bz,marker=marker[trainer],color=color[trainer])
            fax[2,1].plot(t_mat[t_mat['Bz'   ] > -9990.0].index,t_mat[t_mat['Bz']    > -9990.0].Bz,color=color[trainer],linewidth=2)
        
        
        fancy_plot(fax[0,0])
        fancy_plot(fax[1,0])
        fancy_plot(fax[2,0])
        fancy_plot(fax[0,1])
        fancy_plot(fax[1,1])
        fancy_plot(fax[2,1])
        #i = pd.to_datetime("2016/12/21 08:43:12") 
        fax[0,0].set_xlim([start_t,end_t])
        
        fax[0,0].set_ylabel('Np [cm$^{-3}$]',fontsize=20)
        fax[1,0].set_ylabel('Th. Speed [km/s]',fontsize=20)
        fax[2,0].set_ylabel('Flow Speed [km/s]',fontsize=20)
        fax[2,0].set_xlabel('Time [UTC]',fontsize=20)
        
        fax[0,1].set_ylabel('Bx [nT]',fontsize=20)
        fax[1,1].set_ylabel('By [nT]',fontsize=20)
        fax[2,1].set_ylabel('Bz [nT]',fontsize=20)
        fax[2,1].set_xlabel('Time [UTC]',fontsize=20)
        
        fax[1,0].set_ylim([0.,100.])


        #add legend to plot
        fax[0,0].legend(loc='upper right',frameon=False)
        
        
        #turn into data frame 
        frm_vs = pd.DataFrame(top_vs)
        #add columns
        col_add = ['X','Y','Z','Vx','Vy','Vz']
        for i in col_add: frm_vs[i] = -9999.9



        #Updated self plasma dictionary
        self.plsm = plsm
        self.fig, self.fax = fig,fax
        
        #Do not need this 2018/03/21 J. Prchlik
        ####Use wind CDF to get velocity comps
        ####cdf = pycdf.CDF('/Volumes/Pegasus/jprchlik/dscovr/solar_wind_events/cdf/wind/plsm/wi_h1_swe_20161221_v01.cdf')
        ####
        ####wind_vx = cdf['Proton_VX_nonlin'][...]
        ####wind_vy = cdf['Proton_VY_nonlin'][...]
        ####wind_vz = cdf['Proton_VZ_nonlin'][...]
        ####wind_t0 = cdf['Epoch'][...]
        ####
        ####cdf.close()
        ####
        #####create pandas dataframe with wind components
        ####wind_v = pd.DataFrame(np.array([wind_t0,wind_vx,wind_vy,wind_vz]).T,columns=['time_dt','Vx','Vy','Vz'])
        ####wind_v.set_index(wind_v.time_dt,inplace=True)
        #big list of velocities
        #big_lis = []

    def pred_earth(self,cut_deg=70.):
        """
        Create prediction for solar wind speed at near earth spacecraft and create corresponding plots
    
        Parameters
        ----------
        cut_deg: float
            Cut calculated normal vectors more than cut_deg away from [-1.,0.,0.]
            GSE to removed from the prediction (Default = 70, Weimer et al. 2003).

        Returns
        -------
        None
    
        """
    
        #Use common names for self variables
        t_mat = self.t_mat
        plsm  = self.plsm
        Re = self.Re # Earth radius
        start_t  = self.start_t 
        end_t    = self.end_t   
        center   = self.center  
        par      = self.par     
        justparm = self.justparm
        marker   = self.marker
        color    = self.color
        pad = self.pad
        fig, fax = self.fig,self.fax
        
        #set use to use all spacecraft
        craft = self.craft #['Wind','DSCOVR','ACE','SOHO']
        col   = self.col   #['blue','black','red','teal']
        mar   = self.mar   #['D','o','s','<']
        trainer = self.trainer
        
        #range to find the best maximum value
        maxrang = pd.to_timedelta('3 minutes')
    
        #Find points with the largest speed differences in wind
        #Allow dyanic allocation of top events 2018/05/17 J. Prchlik
        top_vs = (plsm[trainer].SPEED.dropna().diff().abs()/plsm[trainer].SPEED.dropna()).nlargest(self.events)
        
        
        #sort by time for event number
        top_vs.sort_index(inplace=True)
    
    
    
        
    
    
        #Add plot for prediction on THEMIS
        fig_th,ax_th = plt.subplots()
        #Add plot with just the THEMIS plasma data
        for esp in self.earth_craft:
            slicer = np.isfinite(plsm[esp].SPEED)
            ax_th.plot(plsm[esp].loc[slicer,:].index,pd.rolling_mean(plsm[esp].loc[slicer,:].SPEED,25),color=color[esp],label=esp.upper(),zorder=100,linewidth=2)
    
        ax_th.set_xlim([pd.to_datetime(self.start_t)-pad,pd.to_datetime(self.end_t)+pad])
        ax_th.set_xlabel('Time [UTC]')
        ax_th.set_ylabel('Flow Speed [km/s]')
        fancy_plot(ax_th)
    
    
        #create dictionary of values for each event 2018/04/24 J. Prchlik
        self.event_dict = {}
        #Store arrival times and plasma parameters in seperate array
        #to call when comparing with omni prediction
        for esp in self.earth_craft:
            self.event_dict[esp+'_time'] = []
            self.event_dict[esp+'_plsm'] = []
            self.event_dict[esp+'_velo'] = []
            self.event_dict[esp+'_dist'] = []
            self.event_dict[esp+'_nvec'] = []
    
        #List of time and Speed value of events J. Prchlik
        event_plot = []
    
        #time delta to skip at the beginning and end due to compression in DTW
        dtw_skp = pd.to_timedelta('45m')
        dtw_stt = pd.to_datetime(self.start_t) 
        dtw_end = pd.to_datetime(self.end_t) 
    
        
        #Plot the top shock values
        #fax[2,0].scatter(t_mat.loc[top_vs.index,:].index,t_mat.loc[top_vs.index,:].SPEED,color='purple',marker='X',s=150)
        #for j,i in enumerate(top_vs.index):
        #try producing continous plot 2018/05/17 J. Prchlik
        #This method did not work
        #Trying again with multi parameter approach 2018/07/26 J. Prchlik
        #Trying everytin again using the core of the observation 
        #And my new DTW alogrithm
        for j,i in enumerate(t_mat.index):
            #skip the first and last 45 minutes for removing compression artifacts
            if ((i-dtw_stt < dtw_skp) | (dtw_end-i < dtw_skp)):
                continue
    
            #get particular speed value
            yval = t_mat.loc[i,:].SPEED
            yvalb = 0.
            xval = mdates.date2num(i)
    
            #try producing continous plot 2018/05/17 J. Prchlik
            #Removing 2017/07/26 J. Prchlk
            #fax[2,0].annotate('Event {0:1d}'.format(j+1),xy=(xval,yval),xytext=(xval,yval+50.),
            #                  arrowprops=dict(facecolor='purple',shrink=0.005))
            #fax[2,1].annotate('Event {0:1d}'.format(j+1),xy=(xval,yvalb),xytext=(xval,yvalb+2.),
            #                  arrowprops=dict(facecolor='purple',shrink=0.005))
    
    
            #computer surface for events
            #tvals = -np.array([np.mean(plsm[c+'_offset'].loc[i,'offsets']).total_seconds() for c in craft])
            #xvals = np.array([np.mean(plsm[c].loc[i,'GSEx']) for c in craft])
            #yvals = np.array([np.mean(plsm[c].loc[i,'GSEy']) for c in craft])
            #zvals = np.array([np.mean(plsm[c].loc[i,'GSEz']) for c in craft])
            #Switched to one loop 2018/03/07
            tvals = [] #-np.array([np.mean(plsm[c+'_offset'].loc[i,'offsets']).total_seconds() for c in craft])
            xvals = [] #np.array([np.mean(plsm[c].loc[i,'GSEx']) for c in craft])
            yvals = [] #np.array([np.mean(plsm[c].loc[i,'GSEy']) for c in craft])
            zvals = [] #np.array([np.mean(plsm[c].loc[i,'GSEz']) for c in craft])
         
            #create master event dictionary for given event to store parameters
            cur = 'event_{0:1d}'.format(j+1)
            self.event_dict[cur] = {}
           
        
            #loop over all craft and populate time and position arrays
            for c in craft:
                #append craft values onto time and position arrays
                #changed to min values 2018/03/12 J. Prchlik
                try:
                    itval = plsm[c+'_offset'].loc[i,:].offsets
                #Fix THEMIS having out of range index
                except KeyError:
                    check = plsm[c+'_offset'].GSEx.dropna().index.get_loc(i,method='nearest')
                    it = plsm[c+'_offset'].GSEx.dropna().index[check]
                    itval = plsm[c+'_offset'].loc[it,:].offsets
                    
                #Switch to first value to have a matched time if multiple values
                #map to the "trainer" space craft time 2018/11/19 J. Prchlik
                #Previously idd closest to 0
                if isinstance(itval,pd._libs.tslib.Timedelta):
                    off_cor = itval.total_seconds()
                    tvals.append(itval.total_seconds())
                elif isinstance(itval,pd.Series):
                    off_cor = min(itval).total_seconds()
                    tvals.append(min(itval).total_seconds())
    
                #Get closest index value location
                #Update with time offset implimented
                ii = plsm[c].GSEx.dropna().index.get_loc(i+pd.to_timedelta(off_cor,unit='s'),method='nearest')
                #convert index location back to time index
                it = plsm[c].GSEx.dropna().index[ii]
    
                #Use offset pandas DF position 2018/04/25 J. Prchlik
                xvals.append(np.mean(plsm[c].iloc[ii,:].GSEx))
                yvals.append(np.mean(plsm[c].iloc[ii,:].GSEy))
                zvals.append(np.mean(plsm[c].iloc[ii,:].GSEz))
        
            #Covert arrays into numpy arrays and flip sign of offset
            self.event_dict[cur]['tvals'] = np.array(tvals)
            self.event_dict[cur]['xvals'] = np.array(xvals) 
            self.event_dict[cur]['yvals'] = np.array(yvals) 
            self.event_dict[cur]['zvals'] = np.array(zvals) 
            #Print position values and time values
        
            #get the velocity components with respect to the shock front at wind
            #i_val = wind_v.index.get_loc(i,method='nearest')
            #vx = wind_v.iloc[i_val].Vx
            #vy = wind_v.iloc[i_val].Vy
            #vz = wind_v.iloc[i_val].Vz
            #use positions and vectors to get a solution for plane velocity
            pm  = np.matrix([xvals[1:4]-xvals[0],yvals[1:4]-yvals[0],zvals[1:4]-zvals[0]]).T #coordinate of craft 1 in top row
            tm  = np.matrix(tvals[1:4]).T # 1x3 matrix of time (wind-spacecraft)
            vna,vn,vm = solve_plane(pm,tm)
            #vna = np.linalg.solve(pm,tm) #solve for the velocity vectors normal
            #vn  = vna/np.linalg.norm(vna)
            #vm  = 1./np.linalg.norm(vna) #get velocity magnitude


            #Check that angle is less than 70 deg. from -X GSE following Weimer et al (2003)
            #2018/11/20 J. Prchlik
            theta = np.degrees(np.arccos(float(vn.T.dot([-1.,0.,0.]))))

            #replace vn,vm with the previous value if theta is greater than 70 degree
            if ((theta > cut_deg) & (len(self.event_dict[esp+'_velo']) > 0)):
                vm = self.event_dict[esp+'_velo'][-1]
                vn = np.matrix(self.event_dict[esp+'_nvec'][-1]).T
            #Skip the prediction if there are no good previous values
            elif ((theta > cut_deg) & (len(self.event_dict[esp+'_velo']) < 1)):
                continue
            
            
            #store vx,vy,vz values
            self.event_dict[cur]['vx'],self.event_dict[cur]['vy'],self.event_dict[cur]['vz'] = vm*np.array(vn).ravel()
            #store normal vector 2018/04/24 J. prchlik
            self.event_dict[cur]['vn'] = vn
            self.event_dict[cur]['vm'] = vm
        
            #get the 4 point location of the front when at wind
            #p_x(t0)1 = p_x(t1)-V_x*dt where dt = t1-t0  
            #solving exactly
            #use the velocity matrix solution to get the solution for the plane analytically
            #2018/03/15 J. Prchlik
            #px = -vx*tvals+xvals
            #py = -vy*tvals+yvals
            #pz = -vz*tvals+zvals
            self.event_dict[cur]['wind_px'] = xvals[0]
            self.event_dict[cur]['wind_py'] = yvals[0]
            self.event_dict[cur]['wind_pz'] = zvals[0]
    
            #Wind position to determine starting point  2018/05/24 J. Prchlik
            px = xvals[0]
            py = yvals[0]
            pz = zvals[0]
    
            for esp in self.earth_craft:
                ################################################################
                #Get THEMIS B location and compare arrival times
                ################################################################
                #
                #
                #Get closest index value location
                #Fix THEMIS having out of range index
                try:
                    itval = plsm[esp+'_offset'].loc[i,:].offsets
                    #Get time of observation in THEMIS B
                    itind = pd.to_datetime(plsm[esp+'_offset'].loc[i,'Time'])
                    it = i
                #Fix THEMIS having out of range index
                except KeyError:
                    check = plsm[esp+'_offset'].GSEx.dropna().index.get_loc(i,method='nearest')
                    it = plsm[esp+'_offset'].GSEx.dropna().index[check]
                    itval = plsm[esp+'_offset'].loc[it,:].offsets
                    #Get time of observation in THEMIS B
                    itind = pd.to_datetime(plsm[esp+'_offset'].loc[it,'Time'])
    
                #Get first match if DTW produces more than one
                if isinstance(itind,pd.Series): itind = itind.dropna()[1]
                if isinstance(itval,pd._libs.tslib.Timedelta):
                    atval = itval.total_seconds()
                elif isinstance(itval,pd.Series):
                    atval = np.mean(itval).total_seconds() #,key=abs).total_seconds()
    
                #Store THEMIS position
                axval = np.mean(plsm[esp+'_offset'].loc[it,'GSEx'])
                ayval = np.mean(plsm[esp+'_offset'].loc[it,'GSEy'])
                azval = np.mean(plsm[esp+'_offset'].loc[it,'GSEz'])
    
                ################################################################
                ################################################################
    
                #parameters to add
                #Switched to dictionary 2018/04/24 J. Prchlik
                #add_lis = [vx,vy,vz,tvals,vm,vn,px,py,pz]
                #big_lis.append(add_lis)
                #Wind Themis B distance difference from plane at wind
                themis_d = float(vn.T.dot((np.matrix([axval,ayval,azval])-np.matrix([px,py,pz])).T))
                themis_dt = float(themis_d)/vm
                themis_pr = i+pd.to_timedelta(themis_dt,unit='s')
    
                #Try to print prediction, but if it fails just move on 2018/05/17 J. Prchlik
                try:
                   # print('Arrival Time {0:%Y/%m/%d %H:%M:%S} at Wind'.format(i))
                   test = 'Arrival Time {0:%Y/%m/%d %H:%M:%S} at Wind'.format(i)
                   test = ('Predicted Arrival Time at {2} {0:%Y/%m/%d %H:%M:%S}, Distance = {1:4.1f}km'.format(themis_pr,themis_d,esp.upper()))
                   test = ('Actual Arrival Time at {2} {0:%Y/%m/%d %H:%M:%S}, Offset (Pred.-Act.) = {1:4.2f}s'.format(itind,themis_dt-atval,esp.upper()))
                except:
                    continue
                
    
                #Use wind parameters to predict shock location 2018/04/25 J. Prchlik
                th_yval = t_mat.loc[i,:].SPEED
                th_xval = mdates.date2num(themis_pr)
                rl_xval = mdates.date2num(itind)
                    
                #plot parameters from wind prediction 2018/05/17 J. Prchlik
                ax_th.scatter(th_xval,th_yval,color='blue',label=None)
    
                #Store the prediction in array for plotting and comparing to omni
                self.event_dict[esp+'_time'].append(th_xval)
                self.event_dict[esp+'_plsm'].append(th_yval)
                self.event_dict[esp+'_velo'].append(vm)
                self.event_dict[esp+'_nvec'].append(vn.ravel())
                self.event_dict[esp+'_dist'].append(themis_d)
    
    
    
                #change to line at wind 2018/05/17
                #Add predicted THEMIS plot
                #Remove 2018/07/26 J. Prchlik
                #ax_th.annotate('Event {0:1d} at {1}'.format(j+1,esp.upper()),xy=(th_xval,th_yval),xytext=(th_xval,th_yval+50.),
                #          arrowprops=dict(facecolor='purple',shrink=0.005))
                ###Add Actual to THEMIS plot 2018/05/03 J. Prchlik
                ##ax_th.annotate('Event {0:1d} at {1}'.format(j+1,esp.upper()),xy=(rl_xval,th_yval),xytext=(rl_xval,th_yval-50.),
                ##          arrowprops=dict(facecolor='red',shrink=0.005))
                #store speed and time values
                event_plot.append([th_xval,th_yval])
                event_plot.append([rl_xval,th_yval])
    
            #put values in new dataframe
            #for l in range(len(col_add)):
            #    frm_vs.loc[i,col_add[l]] = add_lis[l] 
        
        #turn big lis into numpy array
        #I don't need to do this 2018/03/15 J. Prchlik
        #big_lis = np.array(big_lis)
        
        
        fig.autofmt_xdate()
                        
        #Puff up y-limit 2018/05/03 J. Prchlik
        ylims = np.array(fax[2,0].get_ylim())
        #if ylim min less than 0 set to 250
        if ylims[0] < 0:
            ylims[0] = 250. 
    
        yrang = abs(ylims[1]-ylims[0])
        fax[2,0].set_ylim([ylims[0],ylims[1]+.1*yrang])
        #Save time warping plot
        fig.savefig('../plots/bou_{0:%Y%m%d_%H%M%S}.png'.format(pd.to_datetime(start_t)),bbox_pad=.1,bbox_inches='tight')
        
        #set up date and time ranges 2018/05/03 J. Prchlik
        event_plot = np.array(event_plot)
        min_val = event_plot.min(axis=0)
        max_val = event_plot.max(axis=0)
        rng_val = max_val-min_val
    
       
        #save resulting THEMIS plot 2018/04/25 J. Prchlik
        xlims = np.array(ax_th.get_xlim())
        ax_th.set_ylim([ylims[0],ylims[1]+.1*yrang])
    
        #include earth pad offset in time range 2018/05/04 J. Prchlik 
        xlims += self.pad_earth.total_seconds()/24./3600.
    
        #Add 10% padding around plot time window for events
        #increase time range if needed
        test_xmin = min_val[0]-.1*rng_val[0]
        test_xmax = max_val[0]+.1*rng_val[0]
        if test_xmin < xlims[0]:
            xlims[0] = test_xmin
        if test_xmax > xlims[1]:
            xlims[1] = test_xmax
    
    
        #use pretty axis and save
        ax_th.set_xlim(xlims)
        ax_th.legend(loc='best',frameon=False)
        fig_th.savefig('../plots/themis_pred_{0:%Y%m%d_%H%M%S}.png'.format(pd.to_datetime(start_t)),bbox_pad=.1,bbox_inches='tight')
        
        
        
    
    
        #Do not run animation sequence if asked to stop and return with just parameters
        #Returns vx,vy,vz,tvals,Vmag,Vnoraml,X,Y,Z
        #Switched to self.event_dict dictionary 2018/04/24 J. Prchlik
        if justparm: return 

    def dtw_multi_parm(self,twind):
        """
        Finds planar solution to 4 L1 spacecraft
     
        Parameters
        ----------
 
        self: Class
        twind: datetime object
             The rough time of discontinuity in the Trainer Spacecraft, which is used to time weight the fit

 
        """
        from tslearn import metrics
        from tslearn.preprocessing import TimeSeriesScalerMinMax,TimeSeriesScalerMeanVariance


        #Creating modular solution for DTW 2018/03/21 J. Prchlik
        ##set the Start and end time
        #start_t = "2016/12/21 07:00:00"
        #end_t = "2016/12/21 13:00:00"
        #center = True
        #reset variables to local variables
        Re = self.Re # Earth radius
        start_t  = self.start_t 
        end_t    = self.end_t   
        center   = self.center  
        par      = self.par     
        justparm = self.justparm
        marker   = self.marker
        color    = self.color
        
        #set use to use all spacecraft
        craft = self.craft #['Wind','DSCOVR','ACE','SOHO']
        col   = self.col   #['blue','black','red','teal']
        mar   = self.mar   #['D','o','s','<']
        trainer = self.trainer
        
        #range to find the best maximum value
        maxrang = pd.to_timedelta('3 minutes')
        
        
        #create new plasma dictory which is a subset of the entire file readin
        plsm = {}
        for i in craft:
             plsm[i] = self.plsm[i] #[start_t:end_t] Cutting not required because already using a small sample 2018/05/03 J. Prchlik
             #remove duplicates
             plsm[i] = plsm[i][~plsm[i].index.duplicated(keep='first')]

        #get all values at full resolution for dynamic time warping
        t_mat  = plsm[trainer] #.loc[trainer_t-t_rgh_wid:trainer_t+t_rgh_wid]
  
        #add trainer matrix to self
        self.t_mat = t_mat


        #parameters to replace bad values
        #par = ['SPEED','Np','Vth','Bx','By','Bz']
        par = ['SPEED','Bx','By','Bz']
        #par = ['SPEED','Bt']

        #fill all Nans in data series with forward values first and then back fill the first times
        #ffil inf values
        t_mat.replace(to_replace=np.inf,value=np.nan,inplace=True)
        t_mat.replace(to_replace=-np.inf,value=np.nan,inplace=True)
        #ffil bad values
        for p in par:
            bad=((t_mat[p] > 80000.) | (t_mat[p] < -80000.))
            t_mat.loc[bad,p] = np.nan
    
        #fill bad values first forward then backward for the starting time
        t_mat = t_mat.ffill().bfill()


        #Find points with the largest speed differences in wind
        top_vs = (t_mat.SPEED.dropna().diff().abs()/t_mat.SPEED.dropna()).nlargest(self.events)
        
        #sort by time for event number
        top_vs.sort_index(inplace=True)
        
        #add to self
        self.top_vs = top_vs

        #plot with the best timing solution
        self.fig, self.fax = plt.subplots(ncols=2,nrows=3,sharex=True,figsize=(18,18))
        fig, fax = self.fig,self.fax

       
        #set range to include all top events (prevents window too large error
        self.pad = pd.to_timedelta('30 minutes')
        pad = self.pad
        fax[0,0].set_xlim([top_vs.index.min()-pad,top_vs.index.max()+pad])
        
        #loop over all other craft
        for k in craft[1:]:
            print('###########################################')
            print(k)
            p_mat  = plsm[k] #.loc[i_min-t_rgh_wid:i_min+t_rgh_wid]
        
            #use speed for rough esimation if possible
            #if  ((k.lower() == 'soho') ): par = ['SPEED','Np','Vth']
            #elif (((par is None) | (isinstance(par,float))) & (k.lower() != 'soho')): par = ['SPEED','Np','Vth','Bx','By','Bz','Bt'] #Add Total magnetic field 2018/09/07 J. Prchlik
            #Try just speed and magnetic field 2108/09/07 J. Prchlik
            if  ((k.lower() == 'soho') ): 
                par = ['SPEED']
            elif (((par is None) | (isinstance(par,float))) & (k.lower() != 'soho')):
                par = ['Bx','By','Bz'] #Add Total magnetic field 2018/09/07 J. Prchlik
            elif isinstance(par,str):
                par = [par]
            else:
                 par = par

            print(par)

            #Get and record differences and add to x_vals
            #t_mat,x_vals = get_x_difference(t_mat,par)       
            x_vals = par

            #set up variables for training set
            X_train = t_mat[x_vals].values

            #Include a time normalization
            normer_train = t_mat.index.values.astype('float64')

            min_train = normer_train.min()
            max_train = normer_train.max()

            #create normalization values
            normer_train = dtw_wei(normer_train,twind,b=5./((max_train-min_train)/2.)**2.,c=1.)

            #expand array so you can simply multiply
            normer_train = np.outer(normer_train,np.ones(X_train.shape[1]))

            #include a time normalization factor
            #X_train *= normer_train

            #time values trying to match
            y_train = t_mat.index.values
        
            #get the median slope and offset
            #J. Prchlik (2017/11/20)
            #Dont use interpolated time for solving dynamic time warp (J. Prchlik 2017/12/15)
            #only try SPEED corrections for SOHO observations
            #Only apply speed correction after 1 iteration (J. Prchlik 2017/12/18)
   
            #Switched to standardized variables 2018/07/31 J. Prchlik
            #Turned back on 
            if (('themis' in k.lower())):
                try:
                    #create copy of p_mat
                    c_mat = p_mat.copy()
                    #resample the matching (nontrained spacecraft to the trained spacecraft's timegrid to correct offset (2017/12/15 J. Prchlik)
                    c_mat = c_mat.reindex(t_mat.index,method='nearest').interpolate('time')
         
                    #only comoare no NaN values
                    good, = np.where(((np.isfinite(t_mat.SPEED.values)) & (np.isfinite(c_mat.SPEED.values))))
         
                    #if few points for comparison only used baseline offset
                    if ((good.size < 1E36) & (par[0] == 'SPEED')):
                        med_m,med_i = 1.0,0.0
                        off_speed = p_mat.SPEED.median()-t_mat.SPEED.median()
                        p_mat.SPEED = p_mat.SPEED-off_speed
                        if med_m > 0: p_mat.SPEED = p_mat.SPEED*med_m+med_i
                    else:
                        off_speed = p_mat.SPEED.nsmallest(20).median()-t_mat.SPEED.nsmallest(20).median()
                        p_mat.SPEED = p_mat.SPEED-off_speed
                    #only apply slope if greater than 0
                except IndexError:
                #get median offset to apply to match spacecraft
                    off_speed = p_mat.SPEED.nsmallest(20).median()-t_mat.SPEED.nsmallest(20).median()
                    p_mat.SPEED = p_mat.SPEED-off_speed
         
         
            #ffil inf values
            p_mat.replace(to_replace=np.inf,value=np.nan,inplace=True)
            p_mat.replace(to_replace=-np.inf,value=np.nan,inplace=True)
            #ffil bad values
            for p in par:
                bad=((p_mat[p] > 80000.) | (p_mat[p] < -80000.))
                p_mat.loc[bad,p] = np.nan

            #fill all Nans in data series with forward values first and then back fill the first times
            p_mat = p_mat.ffill().bfill()
            #Get and record differences and add to x_vals
            #p_mat,x_vals = get_x_difference(p_mat,par)
            x_vals = par



            #set up variables for test set
            X_tests = p_mat[x_vals].values

            #Include a time normalization
            normer_tests = p_mat.index.values.astype('float64')


            #create normalization values
            normer_tests = dtw_wei(normer_tests,twind,b=5./((max_train-min_train)/2.)**2.,c=1.)
            normer_tests = np.outer(normer_tests,np.ones(X_tests.shape[1]))

            #include a time normalization factor
            #X_tests *= normer_tests

            y_tests = p_mat.index.values
         

            #Scale the parameter to have a mean of 0 and a varience of 1
            scaler = TimeSeriesScalerMeanVariance(mu=0.,std=1.)
            #scaler = TimeSeriesScalerMinMax(min=0., max=1.)  # Rescale time series
            for kk in range(X_train.shape[1]):
                X_train[:,kk] = scaler.fit_transform(X_train[:,kk])[0].ravel()
                X_tests[:,kk] = scaler.fit_transform(X_tests[:,kk])[0].ravel()



            #get dynamic time warping value   
            print('WARPING TIME')
            #get multi-parameter dtw solution
            #path, sim = metrics.dtw_path(X_train, X_tests)
            path, sim = metrics.dtw_path(X_train, X_tests,global_constraint='sakoe_chiba',sakoe_chiba_radius=1550)
            #convert path into a numpy array
            path = np.array(zip(*path))
            print('STOP WARPING TIME')
        
            #get full offsets for dynamic time warping
            off_sol = (p_mat.iloc[path[1],:].index - t_mat.iloc[path[0],:].index)
            print('REINDEXED')
        
            #get a region around one of the best fit times
            b_mat = p_mat.copy()
        
            #update the time index of the match array for comparision with training spacecraft (i=training spacecraft time)
            b_mat = b_mat.reindex(b_mat.iloc[path[1],:].index) #.interpolate('time')
            b_mat.index = b_mat.index-off_sol
            b_mat['offsets'] = off_sol
        
            #Add offset data frame to plasma diction
            plsm[k+'_offset'] = b_mat
            #plot plasma parameters
            #fax[0,0].scatter(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,marker=marker[k],color=color[k],label=k.upper())         
            if len(b_mat[b_mat['Np'   ] > -9990.0]) > 0:
                fax[0,0].scatter(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,marker=marker[k],color=color[k],label=k)
                fax[0,0].plot(b_mat[b_mat['Np'   ] > -9990.0].index,b_mat[b_mat['Np'   ] > -9990.0].Np   ,color=color[k],linewidth=2,label='')
        
            if len(b_mat[b_mat['Vth'  ] > -9990.0]) > 0:
                fax[1,0].scatter(b_mat[b_mat['Vth'  ] > -9990.0].index,b_mat[b_mat['Vth'  ] > -9990.0].Vth  ,marker=marker[k],color=color[k],label=k)
                fax[1,0].plot(b_mat[b_mat['Vth'  ] > -9990.0].index,b_mat[b_mat['Vth'  ] > -9990.0].Vth  ,color=color[k],linewidth=2,label='')
        
            if len(b_mat[b_mat['SPEED'] > -9990.0]) > 0:
                fax[2,0].scatter(b_mat[b_mat['SPEED'] > -9990.0].index,b_mat[b_mat['SPEED'] > -9990.0].SPEED,marker=marker[k],color=color[k])
                fax[2,0].plot(b_mat[b_mat['SPEED'] > -9990.0].index,b_mat[b_mat['SPEED'] > -9990.0].SPEED,color=color[k],linewidth=2)
        
        
            #plot mag. parameters
            if k.lower() != 'soho':
                if len(b_mat[b_mat['Bx']    > -9990.0]) > 0:
                    fax[0,1].scatter(b_mat[b_mat['Bx']    > -9990.0].index,b_mat[b_mat['Bx']    > -9990.0].Bx,marker=marker[k],color=color[k])
                    fax[0,1].plot(b_mat[b_mat['Bx']    > -9990.0].index,b_mat[b_mat['Bx']    > -9990.0].Bx,color=color[k],linewidth=2)
        
                if len(b_mat[b_mat['By']    > -9990.0]) > 0:
                    fax[1,1].scatter(b_mat[b_mat['By']    > -9990.0].index,b_mat[b_mat['By']    > -9990.0].By,marker=marker[k],color=color[k])
                    fax[1,1].plot(b_mat[b_mat['By']    > -9990.0].index,b_mat[b_mat['By']    > -9990.0].By,color=color[k],linewidth=2)
        
                if len(b_mat[b_mat['Bz']    > -9990.0]) > 0:
                    fax[2,1].scatter(b_mat[b_mat['Bz']    > -9990.0].index,b_mat[b_mat['Bz']    > -9990.0].Bz,marker=marker[k],color=color[k])
                    fax[2,1].plot(b_mat[b_mat['Bz']    > -9990.0].index,b_mat[b_mat['Bz']    > -9990.0].Bz,color=color[k],linewidth=2)
        
        
            print('###########################################')
        
        
        #set 0 offsets for training spacecraft
        t_mat['offsets'] = pd.to_timedelta(0) 
        plsm[trainer+'_offset'] = t_mat
        
        
        #plot plasma parameters for Wind
        if len(t_mat[t_mat['Np'   ] > -9990.0]) > 0:
            fax[0,0].scatter(t_mat[t_mat['Np'   ] > -9990.0].index,t_mat[t_mat['Np'   ] > -9990.0].Np   ,marker=marker[trainer],color=color[trainer],label=trainer.upper())
            fax[0,0].plot(t_mat[t_mat['Np'   ] > -9990.0].index,t_mat[t_mat['Np'   ] > -9990.0].Np   ,color=color[trainer],linewidth=2,label='')
        
        if len(t_mat[t_mat['Vth'  ] > -9990.0]) > 0:
            fax[1,0].scatter(t_mat[t_mat['Vth'  ] > -9990.0].index,t_mat[t_mat['Vth'  ] > -9990.0].Vth  ,marker=marker[trainer],color=color[trainer],label=trainer)
            fax[1,0].plot(t_mat[t_mat['Vth'  ] > -9990.0].index,t_mat[t_mat['Vth'  ] > -9990.0].Vth  ,color=color[trainer],linewidth=2,label='')
        
        if len(t_mat[t_mat['SPEED'] > -9990.0]) > 0:
            fax[2,0].scatter(t_mat[t_mat['SPEED'] > -9990.0].index,t_mat[t_mat['SPEED'] > -9990.0].SPEED,marker=marker[trainer],color=color[trainer])
            fax[2,0].plot(t_mat[t_mat['SPEED'] > -9990.0].index,t_mat[t_mat['SPEED'] > -9990.0].SPEED,color=color[trainer],linewidth=2)
        
        
        #plot mag. parameters
        if len(t_mat[t_mat['Bx']    > -9990.0]) > 0:
            fax[0,1].scatter(t_mat[t_mat['Bx'   ] > -9990.0].index,t_mat[t_mat['Bx']    > -9990.0].Bx,marker=marker[trainer],color=color[trainer])
            fax[0,1].plot(t_mat[t_mat['Bx'   ] > -9990.0].index,t_mat[t_mat['Bx']    > -9990.0].Bx,color=color[trainer],linewidth=2)
        
        if len(t_mat[t_mat['By']    > -9990.0]) > 0:
            fax[1,1].scatter(t_mat[t_mat['By'   ] > -9990.0].index,t_mat[t_mat['By']    > -9990.0].By,marker=marker[trainer],color=color[trainer])
            fax[1,1].plot(t_mat[t_mat['By'   ] > -9990.0].index,t_mat[t_mat['By']    > -9990.0].By,color=color[trainer],linewidth=2)
        
        if len(t_mat[t_mat['Bz']    > -9990.0]) > 0:
            fax[2,1].scatter(t_mat[t_mat['Bz'   ] > -9990.0].index,t_mat[t_mat['Bz']    > -9990.0].Bz,marker=marker[trainer],color=color[trainer])
            fax[2,1].plot(t_mat[t_mat['Bz'   ] > -9990.0].index,t_mat[t_mat['Bz']    > -9990.0].Bz,color=color[trainer],linewidth=2)
        
        
        fancy_plot(fax[0,0])
        fancy_plot(fax[1,0])
        fancy_plot(fax[2,0])
        fancy_plot(fax[0,1])
        fancy_plot(fax[1,1])
        fancy_plot(fax[2,1])
        #i = pd.to_datetime("2016/12/21 08:43:12") 
        fax[0,0].set_xlim([start_t,end_t])
        
        fax[0,0].set_ylabel('Np [cm$^{-3}$]',fontsize=20)
        fax[1,0].set_ylabel('Th. Speed [km/s]',fontsize=20)
        fax[2,0].set_ylabel('Flow Speed [km/s]',fontsize=20)
        fax[2,0].set_xlabel('Time [UTC]',fontsize=20)
        
        fax[0,1].set_ylabel('Bx [nT]',fontsize=20)
        fax[1,1].set_ylabel('By [nT]',fontsize=20)
        fax[2,1].set_ylabel('Bz [nT]',fontsize=20)
        fax[2,1].set_xlabel('Time [UTC]',fontsize=20)
        
        fax[1,0].set_ylim([0.,100.])
        
        
        #turn into data frame 
        frm_vs = pd.DataFrame(top_vs)
        #add columns
        col_add = ['X','Y','Z','Vx','Vy','Vz']
        for i in col_add: frm_vs[i] = -9999.9



        #Updated self plasma dictionary
        self.plsm = plsm

#plot distribution of time offsets as a function of time in wind of SOHO, ACE, DSCVOR
def plot_time_dis(self):
    """
    Plot the distribution of time offsets between SOHO, ACE, and DSCOVR and Wind.
    The function creates a plot at ../plots/two_d_his.png

    Parameters
    ----------
    self: class
        A dtw_plane class instance after running iterate DTW.

    Returns
    -------
    None

    """

    #get DTW offset keys from plasma dictionary
    off_keys = [i for i in self.plsm.keys() if (('offset' in i) & (i.replace('_offset','') 
                not in self.earth_craft) & (i.replace('_offset','') != self.trainer))]

    #time range
    time = self.plsm[off_keys[0]].index.values.astype(float)*1e-9
    #Set up bins for Heat map
    resx = int(6e1) #1 minutes
    resy = int(1e1) #10 seconds
    xbins = np.arange(time.min(),time.max(),resx)
    ybins = np.arange(-int(3.6e3),int(3.6e3),resy)#1 hour around time offset

    #set up color map
    ccmap = plt.cm.viridis.reversed()
    ccmap.set_under('1.00')
    #create a figure with as many columns as off_keys 
    fig, fax = plt.subplots(ncols=len(off_keys),figsize=(6*len(off_keys),6),sharex=True,sharey=True)
    fax = fax.flatten()


    #pandas start and end times as datetime objects
    pd_s = pd.to_datetime(self.start_t)
    pd_e = pd.to_datetime(self.end_t)
    pd_p = pd.to_timedelta('30m')
    #get middle point of DTW range
    pd_m = (pd_e-pd_s)/2.+pd_s


    #loop over all keys
    for j,i in enumerate(off_keys):

        #convert from ns to s
        xvals = self.plsm[i].loc[pd_m-pd_p:pd_m+pd_p].index.values.astype(float)*1e-9
        yvals = self.plsm[i].loc[pd_m-pd_p:pd_m+pd_p]['offsets'].values.astype(float)*1e-9
        print(np.median(yvals),i)

        #create two D histogram
        H,xedges,yedges = np.histogram2d(xvals,yvals,bins=(xbins,ybins))
        H = H.T #transpose for plotting

        X, Y = np.meshgrid(xedges, yedges)
        plotc = fax[j].pcolormesh(X,Y,H,label=None,cmap=ccmap,vmin=1,vmax=50)
        fax[j].set_title(i.replace('_offset','').upper())
        fax[j].set_xlabel('Time [UTC]')
        fax[j].set_ylabel('Offset from Wind [s]')
        fancy_plot(fax[j])


    fig.savefig('../plots/two_d_his.png',bbox_pad=.1,bbox_inches='tight')
#    fig.savefig('../plots/two_d_his.eps',bbox_pad=.1,bbox_inches='tight')
    plt.close(fig)

#get difference in parameter values for DTW
def get_x_difference(df,diff_v):
    """
    df: pandas data frame of solar wind observations
    diff_v: list of parameters to compute the difference for

    """

    #Get difference values and stor
    new = ['diff_'+i for i in diff_v]
    df[new] = df[diff_v].diff().bfill()
    diff_v = diff_v+new

    return df,diff_v

#create an equation to wieght the observation of the form y = b*(x-a)^2+c
def dtw_wei(x,t0,b=0.3,c=1):
    """
    x: a time range in nanoseconds
    t0: the central time point in nanoseconds
    """
    return b*(x-t0.value)**2+c

def plot_dtw_example(self,c_time,compare=['DSCOVR'],pad=pd.to_timedelta('30m'),parm='Bz',subsamp=10,offset=10.,leg_loc='lower right'):
    """
    A function to create an example of how DTW works

    Parameters
    ----------
    self: class
        The class object created in the code after running .init_read() and .dtw() 
    c_time: pd.datetime object
        The central panda datetime object to plot around
    compare: list, optional
        List of two space craft to use to compare DTW solution (Default = ['DSCOVR'])
    pd: pd.timedelta object, optional
        Time around c_time to plot (Defatult = 30 minutes, pd.to_timedelta('30m'))
    parm: str, optional
        Parameter to plot on the y-axis (Default = 'Bz')
    subsamp: int, optional
        Subsampling parameter, so that plot does not show the full range of values (Default = 10).
    offset: float, optional
        Value to offset the unwarped time value solution (Default = 10.)
    leg_loc: string or int
        Location of the matplotlib legend (Default = 'lower right').
    
    """

    #Create figure
    fig, ax = plt.subplots(figsize=(2,2),dpi=600)
 
    #The reference or "trainer" space craft
    traft =  self.plsm[self.trainer]


    for i in compare:
        #What the spacecraft observed
        craft =  self.plsm[i]
        #Offsets applied to the spacecraft observations
        oraft =  self.plsm[i+'_offset']

 


        #good parameters
        good_parm = ((oraft[parm] > -9990.0) & (traft[parm] > -9999.0))

        #plot nicely
        #ax.scatter(craft[craft['SPEED'] > -9990.0].index,craft[craft['SPEED'] > -9990.0].SPEED,color=self.color[i],marker=self.marker[i])

        xvals = np.array([craft.iloc[oraft.match_ind[good_parm],:].index   ,traft.iloc[oraft.train_ind[good_parm],:].index])[:,::subsamp]
        yvals = np.array([craft.iloc[oraft.match_ind[good_parm],:][parm]+offset,traft.iloc[oraft.train_ind[good_parm],:][parm]])[:,::subsamp]


        ax.plot(xvals[0],yvals[0],linewidth=1,color=self.color[i],label=i)

        #only get keep finite values
        #good = np.isfinite(yvals)
        #allgood = ((good[0]) & (good[1]))
        #xvals=xvals[allgood]
        #yvals=yvals[allgood]

        ax.plot(xvals,yvals,'--',color=self.color[i],linewidth=.11)


   

    #plot the trainer space craft (i.e. the spacecraft which we are referencing for the DTW
    ax.plot(xvals[1],yvals[1],linewidth=1,color=self.color[self.trainer],label=self.trainer)

    ax.set_xlim([c_time-pad,c_time+pad])

    #rotate  x axis tick labels
    for tick in ax.get_xticklabels():
        tick.set_rotation(25)

    ax.legend(loc=leg_loc,frameon=False,fontsize=6)
    ax.set_xlabel('Time [UTC]')
    ax.set_ylabel(parm+' [nT]')
    ax.set_title('{0:%Y/%m/%d}'.format(c_time.to_pydatetime()),fontsize=8)

    # format the ticks
    mins = mdates.MinuteLocator(interval=10)  #every x minutes 
    minsFmt = mdates.DateFormatter('%H:%M')
    ax.xaxis.set_major_locator(mins)
    ax.xaxis.set_major_formatter(minsFmt)

    fancy_plot_small(ax)
    fig.savefig('../plots/example_dtw_{0:%Y%m%d_%H%M%S}.png'.format(c_time.to_pydatetime()),bbox_pad=0.1,bbox_inches='tight')
    fig.savefig('../plots/example_dtw_{0:%Y%m%d_%H%M%S}.eps'.format(c_time.to_pydatetime()),bbox_pad=0.1,bbox_inches='tight')


#add small tick marks to plots
def fancy_plot_small(ax):
    #Turn minor ticks on
    ax.minorticks_on()
    ax.yaxis.set_ticks_position('both')
    ax.xaxis.set_ticks_position('both')
    #set the width of the ticks
    ax.tick_params(which='both',width=1)
    #set the length of the major ticks
    ax.tick_params(which='major',length=3)
    #set length of the minor ticks
    ax.tick_params(which='minor',length=1.5,direction='in')
    ax.tick_params(direction='in')
    return ax

def omni_plot(self,hours=mdates.HourLocator()):
    """
    Function to plot 4-spacecraft plane solution at L1 compared to omni prediciton. This function
    was used to make the plots for AGU Fall 2018.

    Parameters
    -------------
    self: Class
        A dtw_plane class instance after the pred_earth function is already ran. 
    hours: matplotlib.dates.HourLocator object, optional
        The frequency which to label the time axis in the plots (Default =  mdates.HourLocator(), which is every hour).
    Returns
    ------------
    None

    """
    from matplotlib.ticker import MaxNLocator

    #Create omni figure
    fig_omni, ax_omni = plt.subplots(figsize=(2,2),dpi=600)

    #local plsm variable to skip self
    plsm = self.plsm

    #Read and store omni observations
    start = pd.to_datetime(self.start_t)+self.pad_earth
    end   = pd.to_datetime(self.end_t)+self.pad_earth
    omni = lcf.main(start,end,scrf=['omni'],pls=True,mag=False,orb=False)
    omni = omni['omni']['pls']
    omni['time_dt'] = pd.to_datetime(omni.Time)
    omni.set_index(omni.time_dt,inplace=True)
    self.plsm['omni'] = omni

    #plot omni parameters
    #slicer = ((omni.SPEED < 10000.) & (omni.time_dt > start) & (omni.time_dt < end))
    slicer = ((omni.SPEED < 10000.) & (omni.time_dt > start) & (omni.time_dt < end))
    ax_omni.plot(omni.loc[slicer,:].index,omni.loc[slicer,:].SPEED,linestyle='--',color='grey',label='OMNI')

    #loop over all earth space craft to plot
    for esp in self.earth_craft:
        #Plot predictions at themis
        pre_x = np.array(self.event_dict[esp+'_time'])
        pre_t = np.array(self.event_dict[esp+'_time'])
        pre_y = np.array(self.event_dict[esp+'_plsm'])
        pre_v = np.array(self.event_dict[esp+'_velo'])
        pre_n = np.array(self.event_dict[esp+'_nvec'])
        pre_d = np.array(self.event_dict[esp+'_dist'])


        #Average velocties
        smt_v = movingaverage (pre_v, 5)
        #difference between smooth ando measured
        err_v = (smt_v-pre_v)/smt_v

      
#        min_v, max_v = np.nanpercentile(pre_v,(65,98))
        #remove nans and bad velocities and distances (2018/08/01)
        #good, = np.where((np.isfinite(pre_x)) & (np.isfinite(pre_y)) & (pre_v < 2.E4)  & (pre_d < 3.E9 ) & (pre_v > 220.) & (pre_d > 1.E5))#)))
        #1.5E6 is the approximate distance to L1 only use attack angles near radially propogating
        #good, = np.where((np.isfinite(pre_x)) & (np.isfinite(pre_y)) & (np.abs(pre_d-1.5E6)/1.5e6 < 0.65) & (pre_v > min_v) & (pre_v < max_v))#)))
        #good = ((np.isfinite(pre_x)) & (np.isfinite(pre_y)) & (np.abs(pre_d-1.5E6)/1.5e6 < 1.50) & (pre_v > min_v) & (pre_v < max_v))#)))


        #No longer needed after making cut on normal vector
        ####good = ((np.isfinite(pre_x)) & (np.isfinite(pre_y)) )#& (np.abs(pre_d-1.5E6)/1.5e6 < 1.50) & (abs(err_v) < 0.05))#(pre_v > min_v) & (pre_v < max_v))#)))
        #range of velocities to consider 2018/09/07 J. Prchlik
        ###min_v, max_v = np.nanpercentile(pre_v[good],(2,98))
        ###min_v, max_v = np.nanpercentile(pre_d[good],(10,100))#-1.5e6
        ###
        ###if min_v < 0.:
        ###    min_v = 0.
        ###print(min_v,max_v,pre_d[good].max())

        ####iterate on what is a good velocity 2018/11/16 J. Prchlik 
        ####good = ((np.isfinite(pre_x)) & (np.isfinite(pre_y)) & (np.abs(pre_d-1.5E6)/1.5e6 > 0.50))# & (abs(err_v) < 0.05) & (pre_v > min_v) & (pre_v < max_v))#)))
        good = ((np.isfinite(pre_x)) & (np.isfinite(pre_y)))# & (pre_d > min_v) & (pre_d < max_v))# & (abs(err_v) < 0.05) & (pre_v > min_v) & (pre_v < max_v))#)))

        pre_x = np.array(pre_x)[good]
        pre_y = np.array(pre_y)[good]
        #replace bad values with nan
        #pre_x[good == False] = np.nan
        #pre_y[good == False] = np.nan


        


        #sort argument in time
        #remove out of order arrive fronts
        srt_x = np.argsort(pre_x)
        #srt_x, = np.where(np.diff(pre_x) > 0.)
        pre_x = pre_x[srt_x]
        pre_y = pre_y[srt_x]


        #insert start and end times
        #x-values
        pre_x = np.insert(pre_x,0,pre_x[0])
        pre_x = np.insert(pre_x,0,mdates.date2num(start))
        pre_x = np.insert(pre_x,-1,mdates.date2num(end))
        #y-values
        #get value before first shock
        #init_idx = self.plsm['Wind'].index.get_loc(self.top_vs.index[0])-1
        init_val = pre_y[0] #self.plsm['Wind'].ffill().iloc[init_idx].SPEED
        pre_y = np.insert(pre_y,0,init_val)
        pre_y = np.insert(pre_y,0,init_val)
        pre_y = np.insert(pre_y,-1,pre_y[-1])


        #create box like plot
        pre_x = np.array([pre_x,pre_x]).T.flatten()[1:]
        pre_y = np.array([pre_y,pre_y]).T.flatten()[:-1]

        #sort argument in time
        #remove out of order arrive fronts
        srt_x = np.argsort(pre_x)
        #srt_x, = np.where(np.diff(pre_x) > 0.)
        pre_x = pre_x[srt_x]
        pre_y = pre_y[srt_x]



        #No longer need with restriction in theta angle 2018/11/20 J. Prchlik
        ######create pandas df and get rolling median value to plot
        #####window = '90s'
        #pre_df = pd.DataFrame(np.array([pre_x,pre_y]).T,columns=['time','SPEED'])
        #pre_df.set_index(pd.to_datetime(pre_df.time),inplace=True)
        #resample at a 2minute cadence
        #pre_df = pre_df.drop_duplicates('time').reindex(plsm[esp].index.drop_duplicates(),method='nearest').interpolate('time')
        #pre_df.drop_duplicates('time',keep='first',inplace=True) 

        ######smooth array for prediction plotting
        #####pre_df['med_SPEED'] = pre_df.SPEED.rolling(window,min_periods=0,closed='both').median()
        ######pre_df['std_SPEED'] = pre_df.SPEED.rolling(window,min_periods=0,closed='both').std()
        #####pre_df['std_SPEED'] = (pre_df.SPEED-pre_df.med_SPEED).abs().rolling(window,min_periods=0,closed='both').median()
        #####pre_df['cnt_SPEED'] = pre_df.SPEED.rolling(window,min_periods=0,closed='both').count()

        ######get the core 1sigma uncert
        #####sig_min,sig_max = np.nanpercentile(pre_df.std_SPEED,[32,68])

        ######replace values less than the min with the 1sigma value
        #####pre_df.loc[pre_df.std_SPEED < sig_min,'std_SPEED'] = sig_min
        #####pre_df.loc[pre_df.std_SPEED > sig_max,'std_SPEED'] = sig_max


        ######compute # of sigma away from median
        #####pre_df['sig_SPEED'] = np.abs(pre_df.SPEED-pre_df.med_SPEED)/(pre_df.std_SPEED)

        ######replace bad SPEED values with last previous measurement
        #####repl_pred = pre_df.sig_SPEED > 3.
        #####pre_df.loc[repl_pred,'SPEED'] = np.nan
        #####pre_df.ffill(inplace=True)


        
        #Add plot with just the THEMIS plasma data
        slicer = np.isfinite(plsm[esp].SPEED)
        ax_omni.plot(plsm[esp].loc[slicer,:].index,pd.rolling_mean(plsm[esp].loc[slicer,:].SPEED,25,center=True),color=self.color[esp],label=esp.upper().replace('_',' '),zorder=100,linewidth=1)

        #ax_omni.plot(pre_df.time,pre_df.med_SPEED,color='teal',linestyle='-.',label='Plane Pred.')
        #Plot plane prediction
        ax_omni.plot(pre_x,pre_y,color='black',linestyle='-.',label='Plane Pred.')
        #ax_omni.plot(pre_df.time,pre_df.SPEED,color='black',linestyle='-.',label='Plane Pred.',zorder=500)


    #ax_omni.locator_params(axis='x', nbins=4)
    # format the ticks
    #hours =   # every hour
    hoursFmt = mdates.DateFormatter('%H')
    ax_omni.xaxis.set_major_locator(hours)
    ax_omni.xaxis.set_major_formatter(hoursFmt)

    #ax_omni.format_xdata = mdates.DateFormatter('%H:%M')
    #ax_omni.xaxis.set_major_locator(MaxNLocator(4))
    ax_omni.set_title(self.start_t[:10],fontsize=6)
    ax_omni.legend(loc='best',frameon=False,fontsize=4)
    #set axis labels
    ax_omni.set_xlabel("Time [UTC]",fontsize=8)
    ax_omni.set_ylabel("Flow Speed [km/s]",fontsize=8)
    #Add limit to be only THEMIS region
    ax_omni.set_xlim((plsm[esp].loc[slicer,:].index.min(),plsm[esp].loc[slicer,:].index.max()))
    fancy_plot_small(ax_omni)
    #rotate y,z y axis tick labels
    for tick in ax_omni.get_xticklabels():
        tick.set_rotation(-35)
    

    fig_omni.savefig('../plots/omni_pred_{0:%Y%m%d_%H%M%S}.png'.format(pd.to_datetime(self.start_t)),bbox_pad=.1,bbox_inches='tight',dpi=600)
    fig_omni.savefig('../plots/omni_pred_{0:%Y%m%d_%H%M%S}.eps'.format(pd.to_datetime(self.start_t)),bbox_pad=.1,bbox_inches='tight',dpi=600)

    #REMOVED TEST 2018/11/20 J. Prchlik
    #Also plot distances and vn values
    ####fig_test,ax_test = plt.subplots(nrows=3,sharex=True)

    ####ax_test[0].plot(pre_t,np.array(pre_d)*1.5e-6)
    ####ax_test[1].plot(pre_t,np.array(pre_v))
    ####ax_test[2].plot(pre_t,np.array(pre_n)[:,0])

    ####ax_test[0].set_ylabel('Distance')
    ####ax_test[1].set_ylabel('Velocity')
    ####
    ####ax_test[0].set_xlim(ax_omni.get_xlim())

    ####for iax in ax_test.ravel():
    ####    fancy_plot(iax)


def delay_plot(self):
    """
    Plot the time delay between spacecraft as a function of time for the spacecraft used in the analysis.

    Parameters
    -----------
    self: dtw class instance

    """



def movingaverage (values, window):
    """
    Calculate moving average
    
    Parameters
    ----------
    values: np.array
         Value to compute movie average over
    window: int
         Length of window to compute moving averages over

    Returns
    -----------
    sma: np.array
        Smoothed running average

    """
    weights = np.repeat(1.0, window)/window
    sma = np.convolve(values, weights, 'valid')
    #extapolate to start to keep sma the same size as values
    sma = np.insert(sma,0,(window-1)*[sma[0]])
    return sma



        
        
def plane_animation(self,andir = '../plots/boutique_ana/'):
        
    """
    Creates a series of plots that can be used for a movie showing successively propogation solar wind planes.

    Parameters
    -------------
    self: Class
        A dtw_plane class instance after the pred_earth function is already ran. 
    andir: string, optional
        String value to plotting directory for the animation. Directory must already exist (Default = '../plots/boutique_ana/').
    """
    #get animation function from matplotlib
    from matplotlib import animation

    #make sure andir ends with a '/'
    if andir[-1] != '/':
        andir += '/'

    #reset variables to local variables
    Re = self.Re # Earth radius in km
    start_t  = self.start_t 
    end_t    = self.end_t   
    center   = self.center  
    par      = self.par     
    justparm = self.justparm
    marker   = self.marker
    color    = self.color
    plsm     = self.plsm
    
    #set use to use all spacecraft
    craft = self.craft #['Wind','DSCOVR','ACE','SOHO']
    col   = self.col   #['blue','black','red','teal']
    mar   = self.mar   #['D','o','s','<']
    trainer = self.trainer
    #sim_date =  pd.date_range(start=start_t,end=end_t,freq='60S')


    #get data from THEMIS prediction
    esp = self.earth_craft[0]
    #switched to Wind index for looping and creating figures 2018/03/15
    sim_date = plsm[esp][start_t:end_t].index[::100]
    #time "event" is observed at Wind
    pre_t = mdates.num2date(np.array(self.event_dict[esp+'_time']),tz=None)[::100]
    #get a pandas formatted time
    fmt_t =  pd.to_datetime(pre_t)
    #pre_t = np.array(self.event_dict[esp+'_time'])
    #The velocity of the propograting vector 
    pre_v = np.array(self.event_dict[esp+'_velo'])[::100]
    #The normal of the propogating vector
    pre_n = np.array(self.event_dict[esp+'_nvec'])[::100]
    #pre_d = np.array(self.event_dict[esp+'_dist'])

    

    #SWITCH to Just creation of mp4 using animate in matplotlib
    #Create figure showing space craft orientation
    ofig, oax = plt.subplots(nrows=2,ncols=2,gridspec_kw={'height_ratios':[2,1],'width_ratios':[2,1]},figsize=(8,8))
    #set orientation labels
    oax[1,1].axis('off')
    
    #Create axes inside [1,1] (bottom left) will be used for the vector normal
    vec_ax_1 = inset_axes(oax[1,1], width="40%", height="40%", loc=3)
    vec_ax_2 = inset_axes(oax[1,1], width="40%", height="40%", loc=4)

 
    #create a title object to pass to the animation function
    title_time = oax[0,0].set_title('{0:%Y/%m/%d %H:%M:%S}'.format(sim_date[0]),fontsize=20)

    #These labels are statics, so no need to create objects for them
    #oax[0,0].set_xlabel('X(GSE) [R$_\oplus$]',fontsize=20)
    oax[0,0].set_ylabel('Z(GSE) [R$_\oplus$]',fontsize=20)
    oax[0,1].set_xlabel('Y(GSE) [R$_\oplus$]',fontsize=20)
    #oax[0,1].set_ylabel('Z(GSE) [R$_\oplus$]',fontsize=20)
    oax[1,0].set_xlabel('X(GSE) [R$_\oplus$]',fontsize=20)
    oax[1,0].set_ylabel('Y(GSE) [R$_\oplus$]',fontsize=20)

    #add fancy_plot to 2D plots
    for pax in oax.ravel():
        fancy_plot(pax)



    #set static limits from orbit maximum from SOHO file in Re
    #z limits
    z_lim = np.array([-1.,1])*240.
    oax[0,0].set_ylim(z_lim)
    oax[0,1].set_ylim(z_lim)
    #xlimits
    x_lim = np.array([-100.,450])#*300.0+200.
    oax[0,0].set_xlim(x_lim)
    oax[1,0].set_xlim(x_lim)
    #y limits
    y_lim = np.array([-1.,1])*120.0
    oax[0,1].set_xlim(y_lim)
    oax[1,0].set_ylim(y_lim)
    
    oax[0,0].legend(loc='upper right',frameon=False,scatterpoints=1)


    #Add Earth's Bow Shock 2018/12/04 J. Prchlik
    #y^2+Axy+Bx^2+Cy+Dx+E=0
    #Assume y=z
    #Parameters are from Fairfield et  al. 1971 Table 2 X Rotation No 4
    A =  0.2164
    B = -0.0986
    C = -4.26
    D =  44.916
    E = -623.77

    #Merdian 4 deg
    #More even so use this one 2018/12/05 J. Prchlik
    A =  0.0296
    B = -0.0381
    C = -1.280
    D =  45.664
    E = -652.10


    #Sample xvalue
    y_v = np.linspace(-100,100,100)


    #Define simplifying constants
    F = A*y_v+D
    G = y_v**2+C*y_v+E
    
    #Get positive root of solution
    x_v = (-F+np.sqrt(F**2-4*G*B))/(2.*B)
    
    #plot Bow shock
    oax[0,0].plot(x_v,y_v,linewidth=2,color='black',label=None)
    oax[1,0].plot(x_v,y_v,linewidth=2,color='black',label=None)
  
    #Now do it for y,z Bow shock is meaningless in this orientation (face on)
    #oax[0,1].plot(,,linewidth=2,color='black',label=None)


    #Set axis limits for vectors
    vec_ax_1.set_xlim([-1,1]) 
    vec_ax_2.set_xlim([1,-1]) 
    vec_ax_1.set_ylim([-1,1])
    vec_ax_2.set_ylim([-1,1])

    #Set axis limits for vectors
    fancy_plot(vec_ax_1)
    fancy_plot(vec_ax_2)


    #create labels
    small_font = 16
    vec_ax_1.set_xlabel('$n_\mathrm{X}$',fontsize=small_font)
    vec_ax_2.set_xlabel(r'($n_\mathrm{X}^2$+$n_\mathrm{Y}^2$)$^\frac{1}{2}$',fontsize=small_font)
    vec_ax_1.set_ylabel('$n_\mathrm{Y}$',fontsize=small_font)
    vec_ax_2.set_ylabel('$n_\mathrm{Z}$',fontsize=small_font)
    vec_ax_2.yaxis.set_label_position("right")       
    
    #rotate y,z y axis tick labels
    for tick in oax[0,1].get_xticklabels():
        tick.set_rotation(45)

    #set up vector plots
    vec_xy = vec_ax_1.arrow(0,0,1,1,color='black',head_width=.1,width=0.01,label=None,length_includes_head=True)
    vec_rz = vec_ax_2.arrow(0,0,1,1,color='black',head_width=.1,width=0.01,label=None,length_includes_head=True)

    #Dictionary for locations of the Spacecraft
    loc_dic = {}
    #get array of x,y,z spacecraft positions
    #spacraft positions
    for k in craft:
        #Get closest index value location
        ii = plsm[k].GSEx.dropna().index.get_loc(sim_date[0],method='nearest')
        #convert index location back to time index
        it = plsm[k].GSEx.dropna().index[ii]
    
        loc_dic[k+'_xz'] = oax[0,0].scatter(plsm[k].loc[it,'GSEx']/Re,plsm[k].loc[it,'GSEz']/Re,marker=marker[k],s=80,color=color[k],label=k)
        loc_dic[k+'_xy'] = oax[1,0].scatter(plsm[k].loc[it,'GSEx']/Re,plsm[k].loc[it,'GSEy']/Re,marker=marker[k],s=80,color=color[k],label=None)
        loc_dic[k+'_yz'] = oax[0,1].scatter(plsm[k].loc[it,'GSEy']/Re,plsm[k].loc[it,'GSEz']/Re,marker=marker[k],s=80,color=color[k],label=None)

    
    #dictionary for path objects created
    patch_dic = {}

    #Create function to initialize animation
    def init_an():
        """
        Initializes variables used in the animation of the solar wind.

        Returns
        -------
        """
        #removed positions of the space craft
        for k in craft:
            loc_dic[k+'_xz'].set_offsets([[],[]])
            loc_dic[k+'_xy'].set_offsets([[],[]])
            loc_dic[k+'_yz'].set_offsets([[],[]])

        #remove vectors from plot
        #vec_xy.set_xy([[],[]],[[],[]])
        #vec_rz.set_xy([[],[]],[[],[]])
        #print('HERE')
        title_time.set_text('') 


        return vec_xy,vec_rz,title_time

    #Function to run the animation (basically just runs the loop)
    def animate(k):
        """
        Animates the propogation of the solar wind using a simulated time l.

        Parameters
        ----------
        l : pd.datetime index object
            A pandas datatime index corresponding to a specific time in the refernce spacecraft's
            (usually Wind) observations.
        
        Output
        ------
        """
        l = sim_date[k]
        #list of colors to use for the planes
        cycol = cycle(['blue','green','red','cyan','magenta','black','teal','orange'])

        #set title of plot
        title_time.set_text('{0:%Y/%m/%d %H:%M:%S}'.format(l))


        #get the wind plane values for given x, y, or z
        counter = np.linspace(-1e10,1e10,5)
        windloc = np.zeros(counter.size)

        #+/- range for plane
        rng = np.linspace(-1.e10,1.e10,100)

        #remove all path objects created on the plot
        for z in patch_dic.keys():
            #remove patch from plot
            patch_dic[z].remove()
            #remove patch from dictionary
            patch_dic.pop(z,None)

        #Wind coordinates
        px = float(self.plsm[esp].loc[l,'GSEx'])
        py = float(self.plsm[esp].loc[l,'GSEy'])
        pz = float(self.plsm[esp].loc[l,'GSEz'])

        #Get time of l in local time then find difference between the
        #input time and the time the front is at Wind
        #The tz_localize is a hack because pandas inherents the local
        #time zone, which can give you incorrects results if not 
        #accounted for 2019/01/09 J. Prchlik
        fmt_l = l.tz_localize(fmt_t[0].tz)
        dt = (fmt_t-fmt_l).total_seconds()

        #Add radially propogating CME shock front    
        for j,i in enumerate(pre_t):
            #color to use
            cin = next(cycol)

            #get variable store in large array
            vm = pre_v[j]
            vn = pre_n[j].ravel()

            #give temp variables to some parameters
            vx,vy,vz = vn.ravel()*float(vm)

    
    
          
            #theta normal angle
            theta = float(np.arctan(vn[2]/np.sqrt(vn[0]**2+vn[1]**2)))*180./np.pi
    
            #leave loop if event is not within 2 hours (i.e., do not plot that event)
            if np.abs(dt[j]) > 2*3600.:
                continue
    
    
            #solve for the plane at time l
            #first get the points
            ps = np.matrix([[vx],[vy],[vz]])*dt[j]+np.matrix([[px],[py],[pz]])
    
            #get the magentiude of the position
            pm  = float(np.linalg.norm(ps))
            
    
            #Switched to solve_coeff function 2018/04/24 J. Prchlik
            a,b,c,d = solve_coeff(ps,vn)
    
            #get the plane values for given x, y, or z
            counter = np.linspace(-1e10,1e10,5)
            windloc = np.zeros(counter.size)
    
            #set off axis values to 0
            zvalsx = -(a*counter-d)/c
            zvalsy = -(b*counter-d)/c
            yvalsx = -(a*counter-d)/b
    
    
            #get shock Np value (use bfill to get values from the next good Np value) 
            np_df = plsm[trainer+'_offset'].Np.dropna()
            np_vl = np_df.index.get_loc(l,method='bfill')
            np_op = np_df.iloc[np_vl]
            

            #Use value limits from Weimer et al. (2002)
            maxx =  400.*Re
            maxy =  150.*Re
            maxz =  150.*Re
            minx = -50.*Re
            miny = -150.*Re
            minz = -150.*Re
    
            #make x and y grids
            xg = np.array([minx,maxx])
            yg = np.array([miny,maxy])
            zg = np.array([minz,maxz])
    
            # compute needed points for plane plotting
            xt, yt = np.meshgrid(xg, yg)
            xt, yt = xt.T, yt.T
            #simplify grid
            xt = np.array([minx,maxx,maxx,minx])
            yt = np.array([maxy,maxy,miny,miny])
            #switched to exact a,b,c from above 2018/03/15
            zvalsx = -(a*xt+b*yt-d)/c
            yvalsx = -(a*xt+c*yt-d)/b #works only because I set min(y), max(y) equal to min(z), max(z), respectively
            zvalsy = -(a*xt+b*yt-d)/c
    
            #Itentifier for this plane
            pi = str(j)
    
            #create polygons
            patch_dic[pi+'_xz'] = Polygon(np.array([xt.ravel()/Re,zvalsx.ravel()/Re]).T,True,alpha=0.4,color=cin)
            patch_dic[pi+'_xy'] = Polygon(np.array([xt.ravel()/Re,yvalsx.ravel()/Re]).T,True,alpha=0.4,color=cin)
            patch_dic[pi+'_yz'] = Polygon(np.array([yt.ravel()/Re,zvalsy.ravel()/Re]).T,True,alpha=0.4,color=cin)

            #Add normal vector
            #Plot normal vector with nearest arrive time at THEMIS
            if np.abs(dt[j]) == np.abs(dt).min():
                 #Remove previous arrows Just a hack so animation actually works 2019/01/09 J. Prchlik
                 vec_xy.set_visible(False)#remove()
                 vec_rz.set_visible(False)#remove()
                 #vec_xy.set_xy(0,0,vn[0],vn[1])
                 #vec_rz.set_xy(0,0,np.sqrt(vn[0]**2+vn[1]**2),vn[2])
                 patch_dic[pi+'a1'] = vec_ax_1.arrow(0,0,vn[0],vn[1],color=cin,head_width=.1,width=0.01,label=None,length_includes_head=True)
                 patch_dic[pi+'a2'] = vec_ax_2.arrow(0,0,np.sqrt(vn[0]**2+vn[1]**2),vn[2],color=cin,head_width=.1,width=0.01,label=None,length_includes_head=True)
                 #Hack to make animation work. Without this line it fails
                 #vec_xy.set_color(cin)
                 #vec_rz.set_color(cin)

            #Add patchs corresponding to solar wind planes
            oax[0,0].add_patch(patch_dic[pi+'_xz'])
            oax[1,0].add_patch(patch_dic[pi+'_xy'])
            oax[0,1].add_patch(patch_dic[pi+'_yz'])

    
    
        #get array of x,y,z spacecraft positions
        #spacraft positions
        for k in craft:
            #Get closest index value location
            ii = plsm[k].GSEx.dropna().index.get_loc(l,method='nearest')
            #convert index location back to time index
            it = plsm[k].GSEx.dropna().index[ii]
    
            #Update the plotting location of the spacecraft
            loc_dic[k+'_xy'].set_offsets([plsm[k].loc[it,'GSEx']/Re,plsm[k].loc[it,'GSEz']/Re])
            loc_dic[k+'_xz'].set_offsets([plsm[k].loc[it,'GSEx']/Re,plsm[k].loc[it,'GSEy']/Re])
            loc_dic[k+'_yz'].set_offsets([plsm[k].loc[it,'GSEy']/Re,plsm[k].loc[it,'GSEz']/Re])


        return vec_xy,vec_rz


    #Set up animation
    anim = animation.FuncAnimation(ofig, animate, init_func=init_an,
                                   frames=len(sim_date), interval=20, blit=True)
    #Name of movie for the plane animation
    movie_name = andir+'plane_ani_{0:%Y%m%d_%H%M%S}.mp4'.format(pd.to_datetime(self.start_t))
    
    #save the output animation
    anim.save(movie_name, fps=20, extra_args=['-vcodec', 'libx264'])


    
    
def print_ave_offsets(self):
    """
    A simple function that prints the interesting times of prediction, the coordinates of the Earth Craft at that time,
    and the 5th and 95th percentile of time offsets for SOHO, DSCOVR, and ACE

    Parameters
    -------------
    self: Class
        A dtw_plane class instance after running iterate DTW. 
    """


    wind = self.plsm['Wind'].index.min()
    dscvr= np.percentile(self.plsm['DSCOVR_offset'].offsets,(5,95))*1.e-9/60.
    ace  = np.percentile(self.plsm['ACE_offset'].offsets,(5,95))*1.e-9   /60.
    soho = np.percentile(self.plsm['SOHO_offset'].offsets,(5,95))*1.e-9  /60.
    print('####################################################')
    print('DSCVOR-Wind (5%,95%) = {0:2.1f},{1:2.1f}m'.format(*dscvr))
    print('ACE   -Wind (5%,95%) = {0:2.1f},{1:2.1f}m'.format(*ace))
    print('SOHO  -Wind (5%,95%) = {0:2.1f},{1:2.1f}m'.format(*soho))

    print('THEMIS Coordinates and Time')
    print(self.plsm[self.earth_craft[0]].index.max())
    print(self.plsm[self.earth_craft[0]][['GSEx','GSEy','GSEz']].mean()/self.Re)
    print('####################################################')


