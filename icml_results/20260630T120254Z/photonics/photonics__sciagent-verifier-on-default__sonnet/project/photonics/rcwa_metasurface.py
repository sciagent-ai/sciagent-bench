"""
Rigorous S4 RCWA simulation of TiO2/N-BK7 three-zone metasurface in-coupler
Reproducing Xiong et al. 2025 (Optical Materials Express), lambda=532 nm.
"""

import S4
import numpy as np
import json
import os
from itertools import product

# ── Physical constants ────────────────────────────────────────────────────────
LAM_NM   = 532.0
D_NM     = 453.0
H_NM     = 250.0
N_TIO2   = 2.37
N_NBK7   = 1.5195
N_AIR    = 1.0
EPS_TIO2 = N_TIO2**2
EPS_NBK7 = N_NBK7**2
EPS_AIR  = 1.0
LAM_OVER_D = LAM_NM / D_NM
FREQ     = D_NM / LAM_NM   # S4 frequency in units of c/a
NUM_BASIS = 25

# Per-zone geometry (Table 1)
ZONES = {
    1: {"wb": 110.0, "dp": 100.0, "pillar_w": 100.0},
    2: {"wb": 110.0, "dp": 170.0, "pillar_w": 156.5},
    3: {"wb": 100.0, "dp": 196.0, "pillar_w": 160.5},
}

ANGLES_AIR_DEG   = list(range(-10, 11, 2))   # -10,-8,...,+10 (11 pts)
ANGLES_GLASS_DEG = [41.5, 46.4, 49.5, 52.1, 54.4, 56.5, 58.4, 60.3, 62.5]

LY_SCAN  = [300.0, 400.0, 453.0, 500.0, 600.0, 700.0, 800.0]
SEP_SCAN = [0.0, 50.0, 100.0, 150.0, 200.0]

TARGETS = {
    1: {"eta_T_center": 0.60, "eta_R_center": 0.40},
    2: {"eta_T_center": 0.45, "eta_R_center": 0.55},
    3: {"eta_T_center": 0.35, "eta_R_center": 0.65},
}

os.makedirs("/workspace/photonics", exist_ok=True)
LOG = open("/workspace/photonics/simulation_log.txt", "w")

def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()

log("="*70)
log(f"Xiong 2025 TiO2/N-BK7 metasurface RCWA | lambda={LAM_NM} nm d={D_NM} nm h={H_NM} nm NumBasis={NUM_BASIS}")
log(f"FREQ={FREQ:.6f}  LAM/d={LAM_OVER_D:.6f}")
log("="*70)


def _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm,
              beam_xc, pillar_xc, inverted=False):
    """Build S4 simulation. inverted=True puts NBK7 on top (glass-side excitation)."""
    lx = 1.0
    ly = Ly_nm / D_NM

    S = S4.New(Lattice=((lx, 0), (0, ly)), NumBasis=NUM_BASIS)
    S.AddMaterial(Name="Air",  Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2", Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7", Epsilon=EPS_NBK7)

    if not inverted:
        # Normal: Air superstrate | TiO2 features | NBK7 substrate
        S.AddLayer(Name="AirTop",    Thickness=0,          Material="Air")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM,  Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,          Material="NBK7")
    else:
        # Inverted: NBK7 superstrate | TiO2 features | Air substrate
        S.AddLayer(Name="AirTop",    Thickness=0,          Material="NBK7")
        S.AddLayer(Name="TiO2Layer", Thickness=H_NM/D_NM,  Material="Air")
        S.AddLayer(Name="Substrate", Thickness=0,          Material="Air")

    # Beam: rectangle, full y-extent, width wb_nm, centered at beam_xc
    bx  = beam_xc  / D_NM
    bhx = (wb_nm / 2.0) / D_NM
    bhy = ly / 2.0
    S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                         Center=(bx, 0), Angle=0, Halfwidths=(bhx, bhy))

    # Pillar: rectangle approx for circle/clipped-circle
    px  = pillar_xc / D_NM
    phx = (pillar_w_nm / 2.0) / D_NM
    phy = (min(pillar_d_nm, Ly_nm) / 2.0) / D_NM
    # Only add if pillar doesn't fully overlap beam
    if abs(pillar_xc - beam_xc) > 2.0:
        S.SetRegionRectangle(Layer="TiO2Layer", Material="TiO2",
                             Center=(px, 0), Angle=0, Halfwidths=(phx, phy))

    S.SetFrequency(FREQ)
    return S


def get_eta_T_plus1(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, theta_air_deg):
    """Diffraction efficiency into glass +1 order, light from air."""
    theta_rad = np.radians(theta_air_deg)
    sin_d = N_AIR * np.sin(theta_rad) + 1.0 * LAM_OVER_D
    if abs(sin_d) >= N_NBK7:
        return 0.0, None   # evanescent
    theta_diff_deg = float(np.degrees(np.arcsin(sin_d / N_NBK7)))

    S = _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, inverted=False)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_air_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)

    fwd_inc, bwd_inc = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc = abs(fwd_inc)
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
    """Zeroth-order reflection, light from glass side (inverted stack)."""
    S = _make_sim(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm, beam_xc, pillar_xc, inverted=True)
    S.SetExcitationPlanewave(IncidenceAngles=(theta_glass_deg, 0),
                             sAmplitude=1.0, pAmplitude=0.0, Order=0)

    fwd_inc, bwd_inc = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc = abs(fwd_inc)
    if P_inc < 1e-20:
        return 0.0

    orders = S.GetPoyntingFluxByOrder(Layer="AirTop", zOffset=0)
    basis  = S.GetBasisSet()
    eta_R  = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == 0 and int(round(ny)) == 0:
            eta_R = abs(orders[i][1]) / P_inc   # backward = reflected
            break

    return float(np.clip(eta_R, 0, 1))


