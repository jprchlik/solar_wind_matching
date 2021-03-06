import matplotlib as mpl
mpl.use('TkAgg',warn=False,force=True)
mpl.rcParams['lines.linewidth'] = 3
mpl.rcParams['font.weight'] = 'bold'
mpl.rcParams['text.usetex'] = True
mpl.rcParams['font.sans-serif'] = 'Helvetica'
mpl.rcParams['font.size'] = 24

import pandas as pd
import matplotlib.pyplot as plt
from fancy_plot import fancy_plot
from datetime import datetime
from scipy.stats import pearsonr
#read sunspot file
sunsp_df = pd.read_csv('../sun_spot_number/SN_m_tot_V2.0.txt',delim_whitespace=True)
sunsp_df['time_dt'] = pd.to_datetime(sunsp_df.YYYY.astype('str')+sunsp_df.MM.astype('str'),format='%Y%m')
sunsp_df.set_index(sunsp_df['time_dt'],inplace=True)
sunsp_df = sunsp_df[(sunsp_df.index >= datetime(1996,1,1,0)) & (sunsp_df.index < datetime(2016,1,1,0))]
#sunsp_df = sunsp_df[(sunsp_df.index >= datetime(2000,1,1,0)) & (sunsp_df.index < datetime(2016,1,1,0))]


#read lasco cme cactus file
cmect_df = pd.read_csv('../soho/cactus/cme_lz.txt',sep='|',skiprows=23)
#remove whitespace from column headers
cmect_df.rename(columns=lambda x: x.strip(),inplace=True)
cmect_df['time_dt'] = pd.to_datetime(cmect_df.t0)
cmect_df.set_index(cmect_df['time_dt'],inplace=True)
#number of cme events
cmect_df['counts'] = 1
#get number of halo cme events
cmect_df['h_cnts'] = 0
cmect_df['h_cnts'][cmect_df['halo?'].str.strip() != ''] = 1



#read in shock file
shock_df = pd.read_csv('../soho/archive_shocks.csv',sep=';')
shock_df['time_dt'] = pd.to_datetime(shock_df['time_dt'])
shock_df.set_index(shock_df['time_dt'],inplace=True)

#number of events
shock_df['counts'] = 1

#Resample at one month using the mean
df_bin = shock_df.resample('A').sum()
df_spb = sunsp_df.resample('A').sum()
df_cme = cmect_df.resample('A').sum()



fig, ax = plt.subplots(figsize=(24,8),ncols=2)

ax[0].scatter(df_bin.index[1:],df_bin.counts[1:],color='black')
ax[0].scatter(df_cme.index,df_cme.counts,color='red',marker='D')
ax[0].scatter(df_cme.index,df_cme.h_cnts,color='blue',marker='s')
ax[0].plot(df_spb.index[1:],df_spb.SN[1:]*2.,color='black')
ax[0].set_ylabel('Number of Shock Events')
ax[0].set_xlabel('Year')
fancy_plot(ax[0])
ax[0].set_xlim([datetime(1995,1,1),datetime(2017,1,1)])

ax[1].scatter(df_bin.counts[1:],df_spb.SN[1:],color='black')
ax[1].scatter(df_bin.counts[1:],df_cme.counts,color='red',marker='D')
ax[1].scatter(df_bin.counts[1:],df_cme.h_cnts,color='blue',marker='s')
ax[1].set_xlabel('Number of Shock Events')
ax[1].set_ylabel('Number of Sun Spots')

r,p = pearsonr(df_bin.counts[1:],df_cme.h_cnts)
print r,p
ax[1].text(3000.,2000.,'r={0:4.3f}'.format(r))
fancy_plot(ax[1])

plt.show()
