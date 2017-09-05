import matplotlib as mpl
mpl.use('TkAgg',warn=False,force=True)
mpl.rcParams['lines.linewidth'] = 3
mpl.rcParams['font.weight'] = 'bold'
mpl.rcParams['text.usetex'] = True
mpl.rcParams['font.sans-serif'] = 'Helvetica'
mpl.rcParams['font.size'] = 24

import pandas as pd 
import numpy as np
from fancy_plot import fancy_plot
from glob import glob
import matplotlib.pyplot as plt
from datetime import datetime,timedelta
import statsmodels.api as sm



#Use my training days
mytrain = True 
#Use full soho mission files
full_soho = False

#create bokeh
create_bokeh = False

#Training set shock times to give a value of 1 for logit fitting
if mytrain:
    #shock_times = pd.read_table('shock_times_restricted.txt')
    shock_times = pd.read_table('shock_times.txt')
    shock_times['start_time_dt'] = pd.to_datetime(shock_times.start_time)
else:
    #Use shock spotter shock times
    shock_times = pd.read_table('shock_spotter_events.txt',delim_whitespace=True)
    shock_times = shock_times[shock_times.P > .5]
    shock_times['start_time_dt'] = pd.to_datetime(shock_times.YY.astype('str')+'/'+shock_times.MM.astype('str')+'/'+shock_times.DD.astype('str')+'T'+shock_times.HHMM.astype('str'),format='%Y/%b/%dT%H%M')
    

#read in full mission long soho information
if full_soho:
    #final all soho files in 30second cadence directory
    f_full = glob('../soho/data/30sec_cad/formatted_txt/*txt')
    #read in all soho files in 30sec_cad directory
    df_full = (pd.read_table(f,engine='python',delim_whitespace=True) for f in f_full)
    #create one large array with all soho information
    full_df = pd.concat(df_full,ignore_index=True)
    #only keep with values in the Time frame
    full_df = full_df[full_df['DOY:HH:MM:SS'] >  0]
    
    
    
    
    
    #convert columns to datetime column
    full_df['time_dt'] = pd.to_datetime(full_df['YY'].astype('int').map("{:02}".format)+':'+full_df['DOY:HH:MM:SS'],format='%y:%j:%H:%M:%S',errors='coerce')
    #full_df['time_str'] = full_df['time_dt'].dt.strftime('%Y/%m/%dT%H:%M:%S')
    #set index to be time
    full_df.set_index(full_df['time_dt'],inplace=True)


#find all soho files in data directory
f_soho = glob('../soho/data/*txt')
#read in all soho files in data directory
df_file = (pd.read_table(f,skiprows=28,engine='python',delim_whitespace=True) for f in f_soho)

#create one large array with all soho information in range
soho_df = pd.concat(df_file,ignore_index=True)

#convert columns to datetime column
soho_df['time_dt'] = pd.to_datetime('20'+soho_df['YY'].astype('str')+':'+soho_df['DOY:HH:MM:SS'],format='%Y:%j:%H:%M:%S')
soho_df['time_str'] = soho_df['time_dt'].dt.strftime('%Y/%m/%dT%H:%M:%S')
#set index to be time
soho_df.set_index(soho_df['time_dt'],inplace=True)


#Create variable where identifies shock
soho_df['shock'] = 0

#locate shocks and update parameter to 1
for i in shock_times.start_time_dt:
    #less than 120s seconds away from shock claim as part of shock (output in nano seconds by default)
    shock, = np.where(np.abs(((soho_df.time_dt-i).values/1.e9).astype('float')) < 70.)
    soho_df['shock'][shock] = 1




#Do parameter calculation for the 2016 year (training year)
#calculate difference in parameters
soho_df['del_time'] = soho_df['time_dt'].diff(-1).values.astype('double')/1.e9
soho_df['del_speed'] = np.abs(soho_df['SPEED'].diff(-1)/soho_df.del_time/soho_df.SPEED)
soho_df['del_Np'] = np.abs(soho_df['Np'].diff(-1)/soho_df.del_time/soho_df.Np)
soho_df['del_Vth'] = np.abs(soho_df['Vth'].diff(-1)/soho_df.del_time/soho_df.Vth)

