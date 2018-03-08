import pandas as pd
from mpl_toolkits.mplot3d import Axes3D
from itertools import cycle
from spacepy import pycdf
import matplotlib.dates as mdates
import numpy as np
import matplotlib.pyplot as plt
from fancy_plot import fancy_plot
from datetime import datetime
from multiprocessing import Pool
from functools import partial
import os
import threading
import sys
import time
import mlpy #for dynamic time warping 

from scipy.stats.mstats import theilslopes
import scipy.optimize





#Function to read in spacecraft
def read_in(k,p_var='predict_shock_500',arch='../cdf/cdftotxt/',
            mag_fmt='{0}_mag_2015_2017_formatted.txt',pls_fmt='{0}_pls_2015_2017_formatted.txt',
            orb_fmt='{0}_orb_2015_2017_formatted.txt',
            start_t='2016/12/01',end_t='2017/09/24',center=False):
    """
    A function to read in text files for a given spacecraft

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
    start_t: string, optional
        Date in YYYY/MM/DD format to stop looking for events (inclusive, Default = '2017/07/31')

    Returns
    -------
    plsm: Pandas DataFrame
        A pandas dataframe with probability values and combined mag and plasma observations.
    
    """
    #Read in plasma and magnetic field data from full res
    pls = pd.read_table(arch+pls_fmt.format(k.lower()),delim_whitespace=True)

    #no magnetic field data from SOHO
    if k.lower() != 'soho':
        mag = pd.read_table(arch+mag_fmt.format(k.lower()),delim_whitespace=True)
        orb = pd.read_table(arch+orb_fmt.format(k.lower()),delim_whitespace=True)

        #create datetime objects from time
        pls['time_dt_pls'] = pd.to_datetime(pls['Time'])
        mag['time_dt_mag'] = pd.to_datetime(mag['Time'])
        orb['time_dt_orb'] = pd.to_datetime(orb['Time'])

        #setup index
        pls.set_index(pls.time_dt_pls,inplace=True)
        mag.set_index(mag.time_dt_mag,inplace=True)
        orb.set_index(orb.time_dt_orb,inplace=True)

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
        cols = ['SPEED','Np','Vth','Bx','By','Bz']
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
        pls.loc[:,['Bx','By','Bz']] = 0.0
        pls['time_dt_pls'] = pd.to_datetime(pls['Time'])
        pls['time_dt_mag'] = pd.to_datetime(pls['Time'])
        pls.set_index(pls.time_dt_pls,inplace=True)
        plsm = pls[start_t:end_t]
        plsm.loc[:,['Bx','By','Bz']] = -9999.0

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




#set use to use all spacecraft
craft = ['Wind','DSCOVR','ACE','SOHO']
col   = ['blue','black','red','teal']
mar   = ['D','o','s','<']
marker = {}
color  = {}
trainer = 'Wind'
center = True


#create dictionaries for labels
for j,i in enumerate(craft):
    marker[i] = mar[j]
    color[i]  = col[j]


#set the Start and end time
start_t = "2016/12/21 07:00:00"
end_t = "2016/12/21 13:00:00"

#get strings for times around each event when refining chi^2 time
ref_window = {}
#ref_window['DSCOVR'] = pd.to_timedelta('15 minutes')
#ref_window['ACE'] = pd.to_timedelta('15 minutes')
#ref_window['SOHO'] = pd.to_timedelta('25 minutes')
#ref_window['Wind'] = pd.to_timedelta('25 minutes')
ref_window['DSCOVR'] = pd.to_timedelta('5 minutes')
ref_window['ACE'] = pd.to_timedelta('5 minutes')
ref_window['SOHO'] = pd.to_timedelta('5 minutes')
ref_window['Wind'] = pd.to_timedelta('5 minutes')

#refined window to calculate Chi^2 min for each time
#(ref_chi_t)
#Parameters for file read in and parsing
par_read_in = partial(read_in,start_t=start_t,end_t=end_t,center=center)



#plot window 
plt_windw = pd.to_timedelta('180 minutes')

#window around event to get largers parameter jump values
# when writing to file
a_w = pd.to_timedelta('100 seconds')

