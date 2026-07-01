# %%
import pandas as pd
import numpy as np
from pandas.core.frame import DataFrame

dataFile = 'data_v11a'

def getLine(file,arg):
    with open(file) as myFile:
        for num, line in enumerate(myFile, 1):
            if arg in line:
#                print('found at line:', num)
                return num

def logic(start, num, index):
    if index >= start:
        if index <= start+num:
#           print(index)
           return False
    return True

def getdf(header, lines = 33, dataCols = [3,4]):
    start = getLine(dataFile,header)    

    df = pd.read_csv(dataFile, 
        skiprows = lambda x: logic(start, lines, x),
        sep=r'\s*,\s*',
        header=None,
        engine='python'
        )
    for index, row in df.iterrows():
        #print(index,row)
        for col in dataCols:
            df.iloc[index, col-1] = float(df.iloc[index, col-1].split(' ')[-1])
    return df

# keys need to be unique (apparently)
cases = {
#    'A0_0_init_v8_ke': 'Boussinesq, Steady, Coarse, U-urf = 0.1',
#    'A0_A_v8_piso': 'Boussinesq, URANS, Coarse',
#    'A0_A_v8_piso_m': 'Boussinesq, URANS, Medium',
#    'A0_A_v8_piso_f': 'Boussinesq, URANS, Fine',
#
#    'A0_D_init_05_v8': 'Compressible, Steady, Coarse, U-urf = 0.5',
#    'A0_D_init_v8': 'Compressible, Steady, Coarse, U-urf = 0.1',
#    'A0_D_init_v8_m': 'Compressible, Steady, Medium, U-urf = 0.1',
#    'A0_D_init_v8_f': 'Compressible, Steady, Fine, U-urf = 0.1',
#    'A0_E_piso_v8': 'Compressible, URANS, Coarse',
#    'A0_E_piso_v8_m': 'Compressible, URANS, Medium',
#    'A0_E_piso_v8_f': 'Compressible, URANS, Fine',
#
#    'A0_0_init_v9_ke': 'Boussinesq, Steady, Coarse, U-urf = 0.5',
#    'A0_A_piso_v9_c': 'Boussinesq, URANS, XCoarse',
#    'A0_A_piso_v9_n': 'Boussinesq, URANS, Coarse',
#    'A0_A_piso_v9_m': 'Boussinesq, URANS, Medium',
#    'A0_A_piso_v9_f': 'Boussinesq, URANS, Fine',
#    'A0_A_piso_v9_uf': 'Boussinesq, URANS, XFine',
#
#    'A0_D_init_v9': 'Compressible, Steady, Coarse, U-urf = 0.5',
#    'A0_E_piso_v9_c': 'Compressible, URANS, XCoarse',
#    'A0_E_piso_v9_n': 'Compressible, URANS, Coarse',
#    'A0_E_piso_v9_m': 'Compressible, URANS, Medium',
#    'A0_E_piso_v9_f': 'Compressible, URANS, Fine',
#    'A0_E_piso_v9_uf': 'Compressible, URANS, XFine',
#
#    'A0_F_piso_v9_timescale': 'Compressible, URANS, Coarse, time',
#    'A0_F_piso_v9_timescale_hot': 'Compressible, URANS, Coarse, time, hot',
#
#    'A0_0_init_v10_ke' : 'Boussinesq, Steady, C, k-eps',
#    'A0_0_init_v10_rng' : 'Boussinesq, Steady, C, RNG',
#
#    'A0_A_pimple_v10_xc' : 'Boussinesq, URANS, PIMPLE, XC, k-eps',
#    'A0_A_pimple_v10_c' : 'Boussinesq, URANS, PIMPLE, C, k-eps',
#    'A0_A_pimple_v10_n' : 'Boussinesq, URANS, PIMPLE, N, k-eps',
#    'A0_A_pimple_v10_m' : 'Boussinesq, URANS, PIMPLE, M, k-eps',
#    'A0_A_pimple_v10_f' : 'Boussinesq, URANS, PIMPLE, F, k-eps',
#
#    'A0_A_piso_v10_xc' : 'Boussinesq, URANS, PISO, XC, k-eps',
#    'A0_A_piso_v10_c' : 'Boussinesq, URANS, PISO, C, k-eps',
#    'A0_A_piso_v10_n' : 'Boussinesq, URANS, PISO, N, k-eps',
#    'A0_A_piso_v10_m' : 'Boussinesq, URANS, PISO, M, k-eps',
#    'A0_A_piso_v10_f' : 'Boussinesq, URANS, PISO, F, k-eps',
#
#    'A0_A_pimple_v10_rng_uc' : 'Boussinesq, URANS, PIMPLE, UC, RNG',
#    'A0_A_pimple_v10_rng_xxc' : 'Boussinesq, URANS, PIMPLE, XXC, RNG',
#    'A0_A_pimple_v10_rng_xc' : 'Boussinesq, URANS, PIMPLE, XC, RNG',
#    'A0_A_pimple_v10_rng_c' : 'Boussinesq, URANS, PIMPLE, C, RNG',
#
#    # v11a #labels = ['c: 62k','n: 89k','m: 147k','f: 282k','f2: 652k','f3: 1.12M','f4: 2.17M']
#

#    'A0_0_init_v11a_ke' : 'Boussinesq, Steady, f4: 2.17M',
    'A0_0_init_v11a_ke' : 'Boussinesq, Steady, f4, U-rel: .5',
#    'A0_0_init_v11a_ke_relax' : 'Boussinesq, Steady, f4: 2.17M, relaxed',
    'A0_0_init_v11a_ke_relax' : 'Boussinesq, Steady, f4, U-rel: .1',
    'A0_0_init_v11a_ke_hot' : 'Boussinesq, Steady, f4, U-rel: .5, hot',
#
#    'A0_D_init_v11a_ke' : 'Compressible, Steady, f4: 2.17M',
    'A0_D_init_v11a_ke' : 'Compressible, Steady, f4, U-rel: .5',
#    'A0_D_init_v11a_ke_relax' : 'Compressible, Steady, f4: 2.17M, relaxed',
    'A0_D_init_v11a_ke_relax' : 'Compressible, Steady, f4, U-rel: .1',
    'A0_D_init_v11a_ke_hot' : 'Compressible, Steady, f4, U-rel: .5, hot',
#
#    'Boussinesq, URANS, PIMPLE, k-eps',
    'A0_A_pimple_v11a_c' : 'c: 62k',
    'A0_A_pimple_v11a_n' : 'n: 89k',
    'A0_A_pimple_v11a_m' : 'm: 147k',
    'A0_A_pimple_v11a_f' : 'f: 282k',
    'A0_A_pimple_v11a_uf' : 'f2: 652k',
    'A0_A_pimple_v11a_uf2' : 'f3: 1.12M',
    'A0_A_pimple_v11a_uuf' : 'f4: 2.17M',
#    'A0_A_pimple_v11a_uuf' : 'Boussinesq, Transient, f4',
    'A0_A_pimple_v11a_uuf_hot' : 'Boussinesq, Transient, f4, hot',

    'A0_E_pimple_v11a_uf' : 'Compressible, URANS, f2: 652k',
    'A0_E_pimple_v11a_uf2' : 'Compressible, URANS, f3: 1.12M',
#    'A0_E_pimple_v11a_uuf' : 'Compressible, URANS, f4: 2.17M',
    'A0_E_pimple_v11a_uuf' : 'Compressible, Transient, f4',
    'A0_E_pimple_v11a_uuf_hot' : 'Compressible, Transient, f4, hot',

#    'A0_A_pimple_v11a_uuf' : 'Boussinesq, URANS, f4',
#    'A0_E_pimple_v11a_uuf' : 'Compressible, URANS, f4',

    }

