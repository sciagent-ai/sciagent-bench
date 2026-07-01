# %%
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os

#plt.rc('font', family='serif')
##plt.rc('font', serif='Old Standard TT')
#plt.rcParams['font.serif'] = ['Times New Roman'] + plt.rcParams['font.serif']
#plt.rc('font', size=12)
#plt.rc('font', weight='light')
#plt.rc('text', usetex='false')

from matplotlib import rc
import matplotlib.pylab as plt
from matplotlib.ticker import StrMethodFormatter


#rc('font', **{'family': 'serif', 'serif': ['Computer Modern']})
#rc('text', usetex=False)
rc('font', size=12)


#matplotlib.use('Qt5Agg') # Make sure that we are using QT5
#%matplotlib inline
#plt.close('all')

file = 0 # for file loading
skip = .100 # time
sample = 100
save = True
rho = 1.205

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)
cwd = os.getcwd()
print("Current working dir : {}".format(cwd) )

pp = False

def new_func(cwd, pos, var,startTime = 0):
    data = pd.DataFrame()
    for id in pos:
        df = pd.read_csv(
    cwd + '/postProcessing/' + id + '/' + str(startTime) + '/surfaceFieldValue.dat',
    delim_whitespace=True,
    header=4,
    error_bad_lines=False)
        if pp:
            print(df.columns.tolist())

        df = df.shift(periods=1, axis="columns")
        df = df.drop(columns=['#'])   
        #print(df)     
        #df = df[~df.Time.str.contains("#")]
        df = df.apply(pd.to_numeric)

        # convert all columns of DataFrame
        data[id] = df[var]
        data['Time-'+id] = df['Time']
    return data

def getnearpos(array,value):
    idx = (np.abs(array-value)).argmin()
    return idx   
# %

labels = {
        'T_hot_crac1':'hot_crac1',
        'T_hot_crac2':'hot_crac2',
        'T_hot_crac3':'hot_crac3',
        'T_hot_crac4':'hot_crac4',
        'T_h_rack1':'hot_rack1',
        'T_h_rack2':'hot_rack2',
        'T_h_rack3':'hot_rack3',
        'T_h_rack4':'hot_rack4',
        'T_h_rack5':'hot_rack5',
        'T_h_rack6':'hot_rack6',
        'T_h_rack7':'hot_rack7',
        'T_h_rack8':'hot_rack8',
        'T_h_rack9':'hot_rack9',
        'T_h_rack10':'hot_rack10',
        'T_c_rack1':'cold_rack1',
        'T_c_rack2':'cold_rack2',
        'T_c_rack3':'cold_rack3',
        'T_c_rack4':'cold_rack4',
        'T_c_rack5':'cold_rack5',
        'T_c_rack6':'cold_rack6',
        'T_c_rack7':'cold_rack7',
        'T_c_rack8':'cold_rack8',
        'T_c_rack9':'cold_rack9',
        'T_c_rack10':'cold_rack10',
        }

# %%

pos = ['T_hot_crac1',
        'T_hot_crac2',
        'T_hot_crac3',
        'T_hot_crac4',
        'T_h_rack1',
        'T_h_rack2',
        'T_h_rack3',
        'T_h_rack4',
        'T_h_rack5',
        'T_h_rack6',
        'T_h_rack7',
        'T_h_rack8',
        'T_h_rack9',
        'T_h_rack10',
        'T_c_rack1',
        'T_c_rack2',
        'T_c_rack3',
        'T_c_rack4',
        'T_c_rack5',
        'T_c_rack6',
        'T_c_rack7',
        'T_c_rack8',
        'T_c_rack9',
        'T_c_rack10',]

var = 'areaAverage(T)'

data = new_func(cwd, pos, var, file)

# data.describe()

fig = plt.figure(figsize=(12,5))
#fig, ax = plt.subplots(1,1)
#fig.set_size_inches(18.5, 10.5, forward=True)
#plt.rcParams["figure.figsize"] = (20,3)

for id in pos:
    filtered = data.loc[(data['Time-'+id] > (file + skip))]
    xx = filtered['Time-'+id].values
    yy = filtered[id].values
    plt.plot(xx,yy, label = labels[id], linewidth=1)

    idx = getnearpos(xx,xx[-1] - sample)
    print('{}, {}, Mean of last {} is: {:.12e}, std: {:.12e}'.format(
        id, var, xx[-1]-xx[idx], np.mean(yy[idx:-1]),np.std(yy[idx:-1])
        )) 

plt.grid(True, linewidth=0.5, linestyle='-')
plt.xlabel('Time')
plt.ylabel(var+' [K]')
plt.legend(bbox_to_anchor=(1, 1), loc='upper left', ncol=1)
plt.gca().yaxis.set_major_formatter(StrMethodFormatter('{x:.4f}')) # No decimal places

if save:
    plt.savefig("logs/"+ str(file) + '_' + var +".pdf", bbox_inches = 'tight')


# %%
pos = [
#        'T_h_rack1',
#        'T_h_rack2',
#        'T_h_rack3',
#        'T_h_rack4',
#        'T_h_rack5',
#        'T_h_rack6',
#        'T_h_rack7',
#        'T_h_rack8',
#        'T_h_rack9',
#        'T_h_rack10',
#        'T_c_rack1',
#        'T_c_rack2',
#        'T_c_rack3',
#        'T_c_rack4',
#        'T_c_rack5',
#        'T_c_rack6',
#        'T_c_rack7',
#        'T_c_rack8',
#        'T_c_rack9',
#        'T_c_rack10',
        'T_hot_crac1',
        'T_hot_crac2',
        'T_hot_crac3',
        'T_hot_crac4',
        'T_cold_crac1',
        'T_cold_crac2',
        'T_cold_crac3',
        'T_cold_crac4']

