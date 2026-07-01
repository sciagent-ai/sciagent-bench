"""
Phase 3 targeted RCWA scan.
Key changes vs phase 2:
  1. SetRegionCircle for all pillars (physical circles, not rectangles)
  2. Zone 2: dense Ly=200-400 step 25, sep=0-300 step 25 (117 configs)
  3. Zone 1 & 3: refined scan + circle pillars
  4. NumBasis=35 for high-angle accuracy
  5. Merit now penalises worst-case CE directly (not just mean_T/mean_R separately)
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
    1: {"wb": 110.0, "r_pillar": 50.0},    # dp=100, radius=50
    2: {"wb": 110.0, "r_pillar": 85.0},    # dp=170, radius=85
    3: {"wb": 100.0, "r_pillar": 98.0},    # dp=196, radius=98
}

ANGLES_AIR_DEG   = list(range(-10, 11, 2))
ANGLES_GLASS_DEG = [41.5, 46.4, 49.5, 52.1, 54.4, 56.5, 58.4, 60.3, 62.5]

# Zone-specific angle indices
ZONE_ANGLE_IDX = {1: [0,1,2,3], 2: [4,5,6], 3: [7,8,9,10]}

# Per-zone scan grids
LY_SCAN = {
    1: [300, 350, 400, 453, 500, 600, 700],
    2: list(range(200, 425, 25)),            # 200,225,...,400 (9 values)
    3: [300, 350, 400, 453, 500, 550, 600],
}
SEP_SCAN = {
    1: list(range(0, 250, 50)),
    2: list(range(0, 325, 25)),              # 0,25,...,300 (13 values)
    3: list(range(0, 350, 25)),
}

os.makedirs("/workspace/photonics", exist_ok=True)
LOG = open("/workspace/photonics/simulation_log.txt", "w")

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()

log("="*70)
log(f"Phase 3 RCWA | Circle pillars | NumBasis={NUM_BASIS}")
log(f"Zone2 scan: Ly={LY_SCAN[2]}")
log(f"Zone2 sep:  {SEP_SCAN[2]}")
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

    # Beam: full-y rectangle, width wb_nm
    bx  = beam_xc  / D_NM
    bhx = (wb_nm / 2.0) / D_NM
    bhy = ly / 2.0
    S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                         Center=(bx, 0), Angle=0, Halfwidths=(bhx, bhy))

    # Pillar: circle of radius r_pillar_nm (SetRegionCircle)
    px = pillar_xc / D_NM
    pr = r_pillar_nm / D_NM
    # Only add if pillar center is clearly separated from beam center
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
    if P_inc < 1e-20:
        return 0.0, theta_d
    orders = S.GetPoyntingFluxByOrder(Layer="Substrate", zOffset=0)
    basis  = S.GetBasisSet()
    eta_T  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 1 and int(round(ny)) == 0:
            eta_T = abs(orders[i][0]) / P_inc
            break
    return float(np.clip(eta_T, 0, 1)), theta_d


def get_eta_R_0(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, theta_glass_deg):
    S = _make_sim(Ly_nm, wb_nm, r_pillar, beam_xc, pillar_xc, True)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_glass_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)
    fwd, _ = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc  = abs(fwd)
    if P_inc < 1e-20:
        return 0.0
    orders = S.GetPoyntingFluxByOrder(Layer="AirTop", zOffset=0)
    basis  = S.GetBasisSet()
    eta_R  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 0 and int(round(ny)) == 0:
            eta_R = abs(orders[i][1]) / P_inc
            break
    return float(np.clip(eta_R, 0, 1))


def run_zone(zone_id, Ly_nm, sep_nm):
    z = ZONES[zone_id]
    wb, rp = z["wb"], z["r_pillar"]
    beam_xc   = 0.0
    pillar_xc = wb / 2.0 + sep_nm
    while pillar_xc >  D_NM / 2: pillar_xc -= D_NM
    while pillar_xc < -D_NM / 2: pillar_xc += D_NM

    eta_T_list, theta_d_list = [], []
    for ta in ANGLES_AIR_DEG:
        try:
            eT, td = get_eta_T_plus1(Ly_nm, wb, rp, beam_xc, pillar_xc, ta)
        except Exception as e:
            eT, td = 0.0, None
        eta_T_list.append(eT)
        theta_d_list.append(td)

    eta_R_list = []
    for tg in ANGLES_GLASS_DEG:
        try:
            eR = get_eta_R_0(Ly_nm, wb, rp, beam_xc, pillar_xc, tg)
        except Exception:
            eR = 0.0
        eta_R_list.append(eR)

    return eta_T_list, theta_d_list, eta_R_list


def coupling_eff_single(eta_T, eta_R_interp):
    """Goodsell 2-interaction formula."""
    return eta_T * (eta_R_interp + (1.0 - eta_R_interp) * eta_T)


def merit_direct_ce(zone_id, eta_T_list, theta_d_list, eta_R_list):
    """
    Compute zone-specific coupling efficiencies and score directly.
    Returns (score, min_CE, mean_CE, mean_T, mean_R).
    """
    idxs = ZONE_ANGLE_IDX[zone_id]
    ga   = np.array(ANGLES_GLASS_DEG)
    eR   = np.array(eta_R_list)
    ces  = []
    for i in idxs:
        eT = eta_T_list[i]
        td = theta_d_list[i]
        if td is None or eT < 1e-4:
            ces.append(0.0)
            continue
        eta_R_i = float(np.interp(td, ga, eR))
        ces.append(coupling_eff_single(eT, eta_R_i))
    min_ce  = min(ces) if ces else 0.0
    mean_ce = np.mean(ces) if ces else 0.0
    # Score: penalise low minimum CE
    score   = -min_ce - 0.5 * mean_ce   # negative so we MINIMISE (lower=better) → negate
    # Redefine as positive "badness":
    score   = (0.25 - min_ce)**2 + 0.1 * (0.25 - mean_ce)**2  # 0 if meets target
    mT = np.mean([eta_T_list[i] for i in idxs])
    mR = np.mean(eta_R_list)
    return score, min_ce, mean_ce, mT, mR


# ── Grid scans ────────────────────────────────────────────────────────────────
all_zone_results = {}
all_best_geo     = {}

for zid in [1, 2, 3]:
    ly_s  = LY_SCAN[zid]
    sep_s = SEP_SCAN[zid]
    n     = len(ly_s) * len(sep_s)
    log(f"\n{'='*60}\nZone {zid} | {n} configs | circle pillars | NumBasis={NUM_BASIS}\n{'='*60}")

    best_score = 1e9
    best_Ly = best_sep = None
    best_eT = best_td = best_eR = None

    for Ly, sep in product(ly_s, sep_s):
        try:
            eT, td, eR = run_zone(zid, Ly, sep)
            sc, minCE, meanCE, mT, mR = merit_direct_ce(zid, eT, td, eR)
            log(f"  Ly={Ly:4.0f} sep={sep:4.0f}: mT={mT:.3f} mR={mR:.3f} minCE={minCE:.3f} score={sc:.5f}")
            if sc < best_score:
                best_score = sc
                best_Ly, best_sep = Ly, sep
                best_eT, best_td, best_eR = eT, td, eR
        except Exception as e:
            log(f"  Ly={Ly} sep={sep}: EXCEPTION {e}")

    log(f"\n  Zone {zid} BEST: Ly={best_Ly} nm sep={best_sep} nm score={best_score:.5f}")
    idxs = ZONE_ANGLE_IDX[zid]
    log(f"  Zone-angles eta_T = {[f'{best_eT[i]:.3f}' for i in idxs]}")
    log(f"  Zone-angles theta_d = {[f'{best_td[i]:.1f}' if best_td[i] else 'None' for i in idxs]}")
    log(f"  eta_R = {[f'{v:.3f}' for v in best_eR]}")

    all_zone_results[zid] = {"eta_T": best_eT, "theta_diff": best_td, "eta_R": best_eR}
    all_best_geo[zid]     = {"Ly_nm": best_Ly, "sep_nm": best_sep}

    z = ZONES[zid]
    out = {
        "zone": zid,
        "geometry": {
            "d_nm": D_NM, "h_nm": H_NM,
            "Ly_nm": best_Ly, "wb_nm": z["wb"],
            "r_pillar_nm": z["r_pillar"], "sep_nm": best_sep,
        },
        "angles_air":   ANGLES_AIR_DEG,
        "eta_T":        best_eT,
        "theta_diff":   best_td,
        "angles_glass": ANGLES_GLASS_DEG,
        "eta_R":        best_eR,
    }
    with open(f"/workspace/photonics/zone{zid}_results.json", "w") as f:
        json.dump(out, f, indent=2)
    log(f"  Wrote zone{zid}_results.json")


# ── MFE ──────────────────────────────────────────────────────────────────────
log(f"\n{'='*60}\nMFE CALCULATION\n{'='*60}")
fov         = ANGLES_AIR_DEG
zone_assign = [1 if ta<=-3.33 else (2 if ta<=3.33 else 3) for ta in fov]
ga          = np.array(ANGLES_GLASS_DEG)
coupling_eff = []

for i, (ta, zid) in enumerate(zip(fov, zone_assign)):
    res   = all_zone_results[zid]
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
log(f"Best geometries: { {k: v for k,v in all_best_geo.items()} }")
log(f"{'='*60}")

mfe_out = {
    "mfe_value": mfe,
    "coupling_efficiency_per_angle": [float(c) for c in coupling_eff],
    "fov_angles":       [float(a) for a in fov],
    "zone_assignments": zone_assign,
    "meets_target":     meets,
    "best_geometries":  {str(k): v for k,v in all_best_geo.items()},
}
with open("/workspace/photonics/mfe_result.json", "w") as f:
    json.dump(mfe_out, f, indent=2)
log("Wrote mfe_result.json")
LOG.close()
print("SIMULATION COMPLETE", flush=True)
