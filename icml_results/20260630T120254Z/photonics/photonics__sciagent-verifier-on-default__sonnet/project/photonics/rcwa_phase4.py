"""
Phase 4: Fine Zone 1 targeted scan + load Zone 2&3 from phase 3.
Goal: push Zone 1 CE at -4° above 0.25 → MFE >= 25%.
"""

import S4
import numpy as np
import json
import os
from itertools import product

LAM_NM     = 532.0
D_NM       = 453.0
H_NM       = 250.0
N_TIO2     = 2.37
N_NBK7     = 1.5195
N_AIR      = 1.0
EPS_TIO2   = N_TIO2**2
EPS_NBK7   = N_NBK7**2
EPS_AIR    = 1.0
LAM_OVER_D = LAM_NM / D_NM
FREQ       = D_NM / LAM_NM
NUM_BASIS  = 35

ZONES = {
    1: {"wb": 110.0, "r_pillar": 50.0},
    2: {"wb": 110.0, "r_pillar": 85.0},
    3: {"wb": 100.0, "r_pillar": 98.0},
}

ANGLES_AIR_DEG   = list(range(-10, 11, 2))
ANGLES_GLASS_DEG = [41.5, 46.4, 49.5, 52.1, 54.4, 56.5, 58.4, 60.3, 62.5]
ZONE_ANGLE_IDX   = {1: [0,1,2,3], 2: [4,5,6], 3: [7,8,9,10]}

os.makedirs("/workspace/photonics", exist_ok=True)
LOG = open("/workspace/photonics/simulation_log.txt", "w")

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()

log("="*70)
log("Phase 4: Fine Zone 1 scan | keep Zone 2&3 from Phase 3")
log("="*70)


def _make_sim(Ly_nm, wb_nm, r_pillar_nm, beam_xc, pillar_xc, inverted=False):
    lx = 1.0
    ly = Ly_nm / D_NM
    S = S4.New(Lattice=((lx, 0), (0, ly)), NumBasis=NUM_BASIS)
    S.AddMaterial(Name="Air",  Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2", Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7", Epsilon=EPS_NBK7)
    if not inverted:
        S.AddLayer(Name="AirTop",    Thickness=0,         Material="Air")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM, Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,         Material="NBK7")
    else:
        S.AddLayer(Name="AirTop",    Thickness=0,         Material="NBK7")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM, Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,         Material="Air")
    bx  = beam_xc / D_NM
    bhx = (wb_nm / 2.0) / D_NM
    bhy = ly / 2.0
    S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                         Center=(bx, 0), Angle=0, Halfwidths=(bhx, bhy))
    px = pillar_xc / D_NM
    pr = r_pillar_nm / D_NM
    if abs(pillar_xc - beam_xc) > r_pillar_nm * 0.3:
        S.SetRegionCircle(Layer="TiO2Layer", Material="TiO2",
                          Center=(px, 0), Radius=pr)
    S.SetFrequency(FREQ)
    return S


def get_eta_T_plus1(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, theta_air_deg):
    sin_d = N_AIR * np.sin(np.radians(theta_air_deg)) + LAM_OVER_D
    if abs(sin_d) >= N_NBK7:
        return 0.0, None
    theta_d = float(np.degrees(np.arcsin(sin_d / N_NBK7)))
    S = _make_sim(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, False)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_air_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)
    fwd, _ = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc  = abs(fwd)
    if P_inc < 1e-20: return 0.0, theta_d
    orders = S.GetPoyntingFluxByOrder(Layer="Substrate", zOffset=0)
    basis  = S.GetBasisSet()
    eta_T  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 1 and int(round(ny)) == 0:
            eta_T = abs(orders[i][0]) / P_inc; break
    return float(np.clip(eta_T, 0, 1)), theta_d


def get_eta_R_0(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, theta_glass_deg):
    S = _make_sim(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, True)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_glass_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)
    fwd, _ = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc  = abs(fwd)
    if P_inc < 1e-20: return 0.0
    orders = S.GetPoyntingFluxByOrder(Layer="AirTop", zOffset=0)
    basis  = S.GetBasisSet()
    eta_R  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 0 and int(round(ny)) == 0:
            eta_R = abs(orders[i][1]) / P_inc; break
    return float(np.clip(eta_R, 0, 1))


