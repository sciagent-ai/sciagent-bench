"""
Refined grid scan for Xiong 2025 metasurface reproduction.
Fixes:
  1. Zone-specific angle ranges for merit function
  2. Extended sep scan (up to 350 nm) for Zone 3
  3. Extra Ly values (350, 550 nm) for Zone 3
  4. Higher NumBasis (30) for better accuracy at high diffraction angles
"""

import S4
import numpy as np
import json
import os
from itertools import product

# ── Constants ─────────────────────────────────────────────────────────────────
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
NUM_BASIS  = 30     # increased for high-angle accuracy

ZONES = {
    1: {"wb": 110.0, "dp": 100.0, "pillar_w": 100.0},
    2: {"wb": 110.0, "dp": 170.0, "pillar_w": 156.5},
    3: {"wb": 100.0, "dp": 196.0, "pillar_w": 160.5},
}

ANGLES_AIR_DEG   = list(range(-10, 11, 2))   # indices 0-10
ANGLES_GLASS_DEG = [41.5, 46.4, 49.5, 52.1, 54.4, 56.5, 58.4, 60.3, 62.5]

# Zone-specific angular ranges (indices into ANGLES_AIR_DEG)
ZONE_ANGLE_IDX = {
    1: [0, 1, 2, 3],        # -10,-8,-6,-4
    2: [4, 5, 6],            # -2, 0,+2
    3: [7, 8, 9, 10],        # +4,+6,+8,+10
}

# Extended grid — Zone 3 gets wider sep range
LY_SCAN_Z3  = [300.0, 350.0, 400.0, 453.0, 500.0, 550.0, 600.0]
SEP_SCAN_Z3 = [0.0, 50.0, 100.0, 150.0, 200.0, 225.0, 250.0, 275.0, 300.0, 350.0]
LY_SCAN_Z12 = [300.0, 400.0, 453.0, 500.0, 600.0, 700.0, 800.0]
SEP_SCAN_Z12= [0.0, 50.0, 100.0, 150.0, 200.0]

TARGETS = {
    1: {"eta_T_center": 0.55, "eta_R_center": 0.40},
    2: {"eta_T_center": 0.42, "eta_R_center": 0.55},
    3: {"eta_T_center": 0.35, "eta_R_center": 0.65},
}

os.makedirs("/workspace/photonics", exist_ok=True)
LOG = open("/workspace/photonics/simulation_log.txt", "w")

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()

log("="*70)
log(f"REFINED RCWA scan | lambda={LAM_NM} nm d={D_NM} nm h={H_NM} nm NumBasis={NUM_BASIS}")
log(f"Zone-specific merit | extended Zone3 sep up to 350 nm")
log("="*70)


def _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm,
              beam_xc, pillar_xc, inverted=False):
    lx = 1.0
    ly = Ly_nm / D_NM
    S = S4.New(Lattice=((lx, 0), (0, ly)), NumBasis=NUM_BASIS)
    S.AddMaterial(Name="Air",  Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2", Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7", Epsilon=EPS_NBK7)
    if not inverted:
        S.AddLayer(Name="AirTop",    Thickness=0,          Material="Air")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM,  Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,          Material="NBK7")
    else:
        S.AddLayer(Name="AirTop",    Thickness=0,          Material="NBK7")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM,  Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,          Material="Air")
    # Beam
    bx  = beam_xc  / D_NM
    bhx = (wb_nm / 2.0) / D_NM
    bhy = ly / 2.0
    S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                         Center=(bx, 0), Angle=0, Halfwidths=(bhx, bhy))
    # Pillar
    px  = pillar_xc / D_NM
    phx = (pillar_w_nm / 2.0) / D_NM
    phy = (min(pillar_d_nm, Ly_nm) / 2.0) / D_NM
    if abs(pillar_xc - beam_xc) > 2.0:
        S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                             Center=(px, 0), Angle=0, Halfwidths=(phx, phy))
    S.SetFrequency(FREQ)
    return S


def get_eta_T_plus1(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, theta_air_deg):
    sin_d = N_AIR * np.sin(np.radians(theta_air_deg)) + LAM_OVER_D
    if abs(sin_d) >= N_NBK7:
        return 0.0, None
    theta_diff_deg = float(np.degrees(np.arcsin(sin_d / N_NBK7)))
    S = _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, False)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_air_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)
    fwd, _ = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc  = abs(fwd)
    if P_inc < 1e-20:
        return 0.0, theta_diff_deg
    orders = S.GetPoyntingFluxByOrder(Layer="Substrate", zOffset=0)
    basis  = S.GetBasisSet()
    eta_T  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 1 and int(round(ny)) == 0:
            eta_T = abs(orders[i][0]) / P_inc
            break
    return float(np.clip(eta_T, 0, 1)), theta_diff_deg


def get_eta_R_0(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, theta_glass_deg):
    S = _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, True)
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
    wb, dp, pw = z["wb"], z["dp"], z["pillar_w"]
    beam_xc   = 0.0
    pillar_xc = wb / 2.0 + sep_nm
    while pillar_xc >  D_NM / 2: pillar_xc -= D_NM
    while pillar_xc < -D_NM / 2: pillar_xc += D_NM

    eta_T_list   = []
    theta_d_list = []
    for ta in ANGLES_AIR_DEG:
        try:
            eT, td = get_eta_T_plus1(Ly_nm, wb, pw, dp, beam_xc, pillar_xc, ta)
        except Exception as e:
            eT, td = 0.0, None
        eta_T_list.append(eT)
        theta_d_list.append(td)

    eta_R_list = []
    for tg in ANGLES_GLASS_DEG:
        try:
            eR = get_eta_R_0(Ly_nm, wb, pw, dp, beam_xc, pillar_xc, tg)
        except Exception as e:
            eR = 0.0
        eta_R_list.append(eR)

    return eta_T_list, theta_d_list, eta_R_list