#list(cases.keys())

# %%

# k-eps
headers = [
#'A0_A_pimple_v11a_uuf',
#'A0_E_pimple_v11a_uuf',
#'A0_0_init_v11a_ke',
#'A0_D_init_v11a_ke',
#'A0_0_init_v11a_ke_relax',
#'A0_D_init_v11a_ke_relax',

#'A0_A_pimple_v11a_uuf_hot',
#'A0_E_pimple_v11a_uuf_hot',
#'A0_0_init_v11a_ke_hot',
#'A0_D_init_v11a_ke_hot',

#'A0_A_pimple_v11a_uf',
#'A0_E_pimple_v11a_uf',
#'A0_A_pimple_v11a_uf2',
#'A0_E_pimple_v11a_uf2',
#'A0_A_pimple_v11a_uuf',
#'A0_E_pimple_v11a_uuf',

'A0_A_pimple_v11a_c',
'A0_A_pimple_v11a_n',
'A0_A_pimple_v11a_m',
'A0_A_pimple_v11a_f',
'A0_A_pimple_v11a_uf',
'A0_A_pimple_v11a_uf2',
'A0_A_pimple_v11a_uuf',
]


# %%
print(headers[0])
dd = getdf(headers[0])
print(dd)
#display(dd)

# row keys, names for df
legends = {
0:'$T_{hot}$ CRAH 1',
1:'$T_{hot}$ CRAH 2',
2:'$T_{hot}$ CRAH 3',
3:'$T_{hot}$ CRAH 4',
4:'$T_{hot}$ rack 1',
5:'$T_{hot}$ rack 2',
6:'$T_{hot}$ rack 3',
7:'$T_{hot}$ rack 4',
8:'$T_{hot}$ rack 5',
9:'$T_{hot}$ rack 6',
10:'$T_{hot}$ rack 7',
11:'$T_{hot}$ rack 8',
12:'$T_{hot}$ rack 9',
13:'$T_{hot}$ rack 10',
14:'T cold rack 1',
15:'T cold rack 2',
16:'T cold rack 3',
17:'T cold rack 4',
18:'T cold rack 5',
19:'T cold rack 6',
20:'T cold rack 7',
21:'T cold rack 8',
22:'T cold rack 9',
23:'T cold rack 10',
24:'$p_{rgh}$ hot CRAH 1',
25:'$p_{rgh}$ hot CRAH 2',
26:'$p_{rgh}$ hot CRAH 3',
27:'$p_{rgh}$ hot CRAH 4',
28:'$p_{rgh}$ cold CRAH 1',
29:'$p_{rgh}$ cold CRAH 2',
30:'$p_{rgh}$ cold CRAH 3',
31:'$p_{rgh}$ cold CRAH 4',
32:'sum(phi) hole',
}