#read in and format spacecraft in parallel
pool = Pool(processes=4)
outp = pool.map(par_read_in,craft)
pool.terminate()
pool.close()
pool.join()

plsm = {}
#create global plasma key
for i in outp:
    plsm[i.craft.values[0]] = i



#get all values at full resolution for dynamic time warping
t_mat  = plsm[trainer] #.loc[trainer_t-t_rgh_wid:trainer_t+t_rgh_wid]

#plot with the best timing solution
fig, fax = plt.subplots(ncols=2,nrows=3,sharex=True,figsize=(18,18))

#loop over all other craft
for k in craft[1:]:
    print('###########################################')
    print(k)
    p_mat  = plsm[k] #.loc[i_min-t_rgh_wid:i_min+t_rgh_wid]

    #use speed for rough esimation if possible
    if  (k.lower() == 'soho'): par = ['SPEED']
    else: par = ['Bx','By','Bz']

    #sometimes different componets give better chi^2 values therefore reject the worst when more than 1 parameter
    #Try using the parameter with the largest difference  in B values preceding and including the event (2017/12/11 J. Prchlik)
    if len(par) > 1:
       par_chi = np.array([(t_mat[par_i].max()-t_mat[par_i].min()).max() for par_i in par])
       use_par, = np.where(par_chi == np.max(par_chi))
       par      = list(np.array(par)[use_par])

    #get the median slope and offset
    #J. Prchlik (2017/11/20)
    #Dont use interpolated time for solving dynamic time warp (J. Prchlik 2017/12/15)
    #only try SPEED corrections for SOHO observations
    #Only apply speed correction after 1 iteration (J. Prchlik 2017/12/18)
    if ((k.lower() == 'o')):
        try:
            #create copy of p_mat
            c_mat = p_mat.copy()
            #resample the matching (nontrained spacecraft to the trained spacecraft's timegrid to correct offset (2017/12/15 J. Prchlik)
            c_mat = c_mat.reindex(t_mat.index,method='nearest').interpolate('time')
 
            #only comoare no NaN values
            good, = np.where(((np.isfinite(t_mat.SPEED.values)) & (np.isfinite(c_mat.SPEED.values))))
 
            #if few points for comparison only used baseline offset
            if ((good.size < 10.) & (par[0] == 'SPEED')):
                med_m,med_i = 1.0,0.0
                off_speed = p_mat.SPEED.median()-t_mat.SPEED.median()
                p_mat.SPEED = p_mat.SPEED-off_speed
                if med_m > 0: p_mat.SPEED = p_mat.SPEED*med_m+med_i
            else:
                off_speed = p_mat.SPEED.median()-t_mat.SPEED.median()
                p_mat.SPEED = p_mat.SPEED-off_speed
            #only apply slope if greater than 0
        except IndexError:
        #get median offset to apply to match spacecraft
            off_speed = p_mat.SPEED.median()-t_mat.SPEED.median()
            p_mat.SPEED = p_mat.SPEED-off_speed
 
 
 
    #get dynamic time warping value   
    print('WARPING TIME')
    print(par)
    dist, cost, path = mlpy.dtw_std(t_mat[par[0]].ffill().bfill().values,p_mat[par[0]].ffill().bfill().values,dist_only=False)
    print('STOP WARPING TIME')

    #get full offsets for dynamic time warping
    off_sol = (p_mat.iloc[path[1],:].index - t_mat.iloc[path[0],:].index)
    print('REINDEXED')

    #get a region around one of the best fit times
    b_mat = p_mat.copy()

    #update the time index of the match array for comparision with training spacecraft (i=training spacecraft time)
    b_mat = b_mat.reindex(b_mat.iloc[path[1],:].index).interpolate('time')
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


print('HERE')
fancy_plot(fax[0,0])
fancy_plot(fax[1,0])
fancy_plot(fax[2,0])
fancy_plot(fax[0,1])
fancy_plot(fax[1,1])
fancy_plot(fax[2,1])
print('HERE')
i = pd.to_datetime("2016/12/21 08:43:12") 
fax[0,0].set_xlim([i-pd.to_timedelta('100 minutes'),i+pd.to_timedelta('180 minutes')])