def run_zone(zone_id, Ly_nm, sep_nm):
    z = ZONES[zone_id]
    wb, rp = z["wb"], z["r_pillar"]
    beam_xc   = 0.0
    pillar_xc = wb / 2.0 + sep_nm
    while pillar_xc >  D_NM/2: pillar_xc -= D_NM
    while pillar_xc < -D_NM/2: pillar_xc += D_NM
    eta_T_list, theta_d_list = [], []
    for ta in ANGLES_AIR_DEG:
        try:
            eT, td = get_eta_T_plus1(Ly_nm, wb, rp, beam_xc, pillar_xc, ta)
        except Exception:
            eT, td = 0.0, None
        eta_T_list.append(eT); theta_d_list.append(td)
    eta_R_list = []
    for tg in ANGLES_GLASS_DEG:
        try: eR = get_eta_R_0(Ly_nm, wb, rp, beam_xc, pillar_xc, tg)
        except Exception: eR = 0.0
        eta_R_list.append(eR)
    return eta_T_list, theta_d_list, eta_R_list


def ce_at_angle(eta_T_list, theta_d_list, eta_R_list, angle_idx):
    eta_T = eta_T_list[angle_idx]
    td    = theta_d_list[angle_idx]
    if td is None or eta_T < 1e-4: return 0.0
    eta_R = float(np.interp(td, ANGLES_GLASS_DEG, eta_R_list))
    return eta_T * (eta_R + (1.0 - eta_R) * eta_T)


def merit_z1(eta_T, theta_d, eta_R):
    """Maximise minimum CE over zone 1 angles (-10 to -4 deg, idx 0-3).
       Score = (0.25 - min_CE)^2 + 0.1*(0.25 - mean_CE)^2, target 0.
    """
    idxs = ZONE_ANGLE_IDX[1]
    ces  = [ce_at_angle(eta_T, theta_d, eta_R, i) for i in idxs]
    min_ce  = min(ces)
    mean_ce = np.mean(ces)
    score   = (0.25 - min_ce)**2 + 0.1*(0.25 - mean_ce)**2
    return score, min_ce, mean_ce


# ── Zone 1 fine scan ─────────────────────────────────────────────────────────
# Focus: Ly 250-500 step 25, sep 50-300 step 25 (106 configs)
LY1  = list(range(250, 525, 25))
SEP1 = list(range(50, 325, 25))
n1   = len(LY1)*len(SEP1)
log(f"\nZone 1 fine scan: {n1} configs (Ly={LY1[0]}-{LY1[-1]}, sep={SEP1[0]}-{SEP1[-1]})")

best1_score = 1e9
best1_Ly = best1_sep = None
best1_eT = best1_td = best1_eR = None

for Ly, sep in product(LY1, SEP1):
    try:
        eT, td, eR = run_zone(1, Ly, sep)
        sc, minCE, meanCE = merit_z1(eT, td, eR)
        mT = np.mean([eT[i] for i in ZONE_ANGLE_IDX[1]])
        mR = np.mean(eR)
        log(f"  Z1 Ly={Ly:4d} sep={sep:4d}: mT={mT:.3f} mR={mR:.3f} minCE={minCE:.3f} score={sc:.5f}")
        if sc < best1_score:
            best1_score = sc
            best1_Ly, best1_sep = Ly, sep
            best1_eT, best1_td, best1_eR = eT, td, eR
    except Exception as e:
        log(f"  Z1 Ly={Ly} sep={sep}: ERR {e}")

log(f"\n  Zone 1 BEST: Ly={best1_Ly} sep={best1_sep} score={best1_score:.5f}")
log(f"  Zone-angles eta_T = {[f'{best1_eT[i]:.3f}' for i in ZONE_ANGLE_IDX[1]]}")
log(f"  eta_R = {[f'{v:.3f}' for v in best1_eR]}")