# %%
# prepare df
df = pd.DataFrame(headers)
df.rename({0: 'Case'}, axis=1, inplace=True)

df['descr'] = [cases[head] for head in headers]
#print(df)

# initiate empty columns
for _, key in enumerate(legends):
    df[legends[key]] = ""

# column of interest for out data
datacol = 2
def adjust(val):
    if datacol == 2: # adjust pressure
            if val > 100000:
                return val - 101325
            else: 
                return val
    if datacol == 3: # confidence interval
            return 3.92*val

for index, header in enumerate(headers):
    for _, key in enumerate(legends):
        dd = getdf(header)
        df[legends[key]][index] = adjust(dd[datacol][key])
        
display(df)

# % add delta pressures to table

legends_delta = {
33:'$\Delta p_{rgh}$ CRAH 1',
34:'$\Delta p_{rgh}$ CRAH 2',
35:'$\Delta p_{rgh}$ CRAH 3',
36:'$\Delta p_{rgh}$ CRAH 4',
}

# initiate empty columns
for _, key in enumerate(legends_delta):
    df[legends_delta[key]] = ""

for index, header in enumerate(headers):
    for _, key in enumerate(legends_delta):
        dd = getdf(header)
#        print(key,legends_delta[key])
        df[legends_delta[key]][index] = df[legends[key-5]][index]-df[legends[key-9]][index]

display(df)


# %%

# https://plotly.com/python/parallel-coordinates-plot/
#https://stackoverflow.com/questions/8230638/parallel-coordinates-plot-in-matplotlib

import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import numpy as np

from matplotlib import rc
rc('font', **{'family': 'serif', 'serif': ['Computer Modern']})
rc('text', usetex=True)
rc('font', size=12)

from matplotlib.ticker import StrMethodFormatter

cols = [0]+list(np.arange(0,4)+2) # T_crah's
#cols = [0]+list(np.arange(33,37)+2) # delta pressure CRAH's