def merit_zonespecific(zone_id, eta_T, eta_R):
    """Merit using only the angles each zone is responsible for."""
    t    = TARGETS[zone_id]
    idxs = ZONE_ANGLE_IDX[zone_id]
    arr_T = np.array([eta_T[i] for i in idxs])
    arr_R = np.array(eta_R)
    mT    = float(np.mean(arr_T[arr_T > 0])) if np.any(arr_T > 0) else 0.0
    mR    = float(np.mean(arr_R))
    # Extra penalty if worst-case angle in zone is very low
    worst_T = float(np.min(arr_T)) if len(arr_T) > 0 else 0.0
    score   = (mT - t["eta_T_center"])**2 + (mR - t["eta_R_center"])**2 \
              + 0.5 * max(0.0, 0.25 - worst_T)**2   # penalty for low worst-case T
    return score, mT, mR, worst_T


# ── Grid scans ────────────────────────────────────────────────────────────────
all_zone_results = {}
all_best_geo     = {}

for zid in [1, 2, 3]:
    ly_scan  = LY_SCAN_Z3  if zid == 3 else LY_SCAN_Z12
    sep_scan = SEP_SCAN_Z3 if zid == 3 else SEP_SCAN_Z12
    n_configs = len(ly_scan) * len(sep_scan)
    log(f"\n{'='*60}\nZone {zid} grid scan ({n_configs} configs) [zone-specific merit]\n{'='*60}")

    best_score = 1e9
    best_Ly = best_sep = None
    best_eT = best_td = best_eR = None

    for Ly, sep in product(ly_scan, sep_scan):
        try:
            eT, td, eR = run_zone(zid, Ly, sep)
            sc, mT, mR, wT = merit_zonespecific(zid, eT, eR)
            log(f"  Ly={Ly:5.0f} sep={sep:5.0f}: mean_T={mT:.3f} mean_R={mR:.3f} worst_T={wT:.3f} score={sc:.5f}")
            if sc < best_score:
                best_score = sc
                best_Ly, best_sep = Ly, sep
                best_eT, best_td, best_eR = eT, td, eR
        except Exception as e:
            log(f"  Ly={Ly} sep={sep}: EXCEPTION {e}")

    log(f"\n  Zone {zid} BEST: Ly={best_Ly} nm sep={best_sep} nm score={best_score:.5f}")
    idxs = ZONE_ANGLE_IDX[zid]
    log(f"  Zone-angles eta_T = {[f'{best_eT[i]:.3f}' for i in idxs]}")
    log(f"  eta_R = {[f'{v:.3f}' for v in best_eR]}")

    all_zone_results[zid] = {"eta_T": best_eT, "theta_diff": best_td, "eta_R": best_eR}
    all_best_geo[zid]     = {"Ly_nm": best_Ly, "sep_nm": best_sep}

    z = ZONES[zid]
    out = {
        "zone": zid,
        "geometry": {
            "d_nm": D_NM, "h_nm": H_NM,
            "Ly_nm": best_Ly, "wb_nm": z["wb"],
            "dp_nm": z["dp"], "pillar_w_nm": z["pillar_w"],
            "sep_nm": best_sep,
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
fov = ANGLES_AIR_DEG
zone_assign = [1 if ta <= -3.33 else (2 if ta <= 3.33 else 3) for ta in fov]
coupling_eff = []

for i, (ta, zid) in enumerate(zip(fov, zone_assign)):
    res   = all_zone_results[zid]
    eta_T = res["eta_T"][i]
    td    = res["theta_diff"][i]
    if td is None or eta_T < 1e-6:
        coupling_eff.append(0.0)
        log(f"  theta_air={ta:+5.1f} zone={zid} eta_T={eta_T:.3f} td=None  CE=0.000")
        continue
    ga    = np.array(ANGLES_GLASS_DEG)
    eR    = np.array(res["eta_R"])
    eta_R = float(np.interp(td, ga, eR))
    ce    = eta_T * (eta_R + (1.0 - eta_R) * eta_T)
    coupling_eff.append(ce)
    log(f"  theta_air={ta:+5.1f} zone={zid} eta_T={eta_T:.3f} td={td:.1f} eta_R={eta_R:.3f} CE={ce:.3f}")

mfe   = min(coupling_eff) if coupling_eff else 0.0
meets = bool(mfe >= 0.25)

log(f"\n{'='*60}")
log(f"MFE = {mfe:.4f} ({mfe*100:.2f}%)")
log(f"Meets >= 25% target: {meets}")
log(f"Coupling eff: {[f'{v:.3f}' for v in coupling_eff]}")
log(f"{'='*60}")

mfe_out = {
    "mfe_value": mfe,
    "coupling_efficiency_per_angle": [float(c) for c in coupling_eff],
    "fov_angles":       [float(a) for a in fov],
    "zone_assignments": zone_assign,
    "meets_target":     meets,
    "best_geometries": {str(k): v for k, v in all_best_geo.items()},
}
with open("/workspace/photonics/mfe_result.json", "w") as f:
    json.dump(mfe_out, f, indent=2)
log("Wrote mfe_result.json")
LOG.close()
print("SIMULATION COMPLETE", flush=True)