#calculate variance normalized parameters
#divide to get into usits of seconds
soho_df['std_speed'] = soho_df.SPEED.rolling('10m',min_periods=3.).std()/360.
soho_df['std_Np'] = soho_df.Np.rolling('10m',min_periods=3.).std()/360.
soho_df['std_Vth'] = soho_df.Vth.rolling('10m',min_periods=3.).std()/360.

#Significance of the variation in the wind parameters
soho_df['sig_speed'] = soho_df.del_speed/soho_df.std_speed
soho_df['sig_Np'] = soho_df.del_Np/soho_df.std_Np
soho_df['sig_Vth'] = soho_df.del_Vth/soho_df.std_Vth

#create an array of constants that hold a place for the intercept 
soho_df['intercept'] = 1 

#Do parameter calculation for all previous years 
#calculate difference in parameters
if full_soho:
    full_df['del_time'] = full_df['time_dt'].diff(-1).values.astype('double')/1.e9
    full_df['del_speed'] = np.abs(full_df['SPEED'].diff(-1)/full_df.del_time/full_df.SPEED)
    full_df['del_Np'] = np.abs(full_df['Np'].diff(-1)/full_df.del_time/full_df.Np)
    full_df['del_Vth'] = np.abs(full_df['Vth'].diff(-1)/full_df.del_time/full_df.Vth)
    #create an array of constants that hold a place for the intercept 
    full_df['intercept'] = 1 



#mask for training set
train = ((soho_df.time_dt >= datetime(2016,6,5,0)) & (soho_df.time_dt <= datetime(2016,12,31,0)) & (soho_df.del_time < 60.) & (soho_df.shock == 1))
no_sh = ((soho_df.time_dt >= datetime(2016,6,14,12)) & (soho_df.time_dt <= datetime(2016,6,16,0)) & (soho_df.del_time < 60.) & (soho_df.shock == 0))

#training set
soho_df_train = soho_df[((train) | (no_sh))]#plot range 


use_cols = ['sig_speed','sig_Np','sig_Vth','intercept']

#build rough preliminary shock model based on observations
logit_pre = sm.Logit(soho_df_train['shock'],soho_df_train[use_cols])
sh_rs_pre = logit_pre.fit()
#get predictions for training set
soho_df_train['shock2'] = sh_rs_pre.predict(soho_df_train[use_cols])

#do not replace shock training set 0 values
soho_df_train['shock2'][soho_df_train.shock == 0] = 0


#use the predictions from the training set to build a better model
logit = sm.Logit(soho_df_train['shock2'].round(),soho_df_train[use_cols])
sh_rs = logit.fit()


#crate monotonically increasing data frame
#(NEED TO UPDATE TO LINES OF CONSTANT PROBABILITY)
mono_df = pd.DataFrame()
mono_df['mono_speed'] = np.linspace(0,0.010,100)
mono_df['mono_np'] = np.linspace(0,0.2,100)
mono_df['mono_vt'] = np.linspace(0,0.04,100)
mono_df['int'] = 1
mono_df['p_shock'] = sh_rs.predict(mono_df[['mono_speed','mono_np','mono_vt','int']])

#get predictions for full set
soho_df['predict'] = sh_rs.predict(soho_df[use_cols])
#get predictions for training set
soho_df_train['predict'] = sh_rs.predict(soho_df_train[use_cols])
#get predictions for the Mission long CELIAS mission
if full_soho: 
    full_df['predict'] = sh_rs.predict(full_df[use_cols])
    best_df = full_df[full_df.predict >= 0.90]
    best_df.to_csv('../soho/archive_shocks.csv',sep=';')


#create figure object
fig,ax = plt.subplots(ncols=3,figsize=(7*3.,8))

#plot solar wind speed
ax[0].scatter(soho_df_train.del_speed,soho_df_train.shock,color='black')
ax[0].plot(mono_df.mono_speed,mono_df.p_shock,color='red')
ax[0].set_xlabel(r'$\triangle |\mathrm{V}|$ [km/s]')
fancy_plot(ax[0])