fax[0,0].set_ylabel('Np [cm$^{-3}$]',fontsize=20)
fax[1,0].set_ylabel('Th. Speed [km/s]',fontsize=20)
fax[2,0].set_ylabel('Flow Speed [km/s]',fontsize=20)
fax[2,0].set_xlabel('Time [UTC]',fontsize=20)

fax[0,1].set_ylabel('Bx [nT]',fontsize=20)
fax[1,1].set_ylabel('By [nT]',fontsize=20)
fax[2,1].set_ylabel('Bz [nT]',fontsize=20)
fax[2,1].set_xlabel('Time [UTC]',fontsize=20)

fax[1,0].set_ylim([0.,100.])

#Find points with the largest speed differences in wind
top_vs = t_mat.SPEED.dropna().diff().abs().nlargest(6)

#turn into data frame 
frm_vs = pd.DataFrame(top_vs)
#add columns
col_add = ['X','Y','Z','Vx','Vy','Vz']
for i in col_add: frm_vs[i] = -9999.9

#Use wind CDF to get velocity comps
cdf = pycdf.CDF('/Volumes/Pegasus/jprchlik/dscovr/solar_wind_events/cdf/wind/plsm/wi_h1_swe_20161221_v01.cdf')

wind_vx = cdf['Proton_VX_nonlin'][...]
wind_vy = cdf['Proton_VY_nonlin'][...]
wind_vz = cdf['Proton_VZ_nonlin'][...]
wind_t0 = cdf['Epoch'][...]

cdf.close()

#Fit Least Squared plane
def fitPlaneLTSQ(X,Y,Z):
    rows = X.size
    G = np.ones((rows, 3))
    G[:, 0] = X  
    G[:, 1] = Y  
    (a, b, c),resid,rank,s = np.linalg.lstsq(G, Z)
    normal = (a, b, -1)
    nn = np.linalg.norm(normal)
    normal = normal / nn
    return (c, normal)


#create pandas dataframe with wind components
wind_v = pd.DataFrame(np.array([wind_t0,wind_vx,wind_vy,wind_vz]).T,columns=['time_dt','Vx','Vy','Vz'])
wind_v.set_index(wind_v.time_dt,inplace=True)
#big list of velocities
big_lis = []

#Plot the top shock values
#fax[2,0].scatter(t_mat.loc[top_vs.index,:].index,t_mat.loc[top_vs.index,:].SPEED,color='purple',marker='X',s=150)
for j,i in enumerate(top_vs.index):
    yval = t_mat.loc[i,:].SPEED
    xval = mdates.date2num(i)
    fax[2,0].annotate('Shock {0:1d}'.format(j+1),xy=(xval,yval),xytext=(xval,yval+50.),
                      arrowprops=dict(facecolor='purple',shrink=0.005))
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
 
   

    #loop over all craft and populate time and position arrays
    for c in craft:
        #Get closest index value location
        ii = plsm[c].GSEx.dropna().index.get_loc(i,method='nearest')
        #convert index location back to time index
        it = plsm[c].GSEx.dropna().index[ii]

        #append craft values onto time and position arrays
        tvals.append(np.mean(plsm[c+'_offset'].loc[i,'offsets']).total_seconds())
        xvals.append(np.mean(plsm[c].loc[it,'GSEx']))
        yvals.append(np.mean(plsm[c].loc[it,'GSEy']))
        zvals.append(np.mean(plsm[c].loc[it,'GSEz']))

    #Covert arrays into numpy arrays and flip sign of offset
    tvals = np.array(tvals) 
    xvals = np.array(xvals) 
    yvals = np.array(yvals) 
    zvals = np.array(zvals) 

    #get the velocity components with respect to the shock front at wind
    #i_val = wind_v.index.get_loc(i,method='nearest')
    #vx = wind_v.iloc[i_val].Vx
    #vy = wind_v.iloc[i_val].Vy
    #vz = wind_v.iloc[i_val].Vz
    #use positions and vectors to get a solution for plane velocity
    pm = np.matrix([xvals[1:]-xvals[0],yvals[1:]-yvals[0],zvals[1:]-zvals[0]]).T #coordinate of craft 1 in top row
    tm = np.matrix(tvals[1:]).T # 1x3 matrix of time
    vna = np.linalg.solve(pm,tm) #solve for the velocity vectors normal
    vn = vna/np.linalg.norm(vna)
    vm = 1./np.linalg.norm(vna) #get velocity magnitude
    
    #store vx,vy,vz values
    vx,vy,vz = vm*np.array(vn).ravel()

    #get the 4 point location of the front when at wind
    #p_x(t0)1 = p_x(t1)-V_x*dt where dt = t1-t0  
    px = -vx*tvals+xvals
    py = -vy*tvals+yvals
    pz = -vz*tvals+zvals

    #parameters to add
    add_lis = [px,py,pz,vx,vy,vz,tvals]
    big_lis.append(add_lis)
    #put values in new dataframe
    #for l in range(len(col_add)):
    #    frm_vs.loc[i,col_add[l]] = add_lis[l] 