#cols = [0]+list(np.arange(24,32)+2) # pressure CRAH's

#cols = [0]+list(np.arange(4,14)+2) # T_hot racks
#cols = [0]+list(np.arange(14,24)+2) # T_cold racks

N = df.shape[0]
fig, host = plt.subplots()
fig.set_size_inches(4+len(cols), N/2.8)

ynames = list(df.columns[cols].values)
hostNames = list(df['descr'].values)

print(hostNames,'\n',ynames)
# organize the data
ys = np.hstack((np.linspace(1,df.shape[0],df.shape[0])[:,None], df.iloc[:,cols[1:]].values))


def new_func(colorDistr):
    category = []
    for color,num in enumerate(colorDistr):
        category.extend([int(color+1) for i in range(num)])
    return category

category = new_func([7,4,2,2,2]) # by number in groups
#ls_spec = ['-','-','--','--',':',':']
ls_spec = [':',':',':',':','-','-','-',]
#category = [1,2,1,2,1,2,1,2,2] # manual
#category = [1,1,2,2,3,3,2,2,2] # manual
#category = list(range(N)) # individual categories

# %
ymins = ys.min(axis=0)
ymaxs = ys.max(axis=0)
dys = ymaxs - ymins
ymins -= dys * 0.05  # add 5% padding below and above
ymaxs += dys * 0.05
dys = ymaxs - ymins

# transform all data to be compatible with the main axis
zs = np.zeros_like(ys)
zs[:, 0] = ys[:, 0]
zs[:, 1:] = (ys[:, 1:] - ymins[1:]) / dys[1:] * dys[0] + ymins[0]

axes = [host] + [host.twinx() for i in range(ys.shape[1] - 1)]
for i, ax in enumerate(axes):
    ax.set_ylim(ymins[i], ymaxs[i])
    ax.spines['top'].set_visible(False)
    ax.spines['bottom'].set_visible(False)        
    if ax != host:
        ax.spines['left'].set_visible(False)
        ax.yaxis.set_ticks_position('right')
        ax.spines["right"].set_position(("axes", i / (ys.shape[1] - 1)))
        ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.2f}')) # 2 decimal places

host.set_yticks(ys[:,0]) # to ensure ticks are shown
host.set_yticklabels(hostNames) # replace tick with text

host.set_xlim(0, ys.shape[1] - 1)
host.set_xticks(range(ys.shape[1]))

host.set_xticklabels(ynames,fontsize=13) # , fontsize=14
host.tick_params(axis='x', which='major', pad=7)
host.spines['right'].set_visible(False) # ?
host.xaxis.tick_top()
#host.set_title('Parallel Coordinates Plot', fontsize=18)

#colors = plt.cm.Set1.colors
#colors = plt.cm.Dark2.colors
colors = plt.cm.tab10.colors
if N > 10:
    colors = plt.cm.tab20.colors

for j in range(N):
    # to just draw straight lines between the axes:
#    host.plot(range(ys.shape[1]), zs[j,:], c=colors[(category[j] - 1) % len(colors) ])

    # create bezier curves
    # for each axis, there will a control vertex at the point itself, one at 1/3rd towards the previous and one
    #   at one third towards the next axis; the first and last axis have one less control vertex
    # x-coordinate of the control vertices: at each integer (for the axes) and two inbetween
    # y-coordinate: repeat every point three times, except the first and last only twice
    verts = list(zip(
        [x for x in np.linspace(0, ys.shape[1] - 1, ys.shape[1] * 3 - 2, endpoint=True)],
        np.repeat(zs[j, :], 3)[1:-1]
                     ))
#    for x,y in verts: 
#        host.plot(x, y, 'go') # to show the control points of the beziers
    codes = [Path.MOVETO] + [Path.CURVE4 for _ in range(len(verts) - 1)]
    path = Path(verts, codes)
    patch = patches.PathPatch(path, 
                                facecolor='none', 
                                lw=1.5, 
                                ls=ls_spec[j],
                                edgecolor=colors[category[j] - 1])
    host.add_patch(patch)

plt.tight_layout()
plt.show()

fig.savefig("fig04.pdf", bbox_inches = 'tight')
