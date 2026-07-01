"""
Phase 5: Ultra-fine Zone 2 scan only. Load Zone 1&3 from Phase 4/3.
Target: CE(+2°) >= 0.25 for Zone 2.
"""
import S4
import numpy as np
import json
import os
from itertools import product

LAM_NM=532.0; D_NM=453.0; H_NM=250.0
N_TIO2=2.37; N_NBK7=1.5195; N_AIR=1.0
EPS_TIO2=N_TIO2**2; EPS_NBK7=N_NBK7**2; EPS_AIR=1.0
LAM_OVER_D=LAM_NM/D_NM; FREQ=D_NM/LAM_NM; NUM_BASIS=40

ZONES={1:{"wb":110.0,"r_pillar":50.0}, 2:{"wb":110.0,"r_pillar":85.0}, 3:{"wb":100.0,"r_pillar":98.0}}
ANGLES_AIR_DEG=list(range(-10,11,2))
ANGLES_GLASS_DEG=[41.5,46.4,49.5,52.1,54.4,56.5,58.4,60.3,62.5]
# For Zone 2 the critical angles are idx 4,5,6 (-2,0,+2) 
# Zone 2 worst is +2° idx=6, theta_d=52.7°

os.makedirs("/workspace/photonics",exist_ok=True)
LOG=open("/workspace/photonics/simulation_log.txt","w")
def log(m): print(m,flush=True); LOG.write(m+"\n"); LOG.flush()

log("="*70)
log(f"Phase 5: Ultra-fine Zone 2 | NumBasis={NUM_BASIS}")
log("="*70)

def _make_sim(Ly_nm,wb_nm,r_pillar_nm,beam_xc,pillar_xc,inverted=False):
    lx=1.0; ly=Ly_nm/D_NM
    S=S4.New(Lattice=((lx,0),(0,ly)),NumBasis=NUM_BASIS)
    S.AddMaterial(Name="Air",Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2",Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7",Epsilon=EPS_NBK7)
    if not inverted:
        S.AddLayer(Name="AirTop",Thickness=0,Material="Air")
        S.AddLayer(Name="TiO2Layer",Thickness=H_NM/D_NM,Material="Air")
        S.AddLayer(Name="Substrate",Thickness=0,Material="NBK7")
    else:
        S.AddLayer(Name="AirTop",Thickness=0,Material="NBK7")
        S.AddLayer(Name="TiO2Layer",Thickness=H_NM/D_NM,Material="Air")
        S.AddLayer(Name="Substrate",Thickness=0,Material="Air")
    bx=beam_xc/D_NM; bhx=(wb_nm/2.0)/D_NM; bhy=ly/2.0
    S.SetRegionRectangle(Layer="TiO2Layer",Material="TiO2",Center=(bx,0),Angle=0,Halfwidths=(bhx,bhy))
    px=pillar_xc/D_NM; pr=r_pillar_nm/D_NM
    if abs(pillar_xc-beam_xc)>r_pillar_nm*0.3:
        S.SetRegionCircle(Layer="TiO2Layer",Material="TiO2",Center=(px,0),Radius=pr)
    S.SetFrequency(FREQ)
    return S

def eta_T1(Ly,wb,rp,bxc,pxc,ta):
    sd=N_AIR*np.sin(np.radians(ta))+LAM_OVER_D
    if abs(sd)>=N_NBK7: return 0.0,None
    td=float(np.degrees(np.arcsin(sd/N_NBK7)))
    S=_make_sim(Ly,wb,rp,bxc,pxc,False)
    S.SetExcitationPlanewave(IncidenceAngles=(ta,0),sAmplitude=1.0,pAmplitude=0.0,Order=0)
    fwd,_=S.GetPoyntingFlux(Layer="AirTop",zOffset=0); P=abs(fwd)
    if P<1e-20: return 0.0,td
    ords=S.GetPoyntingFluxByOrder(Layer="Substrate",zOffset=0)
    bas=S.GetBasisSet(); eT=0.0
    for i,(nx,ny) in enumerate(bas):
        if int(round(nx))==1 and int(round(ny))==0: eT=abs(ords[i][0])/P; break
    return float(np.clip(eT,0,1)),td

def eta_R0(Ly,wb,rp,bxc,pxc,tg):
    S=_make_sim(Ly,wb,rp,bxc,pxc,True)
    S.SetExcitationPlanewave(IncidenceAngles=(tg,0),sAmplitude=1.0,pAmplitude=0.0,Order=0)
    fwd,_=S.GetPoyntingFlux(Layer="AirTop",zOffset=0); P=abs(fwd)
    if P<1e-20: return 0.0
    ords=S.GetPoyntingFluxByOrder(Layer="AirTop",zOffset=0)
    bas=S.GetBasisSet(); eR=0.0
    for i,(nx,ny) in enumerate(bas):
        if int(round(nx))==0 and int(round(ny))==0: eR=abs(ords[i][1])/P; break
    return float(np.clip(eR,0,1))

def run_zone(zid,Ly,sep):
    z=ZONES[zid]; wb,rp=z["wb"],z["r_pillar"]
    bxc=0.0; pxc=wb/2.0+sep
    while pxc>D_NM/2: pxc-=D_NM
    while pxc<-D_NM/2: pxc+=D_NM
    eTs,tds=[],[]
    for ta in ANGLES_AIR_DEG:
        try: eT,td=eta_T1(Ly,wb,rp,bxc,pxc,ta)
        except: eT,td=0.0,None
        eTs.append(eT); tds.append(td)
    eRs=[]
    for tg in ANGLES_GLASS_DEG:
        try: eR=eta_R0(Ly,wb,rp,bxc,pxc,tg)
        except: eR=0.0
        eRs.append(eR)
    return eTs,tds,eRs