#turn big lis into numpy array
big_lis = np.array(big_lis)

fig.autofmt_xdate()
                
fig.savefig('../plots/bou_20161221_084312.png',bbox_pad=.1,bbox_inches='tight')


andir = '../plots/boutique_ana/'





sim_date =  pd.date_range(start=start_t,end=end_t,freq='600S')

for i in sim_date:
    #list of colors
    cycol = cycle('bgrcmk')

    #Create figure showing space craft orientation
    ofig, oax = plt.subplots(nrows=2,ncols=2,gridspec_kw={'height_ratios':[2,1],'width_ratios':[2,1]},figsize=(18,18))
    #tfig =  plt.figure()
    #tax = tfig.add_subplot(111, projection='3d')
    
    #set orientation lables
    oax[1,1].axis('off')
    oax[0,0].set_title('{0:%Y/%m/%d %H:%M:%S}'.format(i),fontsize=20)
    oax[0,0].set_xlabel('X(GSE) [km]',fontsize=20)
    oax[0,0].set_ylabel('Z(GSE) [km]',fontsize=20)
    oax[0,1].set_xlabel('Y(GSE) [km]',fontsize=20)
    oax[0,1].set_ylabel('Z(GSE) [km]',fontsize=20)
    oax[1,0].set_xlabel('X(GSE) [km]',fontsize=20)
    oax[1,0].set_ylabel('Y(GSE) [km]',fontsize=20)



    #add fancy_plot to 2D plots
    for pax in oax.ravel(): fancy_plot(pax)

    #set labels for 3D plot
    #tax.set_title('{0:%Y/%m/%d %H:%M:%S}'.format(i),fontsize=20)


    #Add radially propogating CME shock front    
    for p,l in enumerate(top_vs.index):
        #color to use
        cin = next(cycol)
        px = big_lis[p][0]
        py = big_lis[p][1]
        pz = big_lis[p][2]
        vx = big_lis[p][3]
        vy = big_lis[p][4]
        vz = big_lis[p][5]

        dt = (i-l.to_pydatetime()).total_seconds()

        #set up arrays of values
        xvals = vx*dt+px
        yvals = vy*dt+py
        zvals = vz*dt+pz

        #get sorted value array
        xsort = np.argsort(xvals)
        ysort = np.argsort(yvals)
        zsort = np.argsort(zvals)

        #get shock Np value (use bfill to get values from the next good Np value) 
        np_df = plsm[trainer+'_offset'].Np.dropna()
        np_vl = np_df.index.get_loc(l,method='bfill')
        np_op = np_df.iloc[np_vl]
        

        #oax[0,0].text((vx*dt+px)[0],(vz*dt+pz)[0],plsm[trainer+'_offset'].loc[i,'Np'].dropna().min(),color='black')
        #oax[1,0].text((vx*dt+px)[0],(vy*dt+py)[0],plsm[trainer+'_offset'].loc[i,'Np'].dropna().min(),color='black')
        #oax[0,1].text((vy*dt+py)[0],(vz*dt+pz)[0],plsm[trainer+'_offset'].loc[i,'Np'].dropna().min(),color='black')
        #plot 3d plot
        #fit plane
        #c, normal = fitPlaneLTSQ(xvals,yvals,zvals)
        #try different way to fit plane
        A = np.c_[xvals,yvals,np.ones(xvals.size)]
        #get cooefficience
        C,_,_,_ = scipy.linalg.lstsq(A,zvals)
        #create center point (use Wind)
        #point = np.array([xvals[0], yvals[0], zvals[0]])
        ##solve for d in a*x+b*y+c*z+d = 0
        #d = -point.dot(normal) #create normal surface
        #create mesh grid
        #Get max and min values
        maxx = np.max(xvals)
        maxy = np.max(xvals)
        minx = np.min(yvals)
        miny = np.min(yvals)

        #make x and y grids
        xg = np.array([minx,maxx])
        yg = np.array([miny,maxy])

        # compute needed points for plane plotting
        xt, yt = np.meshgrid(xg, yg)
        #zt = (-normal[0]*xt - normal[1]*yt - d)*1. / normal[2]
        #create z surface
        zt = C[0]*xt+C[1]*yt+C[2]

        #plot surface
        #tax.plot_surface(xt,yt,zt,color=cin,alpha=.5)

        #get sorted value array
        #xvals = xt.ravel()
        #yvals = yt.ravel()
        #zvals = zt.ravel()
        #zvals = xvals*C[0]+yvals*C[1]+C[2]
        xsort = np.argsort(xvals)
        ysort = np.argsort(yvals)
        zsort = np.argsort(zvals)

        #plot 2d plot
        oax[0,0].plot(xvals[zsort],zvals[zsort],color=cin,label='Shock {0:1d}, Np = {1:3.2f}, t_wind={2:%H:%S}'.format(p+1,np_op,l))
        oax[1,0].plot(xvals[ysort],yvals[ysort],color=cin,label=None)
        oax[0,1].plot(yvals[zsort],zvals[zsort],color=cin,label=None)
    #spacraft positions
    for k in craft:
        #Get closest index value location
        ii = plsm[k].GSEx.dropna().index.get_loc(i,method='nearest')
        #convert index location back to time index
        it = plsm[k].GSEx.dropna().index[ii]

        oax[0,0].scatter(plsm[k].loc[it,'GSEx'],plsm[k].loc[it,'GSEz'],marker=marker[k],s=80,color=color[k],label=k)
        oax[1,0].scatter(plsm[k].loc[it,'GSEx'],plsm[k].loc[it,'GSEy'],marker=marker[k],s=80,color=color[k],label=None)
        oax[0,1].scatter(plsm[k].loc[it,'GSEy'],plsm[k].loc[it,'GSEz'],marker=marker[k],s=80,color=color[k],label=None)
        #tax.scatter(plsm[k].loc[it,'GSEx'],plsm[k].loc[it,'GSEy'],plsm[k].loc[it,'GSEz'],
        #            marker=marker[k],s=80,color=color[k],label=None)


    #set static limits
    #z limits
    oax[0,0].set_ylim([-90000,160000])
    oax[0,1].set_ylim([-90000,160000])
    #tax.set_zlim([-90000,160000])
    #xlimits
    oax[0,0].set_xlim([1200000,1900000])
    oax[1,0].set_xlim([1200000,1900000])
    #tax.set_xlim([1200000,1900000])
    #y limits
    oax[0,1].set_xlim([-600000,300000])
    oax[1,0].set_ylim([-600000,300000])
    #tax.set_ylim([-600000,300000])
    
    oax[0,0].legend(loc='upper right',frameon=False,scatterpoints=1)

    #Save spacecraft orientation plots
    ofig.savefig(andir+'event_orientation_{0:%Y%m%d_%H%M%S}.png'.format(i.to_pydatetime()),bbox_pad=.1,bbox_inches='tight')
    ofig.clf()
    #save 3d spacecraft positions
    #tfig.savefig(andir+'d3/event_orientation_3d_{0:%Y%m%d_%H%M%S}.png'.format(i.to_pydatetime()),bbox_pad=.1,bbox_inches='tight')
    #tfig.clf()
    #plt.close()
    plt.close()



#pool1 = Pool(processes=6)
#pool1.map(make_plot,sim_date)
#poo11.close()
#pool1.join()