#plot solar wind density
ax[1].scatter(soho_df_train.del_Np,soho_df_train.shock,color='black')
ax[1].plot(mono_df.mono_speed,mono_df.p_shock,color='red')
ax[1].set_xlabel(r'$\triangle$n$_\mathrm{p}$/n$_\mathrm{p}$')
fancy_plot(ax[1])

#Thermal Speed
ax[2].scatter(soho_df_train.del_Vth,soho_df_train.shock,color='black')
ax[2].plot(mono_df.mono_speed,mono_df.p_shock,color='red')
ax[2].set_xlabel(r'$\triangle$w$_\mathrm{p}$/w$_\mathrm{p}$ ')
fancy_plot(ax[2])

#plt.show()



###########
#BOKEH PLOT
#For the training set
###########
from bokeh.models import HoverTool, ColumnDataSource
from bokeh.plotting import figure, show,save
from bokeh.layouts import column,gridplot


##########################################
#Create parameters for comparing data sets
##########################################
if create_bokeh:
    source = ColumnDataSource(data=soho_df_train)
    tools = "pan,wheel_zoom,box_select,reset,hover,save,box_zoom"
    
    tool_tips = [("Date","@time_str"),
                 ("Del. Np","@del_Np"),
                 ("Del. Speed","@del_speed"),
                 ("Del. Vth","@del_Vth"),
                 ("Predict","@predict"),
                 ]
    
    
    p1 = figure(title='SOHO CELIAS SHOCKS',tools=tools)
    #p1.plot_width = 1200
    p1.scatter('del_Np','shock',color='black',source=source)
    p1.select_one(HoverTool).tooltips = tool_tips
    p1.xaxis.axis_label = 'Delta Np/Np'
    p1.yaxis.axis_label = 'Shock'
                                       
    p2 = figure(title='SOHO CELIAS SHOCKS',tools=tools)
    #p2.plot_width = 1200
    p2.scatter('del_Vth','shock',color='black',source=source)
    p2.select_one(HoverTool).tooltips = tool_tips
    p2.xaxis.axis_label = 'Delta Vt/Vt'
    p2.yaxis.axis_label = 'Shock'
                                       
    p3 = figure(title='SOHO CELIAS SHOCKS',tools=tools)
    #p3.plot_width = 1200
    p3.scatter('del_speed','shock',color='black',source=source)
    p3.select_one(HoverTool).tooltips = tool_tips
    p3.xaxis.axis_label = 'Delta |V|/|V|'
    p3.yaxis.axis_label = 'Shock'
                                       
    p4 = figure(title='SOHO CELIAS SHOCKS',tools=tools)
    #p4.plot_width = 1200
    p4.scatter('time_dt','shock',color='black',source=source)
    p4.select_one(HoverTool).tooltips = tool_tips
    p4.xaxis.axis_label = 'UT Date'
    p4.yaxis.axis_label = 'Shock'
                                       
                                       
    save(gridplot([p1,p2],[p3,p4]),filename='bokeh_training_plot.html')
    
    ###########################
    # Plotting for the full set
    ###########################
    source1 = ColumnDataSource(data=soho_df)
    tools = "pan,wheel_zoom,box_select,reset,hover,save,box_zoom"
    
    tool_tips = [("Date","@time_str"),
                 ("Del. Np","@del_Np"),
                 ("Del. Speed","@del_speed"),
                 ("Del. Vth","@del_Vth"),
                 ("Predict","@predict"),
                 ]
    
    p5 = figure(title='SOHO CELIAS SHOCKS',tools=tools,x_axis_type="datetime")
    p5.plot_width = 1200
    p5.scatter('time_dt','predict',color='black',source=source1)
    p5.select_one(HoverTool).tooltips = tool_tips
    p5.xaxis.axis_label = 'UT Date'
    p5.yaxis.axis_label = 'Shock'
                                       
                                       
    save(p5,filename='bokeh_full_plot.html')
    
    