# Save zone 1 JSON
z1out = {
    "zone": 1,
    "geometry": {"d_nm":D_NM,"h_nm":H_NM,"Ly_nm":best1_Ly,"wb_nm":110.0,
                 "r_pillar_nm":50.0,"sep_nm":best1_sep},
    "angles_air": ANGLES_AIR_DEG, "eta_T": best1_eT,
    "theta_diff": best1_td, "angles_glass": ANGLES_GLASS_DEG, "eta_R": best1_eR,
}
with open("/workspace/photonics/zone1_results.json","w") as f:
    json.dump(z1out, f, indent=2)
log("  Wrote zone1_results.json")


# ── Load Zone 2 & 3 from Phase 3 ─────────────────────────────────────────────
log("\nLoading Zone 2 & 3 from phase 3 results...")
zone_results = {}

with open("/workspace/photonics/zone2_results.json") as f:
    z2 = json.load(f)
with open("/workspace/photonics/zone3_results.json") as f:
    z3 = json.load(f)

zone_results[1] = {"eta_T": best1_eT, "theta_diff": best1_td, "eta_R": best1_eR}
zone_results[2] = {"eta_T": z2["eta_T"], "theta_diff": z2["theta_diff"], "eta_R": z2["eta_R"]}
zone_results[3] = {"eta_T": z3["eta_T"], "theta_diff": z3["theta_diff"], "eta_R": z3["eta_R"]}

log(f"  Zone 2 geo: {z2['geometry']}")
log(f"  Zone 3 geo: {z3['geometry']}")


# ── MFE ──────────────────────────────────────────────────────────────────────
log(f"\n{'='*60}\nMFE CALCULATION\n{'='*60}")
fov         = ANGLES_AIR_DEG
zone_assign = [1 if ta<=-3.33 else (2 if ta<=3.33 else 3) for ta in fov]
ga          = np.array(ANGLES_GLASS_DEG)
coupling_eff = []

for i, (ta, zid) in enumerate(zip(fov, zone_assign)):
    res   = zone_results[zid]
    eta_T = res["eta_T"][i]
    td    = res["theta_diff"][i]
    if td is None or eta_T < 1e-6:
        coupling_eff.append(0.0)
        log(f"  theta_air={ta:+5.1f} z={zid} eta_T={eta_T:.3f} td=None  CE=0.000")
        continue
    eta_R = float(np.interp(td, ga, np.array(res["eta_R"])))
    ce    = eta_T * (eta_R + (1.0 - eta_R) * eta_T)
    coupling_eff.append(ce)
    log(f"  theta_air={ta:+5.1f} z={zid} eta_T={eta_T:.3f} td={td:.1f}° eta_R={eta_R:.3f} CE={ce:.3f}")

mfe   = min(coupling_eff) if coupling_eff else 0.0
meets = bool(mfe >= 0.25)

log(f"\n{'='*60}")
log(f"MFE = {mfe:.4f} ({mfe*100:.2f}%)")
log(f"Meets >= 25% target: {meets}")
log(f"Coupling per angle: {[f'{v:.3f}' for v in coupling_eff]}")
log(f"Zone 1 best: Ly={best1_Ly} sep={best1_sep}")
log(f"Zone 2 best: Ly={z2['geometry']['Ly_nm']} sep={z2['geometry']['sep_nm']}")
log(f"Zone 3 best: Ly={z3['geometry']['Ly_nm']} sep={z3['geometry']['sep_nm']}")
log(f"{'='*60}")

mfe_out = {
    "mfe_value": mfe,
    "coupling_efficiency_per_angle": [float(c) for c in coupling_eff],
    "fov_angles":       [float(a) for a in fov],
    "zone_assignments": zone_assign,
    "meets_target":     meets,
    "best_geometries": {
        "1": z1out["geometry"],
        "2": z2["geometry"],
        "3": z3["geometry"],
    },
}
with open("/workspace/photonics/mfe_result.json","w") as f:
    json.dump(mfe_out, f, indent=2)
log("Wrote mfe_result.json")
LOG.close()
print("SIMULATION COMPLETE", flush=True)