var = 'areaAverage(p_rgh)'

data = new_func(cwd, pos, var, file)

fig = plt.figure(figsize=(12,6))



for id in pos:
    filtered = data.loc[(data['Time-'+id] > (file + skip))]
    xx = filtered['Time-'+id].values
    yy = (filtered[id].values)*rho
    plt.plot(xx,yy, label = id, linewidth=1)

    idx = getnearpos(xx,xx[-1] - sample)
    print('{}, {}, Mean of last {} is: {:.12e}, std: {:.12e}'.format(
        id, var, xx[-1]-xx[idx], np.mean(yy[idx:-1]),np.std(yy[idx:-1])
        )) 

plt.xlabel('Time')
plt.ylabel(var)
plt.grid(True, linewidth=0.5, linestyle='-')

plt.gca().yaxis.set_major_formatter(StrMethodFormatter('{x:.4f}')) # No decimal places

plt.legend(bbox_to_anchor=(1, 1), loc='upper left', ncol=1)

if save:
    plt.savefig("logs/"+ str(file) + '_' + var +".pdf", bbox_inches = 'tight')



# %%

pos = ['dm_hole']

var = 'sum(phi)'

savefile = 'dm_hole'

data = new_func(cwd, pos, var, file)

plt.figure(figsize=(12,6))

for id in pos:
    filtered = data.loc[(data['Time-'+id] > (file + skip))]
    xx = filtered['Time-'+id].values
    yy = np.abs(filtered[id].values)*rho
    plt.plot(xx,yy, label = id, linewidth=1)
    plt.xlabel('Time')
    plt.ylabel(var)
    plt.grid(True, linewidth=0.5, linestyle='-')
    idx = getnearpos(xx,xx[-1] - sample)
    print('{}, {}, Mean of last {} is: {:.12e}, std: {:.12e}'.format(
        id, var, xx[-1]-xx[idx], np.mean(yy[idx:-1]),np.std(yy[idx:-1])
        )) 

plt.legend(bbox_to_anchor=(1, 1), loc='upper left', ncol=1)
plt.gca().yaxis.set_major_formatter(StrMethodFormatter('{x:.3e}')) # No decimal places

if save:
    plt.savefig("logs/"+ str(file) + '_' + savefile +".pdf", bbox_inches = 'tight')



# %%
pos = ['dm_h_crac1',
        'dm_h_crac2',
        'dm_h_crac3',
        'dm_h_crac4',
        'dm_c_crac1',
        'dm_c_crac2',
        'dm_c_crac3',
        'dm_c_crac4'
        ]

var = 'sum(phi)'

data = new_func(cwd, pos, var, file)

plt.figure(figsize=(12,6))

for id in pos:
    filtered = data.loc[(data['Time-'+id] > (file + skip))]
    xx = filtered['Time-'+id].values
    yy = np.abs(filtered[id].values)*rho
    plt.plot(xx,yy, label = id, linewidth=1)
    plt.xlabel('Time')
    plt.ylabel(var)
    plt.grid(True, linewidth=0.5, linestyle='-')
    idx = getnearpos(xx,xx[-1] - sample)
#    print('{}, {}, Mean of last {} is: {:.12e}, std: {:.12e}'.format(
#        id, var, xx[-1]-xx[idx], np.mean(yy[idx:-1]),np.std(yy[idx:-1])
#        ))

plt.legend(bbox_to_anchor=(1, 1), loc='upper left', ncol=1)
plt.gca().yaxis.set_major_formatter(StrMethodFormatter('{x:.4f}')) # No decimal places

if save:
    plt.savefig("logs/"+ str(file) + '_' + var +".pdf", bbox_inches = 'tight')



# %%

pos =   [ 
        'dm_h_rack1',
        'dm_h_rack2',
        'dm_h_rack3',
        'dm_h_rack4',
        'dm_h_rack5',
        'dm_h_rack6',
        'dm_h_rack7',
        'dm_h_rack8',
        'dm_h_rack9',
        'dm_h_rack10',
        'dm_c_rack1',
        'dm_c_rack2',
        'dm_c_rack3',
        'dm_c_rack4',
        'dm_c_rack5',
        'dm_c_rack6',
        'dm_c_rack7',
        'dm_c_rack8',
        'dm_c_rack9',
        'dm_c_rack10',
        ]

var = 'sum(phi)'

data = new_func(cwd, pos, var, file)

plt.figure(figsize=(12,6))

for id in pos:
    filtered = data.loc[(data['Time-'+id] > (file + skip))]
    xx = filtered['Time-'+id].values
    yy = np.abs(filtered[id].values)*rho
    plt.plot(xx,yy, label = id, linewidth=1)
    plt.xlabel('Time')
    plt.ylabel(var)
    plt.grid(True, linewidth=0.5, linestyle='-')
    idx = getnearpos(xx,xx[-1] - sample)
#    print('{}, {}, Mean of last {} is: {:.12e}, std: {:.12e}'.format(
#        id, var, xx[-1]-xx[idx], np.mean(yy[idx:-1]),np.std(yy[idx:-1])
#        )) 

plt.legend(bbox_to_anchor=(1, 1), loc='upper left', ncol=1)
plt.gca().yaxis.set_major_formatter(StrMethodFormatter('{x:.4f}')) # No decimal places

if save:
    plt.savefig("logs/"+ str(file) + '_' + var +".pdf", bbox_inches = 'tight')


# %%



# %% 




