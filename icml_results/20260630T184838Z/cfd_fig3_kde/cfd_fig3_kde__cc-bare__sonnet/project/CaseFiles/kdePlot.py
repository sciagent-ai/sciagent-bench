# %% ------ Preload / Checklist ------

# ascii in controlDict
# foamFormatConvert -noConstant
# 
# 
# reconstructPar -case . -latestTime | tee logs/log4_rP_latest
# postProcess -latestTime -func writeCellVolumes
# postProcess -latestTime -func writeCellCentres
# checkMesh -writeFields '(wallDistance)' -latestTime 
# postProcess -latestTime -func enstrophy
# 
# 
# postProcess -time 360 -func vorticity
# postProcess -time 360 -func enstrophy
# postProcess -func turbulenceFields
# postProcess -func "ObukhovLength(<UField>)"
# 

%matplotlib qt

xxh = []
yyh = []
xx = []
yy = []
labels = []

# %%
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from utils import readFoam

basepath = os.path.dirname(__file__)
os.chdir(basepath)

#folder = r"C:\Users\hbare\OneDrive - ltu.se\Doktorandstudier\2020.12.01_DATA"
folder = r"C:\Users\barhen\OneDrive - ltu.se\Doktorandstudier\2020.12.01_DATA"

# A-bsq, E-compr
dirs = [
#    r"\A0_A_pimple_v11a_c",
#    r"\A0_A_pimple_v11a_n",
#    r"\A0_A_pimple_v11a_m",
#    r"\A0_A_pimple_v11a_f",
#    r"\A0_A_pimple_v11a_uf",
#    r"\A0_A_pimple_v11a_uf2",
    r"\A0_A_pimple_v11a_uuf",
#    r"\A0_E_pimple_v11a_f",
#    r"\A0_E_pimple_v11a_uf",
#    r"\A0_E_pimple_v11a_uf2",
    r"\A0_E_pimple_v11a_uuf",

#    r"\A0_A_pimple_v11a_c_hot",
#    r"\A0_A_pimple_v11a_n_hot",
#    r"\A0_A_pimple_v11a_m_hot",
#    r"\A0_A_pimple_v11a_f_hot",
#    r"\A0_A_pimple_v11a_uf_hot",
#    r"\A0_A_pimple_v11a_uf2_hot",
    r"\A0_A_pimple_v11a_uuf_hot",

    r"\A0_E_pimple_v11a_uuf_hot",
    ]

#xs = np.linspace(df['T'].min()-1.0,df['T'].max()+1.0,1000)
xs = np.linspace(290,316,1000)
#xs = np.linspace(290,304,1000)

for dir in dirs:

    time = r"\360"

    path = folder+dir+time

    # foam files are treated the same way
    files = [   
    #   'p_rghMean',
    #   'p_rghPrime2Mean',
    #   'alphat',
       'TMean',
    #   'TPrime2Mean',
    #   'UMean',
    #   'C',
    #   'kMean',
    #   'epsilonMean',
    #   'nut',
    #   'turbulenceProperties%3AL',
    #   'turbulenceProperties%3AI',
        'V',
    #   'wallDistance'
    ]

    # my naming of variables in files
    content = [
    #   ['p_rgh'],
    #   ['p_rghPrime2Mean'],
    #   ['alphat'],
       ['T'],
    #   ['TPrime2Mean'],
    #   ['Ux','Uy','Uz'],
    #   ['Cx','Cy','Cz'],
    #   ['k'],
    #   ['epsilon'],
    #   ['nut'],
    #   ['tpL'],
    #   ['tpI'],
        ['V'],
    #   ['wallDistance']
    ]

    print(dir)

    df = pd.DataFrame()
    for i in range(len(files)):
        readFoam(path, files[i],content[i], df)

    if ('Ux' or 'Uy' or 'Uz') in df.columns:
        df['U_mag'] = np.linalg.norm(df[['Ux','Uy','Uz']].values,axis=1,ord=2)

    print(df)

    # %
    values = df['T']
    weights = df['V']

    plt.figure(1)
    N_bin = 100
    values.plot(kind="hist",bins=N_bin, weights=weights,histtype='step')
    count, division = np.histogram(values,weights=weights,bins=N_bin) # np histogram matches df.plot

# %
    # % #----------------------------
    from scipy import stats

    # https://het.as.utexas.edu/HET/Software/Scipy/generated/scipy.stats.gaussian_kde.html
    density = stats.gaussian_kde(values, 'scott', weights)
    
    density.covariance_factor = lambda : .05
#    density._compute_covariance()
    print(density.covariance_factor())

    ys = density(xs)*sum(weights)

    plt.figure()
    plt.plot(xs,ys) # integral under curve is sum(weights)
    plt.ylabel('Volume density [m3]')
    plt.show()

    from scipy import integrate
    y_int = integrate.cumtrapz(ys,xs, initial=0)
    print('Integral fraction: ', y_int[-1] / sum(df['V']) )

    # % ---------------------------
    xxh.append(division)
    yyh.append(count)
    xx.append(xs)
    yy.append(ys)
    strip = 18
    labels.append(dir[strip:])

    plt.close('all')


# %% ----------------------------
#plt.close('all')

# Plotting
import matplotlib as mpl
import matplotlib.font_manager
from matplotlib import rc

rc('font', **{'family': 'serif', 'serif': ['Computer Modern']})
rc('text', usetex=True)
rc('font', size=14)

# %
#labels = ['c: 62k','n: 89k','m: 147k','f: 282k']
#labels = ['f: 282k','f2: 652k','f3: 1.12M','f4: 2.17M']
#labels = ['f2: 652k','f3: 1.12M','f4: 2.17M']
labels = ['c: 62k','n: 89k','m: 147k','f: 282k','f2: 652k','f3: 1.12M','f4: 2.17M']
#labels = ['c: 62k','n: 89k','m: 147k','f: 282k','f2: 652k','f3: 1.12M','f4: 2.17M','f: 282k','f2: 652k','f3: 1.12M','f4: 2.17M']
labels = ['f4: Boussinesq','f4: Compressible','f4: hot-Boussinesq','f4: hot-Compressible']


plt.figure(figsize=(7, 4), dpi=80)
for i in range(len(xx)):
    plt.plot(xx[i],yy[i]) 
plt.legend(labels)
plt.ylabel('Volume density [m$^3$]')
plt.xlabel('Temperature [K]')
plt.tight_layout()
plt.xlim((xs.min(),xs.max()))
plt.show()

# %%
plt.savefig('fig03b.pdf')