def ce_angle(eTs,tds,eRs,idx):
    eT=eTs[idx]; td=tds[idx]
    if td is None or eT<1e-4: return 0.0
    eR=float(np.interp(td,ANGLES_GLASS_DEG,eRs))
    return eT*(eR+(1.0-eR)*eT)

def merit_z2(eTs,tds,eRs):
    ces=[ce_angle(eTs,tds,eRs,i) for i in [4,5,6]]
    minCE=min(ces); meanCE=np.mean(ces)
    return (0.25-minCE)**2+0.1*(0.25-meanCE)**2, minCE, meanCE

# Fine scan: Ly=200-320 step 5, sep=5-80 step 5 → 25×16=400 configs
LY2  = list(range(200, 325, 5))
SEP2 = list(range(5, 85, 5))
n2   = len(LY2)*len(SEP2)
log(f"\nZone 2 ultra-fine: {n2} configs Ly={LY2[0]}-{LY2[-1]} sep={SEP2[0]}-{SEP2[-1]}")

best2_score=1e9; best2_Ly=best2_sep=None; best2_eT=best2_td=best2_eR=None

for Ly,sep in product(LY2,SEP2):
    try:
        eT,td,eR=run_zone(2,Ly,sep)
        sc,minCE,meanCE=merit_z2(eT,td,eR)
        log(f"  Z2 Ly={Ly:4d} sep={sep:3d}: CE(-2,0,+2)=[{ce_angle(eT,td,eR,4):.3f},{ce_angle(eT,td,eR,5):.3f},{ce_angle(eT,td,eR,6):.3f}] minCE={minCE:.3f} sc={sc:.6f}")
        if sc<best2_score:
            best2_score=sc; best2_Ly,best2_sep=Ly,sep; best2_eT,best2_td,best2_eR=eT,td,eR
    except Exception as e:
        log(f"  Z2 Ly={Ly} sep={sep}: ERR {e}")

log(f"\n  Zone 2 BEST: Ly={best2_Ly} sep={best2_sep} score={best2_score:.6f}")
log(f"  eta_T(zone)=[{best2_eT[4]:.3f},{best2_eT[5]:.3f},{best2_eT[6]:.3f}]")
log(f"  eta_R={[f'{v:.3f}' for v in best2_eR]}")

z2geo={"d_nm":D_NM,"h_nm":H_NM,"Ly_nm":best2_Ly,"wb_nm":110.0,"r_pillar_nm":85.0,"sep_nm":best2_sep}
z2out={"zone":2,"geometry":z2geo,"angles_air":ANGLES_AIR_DEG,"eta_T":best2_eT,
       "theta_diff":best2_td,"angles_glass":ANGLES_GLASS_DEG,"eta_R":best2_eR}
with open("/workspace/photonics/zone2_results.json","w") as f: json.dump(z2out,f,indent=2)
log("  Wrote zone2_results.json")

# Load zone 1 & 3
with open("/workspace/photonics/zone1_results.json") as f: z1=json.load(f)
with open("/workspace/photonics/zone3_results.json") as f: z3=json.load(f)
log(f"  Loaded Zone1 geo: {z1['geometry']}")
log(f"  Loaded Zone3 geo: {z3['geometry']}")

zone_results={
    1:{"eta_T":z1["eta_T"],"theta_diff":z1["theta_diff"],"eta_R":z1["eta_R"]},
    2:{"eta_T":best2_eT,"theta_diff":best2_td,"eta_R":best2_eR},
    3:{"eta_T":z3["eta_T"],"theta_diff":z3["theta_diff"],"eta_R":z3["eta_R"]},
}

# MFE
log(f"\n{'='*60}\nMFE\n{'='*60}")
fov=ANGLES_AIR_DEG
zone_assign=[1 if ta<=-3.33 else (2 if ta<=3.33 else 3) for ta in fov]
ga=np.array(ANGLES_GLASS_DEG)
ces=[]
for i,(ta,zid) in enumerate(zip(fov,zone_assign)):
    res=zone_results[zid]; eT=res["eta_T"][i]; td=res["theta_diff"][i]
    if td is None or eT<1e-6: ces.append(0.0); log(f"  {ta:+5.1f} z{zid} eT={eT:.3f} td=None CE=0.000"); continue
    eR=float(np.interp(td,ga,np.array(res["eta_R"])))
    ce=eT*(eR+(1.0-eR)*eT); ces.append(ce)
    log(f"  {ta:+5.1f} z{zid} eT={eT:.3f} td={td:.1f} eR={eR:.3f} CE={ce:.3f}")

mfe=min(ces); meets=bool(mfe>=0.25)
log(f"\nMFE={mfe:.4f} ({mfe*100:.2f}%)  meets>=25%: {meets}")
log(f"CEs: {[f'{v:.3f}' for v in ces]}")

mfe_out={"mfe_value":mfe,"coupling_efficiency_per_angle":[float(c) for c in ces],
         "fov_angles":[float(a) for a in fov],"zone_assignments":zone_assign,"meets_target":meets,
         "best_geometries":{"1":z1["geometry"],"2":z2geo,"3":z3["geometry"]}}
with open("/workspace/photonics/mfe_result.json","w") as f: json.dump(mfe_out,f,indent=2)
log("Wrote mfe_result.json")
LOG.close()
print("SIMULATION COMPLETE",flush=True)