def run_zone(zone_id, Ly_nm, sep_nm):
    """Run full diffraction+reflection sweeps for one geometry."""
    z = ZONES[zone_id]
    wb, dp, pw = z["wb"], z["dp"], z["pillar_w"]
    beam_xc   = 0.0
    pillar_xc = wb / 2.0 + sep_nm
    # wrap into [-d/2, d/2]
    while pillar_xc >  D_NM / 2: pillar_xc -= D_NM
    while pillar_xc < -D_NM / 2: pillar_xc += D_NM

    eta_T_list    = []
    theta_d_list  = []
    for ta in ANGLES_AIR_DEG:
        try:
            eT, td = get_eta_T_plus1(Ly_nm, wb, pw, dp, beam_xc, pillar_xc, ta)
        except Exception as e:
            log(f"    WARN z{zone_id} T theta={ta}: {e}")
            eT, td = 0.0, None
        eta_T_list.append(eT)
        theta_d_list.append(td)

    eta_R_list = []
    for tg in ANGLES_GLASS_DEG:
        try:
            eR = get_eta_R_0(Ly_nm, wb, pw, dp, beam_xc, pillar_xc, tg)
        except Exception as e:
            log(f"    WARN z{zone_id} R theta={tg}: {e}")
            eR = 0.0
        eta_R_list.append(eR)

    return eta_T_list, theta_d_list, eta_R_list


def merit(zone_id, eta_T, eta_R):
    t = TARGETS[zone_id]
    arr_T = np.array(eta_T)
    arr_R = np.array(eta_R)
    mT = float(np.mean(arr_T[arr_T > 0])) if np.any(arr_T > 0) else 0.0
    mR = float(np.mean(arr_R))
    score = (mT - t["eta_T_center"])**2 + (mR - t["eta_R_center"])**2
    return score, mT, mR


# ── Main grid scan ────────────────────────────────────────────────────────────
all_zone_results = {}
all_best_geo     = {}

for zid in [1, 2, 3]:
    log(f"\n{'='*60}\nZone {zid} grid scan ({len(LY_SCAN)*len(SEP_SCAN)} configs)\n{'='*60}")
    best_score = 1e9
    best_Ly = best_sep = None
    best_eT = best_td = best_eR = None

    for Ly, sep in product(LY_SCAN, SEP_SCAN):
        try:
            eT, td, eR = run_zone(zid, Ly, sep)
            sc, mT, mR = merit(zid, eT, eR)
            log(f"  Ly={Ly:5.0f} sep={sep:5.0f}: mean_T={mT:.3f} mean_R={mR:.3f} score={sc:.5f}")
            if sc < best_score:
                best_score = sc
                best_Ly, best_sep = Ly, sep
                best_eT, best_td, best_eR = eT, td, eR
        except Exception as e:
            log(f"  Ly={Ly} sep={sep}: EXCEPTION {e}")

    log(f"\n  Zone {zid} BEST: Ly={best_Ly} nm sep={best_sep} nm score={best_score:.5f}")
    log(f"  eta_T={[f'{v:.3f}' for v in best_eT]}")
    log(f"  eta_R={[f'{v:.3f}' for v in best_eR]}")

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


# ── MFE calculation ───────────────────────────────────────────────────────────
log(f"\n{'='*60}\nMFE CALCULATION\n{'='*60}")
fov = ANGLES_AIR_DEG
zone_assign = [1 if ta <= -3.33 else (2 if ta <= 3.33 else 3) for ta in fov]
coupling_eff = []

for i, (ta, zid) in enumerate(zip(fov, zone_assign)):
    res = all_zone_results[zid]
    eta_T = res["eta_T"][i]
    td    = res["theta_diff"][i]

    if td is None or eta_T < 1e-6:
        coupling_eff.append(0.0)
        log(f"  theta_air={ta:+5.1f} zone={zid} eta_T={eta_T:.3f} td=None  CE=0.000")
        continue

    # Interpolate eta_R at diffraction angle
    ga = np.array(ANGLES_GLASS_DEG)
    eR = np.array(res["eta_R"])
    eta_R = float(np.interp(td, ga, eR))

    # Goodsell 2-interaction formula
    ce = eta_T * (eta_R + (1.0 - eta_R) * eta_T)
    coupling_eff.append(ce)
    log(f"  theta_air={ta:+5.1f} zone={zid} eta_T={eta_T:.3f} td={td:.1f} eta_R={eta_R:.3f} CE={ce:.3f}")

mfe = min(coupling_eff) if coupling_eff else 0.0
meets = bool(mfe >= 0.25)

log(f"\n{'='*60}")
log(f"MFE = {mfe:.4f} ({mfe*100:.2f}%)")
log(f"Meets >= 25% target: {meets}")
log(f"Coupling eff: {[f'{v:.3f}' for v in coupling_eff]}")
log(f"{'='*60}")

mfe_out = {
    "mfe_value": mfe,
    "coupling_efficiency_per_angle": [float(c) for c in coupling_eff],
    "fov_angles":        [float(a) for a in fov],
    "zone_assignments":  zone_assign,
    "meets_target":      meets,
}
with open("/workspace/photonics/mfe_result.json", "w") as f:
    json.dump(mfe_out, f, indent=2)
log("Wrote mfe_result.json")
LOG.close()
print("SIMULATION COMPLETE", flush=True)
