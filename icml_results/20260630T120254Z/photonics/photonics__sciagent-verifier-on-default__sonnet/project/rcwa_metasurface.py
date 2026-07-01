"""
Rigorous S4 RCWA simulation of TiO2/N-BK7 three-zone metasurface in-coupler
Reproducing Xiong et al. 2025 (Optical Materials Express), lambda=532 nm.

Structure per zone: grating period d=453 nm, nano-beam + nano-pillar,
height h=250 nm on N-BK7 substrate.

Simulation strategy (Supplement S1 reciprocity):
  - Diffraction sim: light from air, sweep -10 to +10 deg, TE, get +1 order in glass
  - Reflection sim: light from glass, sweep 41.5 to 62.5 deg, TE, get 0th order reflection

Grid-scan over Ly (unit cell y-size) and beam-pillar separation to find
geometry that best matches per-zone efficiency targets.

Author: SciAgent auto-generated for Xiong 2025 reproduction
"""

import S4
import numpy as np
import json
import os
import sys
import traceback
from itertools import product

# ── Physical constants ────────────────────────────────────────────────────────
LAM = 532e-9          # wavelength [m] (not used directly; S4 works in "units of period")
LAM_NM = 532.0        # nm

# ── Materials at 532 nm ───────────────────────────────────────────────────────
N_TIO2   = 2.37
N_NBK7   = 1.5195
N_AIR    = 1.0

EPS_TIO2 = N_TIO2**2          # 5.6169
EPS_NBK7 = N_NBK7**2          # 2.3089
EPS_AIR  = 1.0

# ── Fixed geometry ────────────────────────────────────────────────────────────
D_NM     = 453.0      # grating period x [nm]
H_NM     = 250.0      # TiO2 layer height [nm]
LAM_OVER_D = LAM_NM / D_NM   # ≈ 1.1744

# S4 works in units of the lattice period → we normalise everything by D_NM
# frequency = 1/lambda_in_units_of_period = D_NM/LAM_NM
FREQ = D_NM / LAM_NM          # ≈ 0.8521 (S4 frequency unit: c/a)

# ── Per-zone beam/pillar geometry (Table 1) ───────────────────────────────────
ZONES = {
    1: {"wb": 110.0, "dp": 100.0, "pillar_w": 100.0},   # full circle → width=dp
    2: {"wb": 110.0, "dp": 170.0, "pillar_w": 156.5},   # partial → clipped
    3: {"wb": 100.0, "dp": 196.0, "pillar_w": 160.5},   # partial → clipped
}

# ── Angle sweeps ──────────────────────────────────────────────────────────────
# Diffraction: light from air
ANGLES_AIR_DEG = np.arange(-10, 11, 2).tolist()   # -10,-8,...,+10 (11 pts)
# Reflection: light from glass  
ANGLES_GLASS_DEG = [41.5, 46.4, 49.5, 52.1, 54.4, 56.5, 58.4, 60.3, 62.5]

# ── Grid scan parameters ──────────────────────────────────────────────────────
LY_SCAN = [300.0, 400.0, 453.0, 500.0, 600.0, 700.0, 800.0]
SEP_SCAN = [0.0, 50.0, 100.0, 150.0, 200.0]   # beam-edge to pillar-centre offset

# ── S4 accuracy ──────────────────────────────────────────────────────────────
NUM_BASIS = 25   # Fourier orders (at least 20; 25 for better accuracy)

# ── Per-zone efficiency targets ───────────────────────────────────────────────
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
log("Xiong 2025 TiO2/N-BK7 metasurface RCWA reproduction")
log(f"lambda={LAM_NM} nm, d={D_NM} nm, h={H_NM} nm, NumBasis={NUM_BASIS}")
log(f"S4 FREQ unit = {FREQ:.6f}")
log("="*70)


# ─────────────────────────────────────────────────────────────────────────────
def make_simulation(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm,
                    beam_x_center, pillar_x_center):
    """
    Create and return a configured S4 simulation object.
    Lattice: d_nm × Ly_nm, all dimensions normalised by D_NM.
    Beam: rectangle centered at beam_x_center (normalised), full height in y.
    Pillar: rectangle of width pillar_w_nm, height min(pillar_d_nm, Ly_nm).
    """
    # Normalise to S4 lattice units (x unit = D_NM, y unit = Ly_nm)
    lx = 1.0                     # always 1 in S4 units (= D_NM)
    ly = Ly_nm / D_NM            # S4 y lattice length in units of D_NM

    S = S4.New(Lattice=((lx, 0), (0, ly)), NumBasis=NUM_BASIS)

    # Materials
    S.AddMaterial(Name="Air",   Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2",  Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7",  Epsilon=EPS_NBK7)

    # Layer stack (from top = where light enters for diffraction sim)
    S.AddLayer(Name="AirTop",   Thickness=0,              Material="Air")
    S.AddLayer(Name="TiO2Layer",Thickness=H_NM / D_NM,   Material="Air")   # background air, features below
    S.AddLayer(Name="Substrate",Thickness=0,              Material="NBK7")

    # ── Pattern TiO2 layer ────────────────────────────────────────────────────
    # S4 rectangle: (centerX, centerY, halfWidthX, halfWidthY) in lattice units
    # NOTE: S4 uses lattice coordinates: x in [−0.5, 0.5], y in [−ly/2, ly/2]

    # Beam: full y-extent, width wb_nm
    bx  = beam_x_center / D_NM          # x-center in S4 units
    bhy = ly / 2.0                       # half-height in y (full cell)
    bhx = (wb_nm / 2.0) / D_NM          # half-width in x

    S.SetRegionRectangle(
        Layer="TiO2Layer",
        Material="TiO2",
        Center=(bx, 0),
        Angle=0,
        Halfwidths=(bhx, bhy),
    )

    # Pillar: rectangle approximating circular/clipped pillar
    px  = pillar_x_center / D_NM
    phx = (pillar_w_nm / 2.0) / D_NM
    phy = (min(pillar_d_nm, Ly_nm) / 2.0) / D_NM

    # Only add pillar if it doesn't fully overlap with the beam
    if abs(px - bx) * D_NM > 1.0:  # centers separated by > 1 nm
        S.SetRegionRectangle(
            Layer="TiO2Layer",
            Material="TiO2",
            Center=(px, 0),
            Angle=0,
            Halfwidths=(phx, phy),
        )

    S.SetFrequency(FREQ)
    return S


def get_diffraction_efficiency(S, theta_air_deg, m_order=1):
    """
    Simulate light from air at theta_air_deg (TE), get +m_order transmission into NBK7.
    Returns (eta_T, theta_diffracted_deg) or (0, None) if order is evanescent.
    """
    theta_rad = np.radians(theta_air_deg)

    # Check if +1 order is propagating in glass
    # Grating equation: n_glass * sin(theta_d) = n_air * sin(theta_i) + m * lambda/d
    # lambda/d = LAM_OVER_D ≈ 1.1744
    sin_d = N_AIR * np.sin(theta_rad) + m_order * LAM_OVER_D
    if abs(sin_d) >= N_NBK7:
        return 0.0, None   # evanescent

    theta_diff_deg = np.degrees(np.arcsin(sin_d / N_NBK7))

    # Set excitation: TE = s-polarization (sAmplitude=1, pAmplitude=0)
    # theta = polar angle from z-axis, phi = azimuthal angle
    S.SetExcitationPlanewave(
        IncidenceAngles=(theta_air_deg, 0),   # (polar, azimuthal) degrees
        sAmplitude=1.0,
        pAmplitude=0.0,
        Order=0,
    )

    # Get incident power (from AirTop)
    inc_forward, inc_backward = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc = abs(inc_forward)

    if P_inc < 1e-20:
        return 0.0, theta_diff_deg

    # Get transmitted power by order into substrate
    # GetPoyntingFluxByOrder: returns list of (forward, backward) per order
    orders = S.GetPoyntingFluxByOrder(Layer="Substrate", zOffset=0)

    # orders is indexed: order index maps to (nx, ny) reciprocal lattice vectors
    # We need to find order (m_order, 0) in the list
    basis = S.GetBasisSet()   # list of (nx, ny) pairs
    eta_T = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == m_order and int(round(ny)) == 0:
            fwd, bwd = orders[i]
            eta_T = abs(fwd) / P_inc
            break

    # Clamp to physical range
    eta_T = max(0.0, min(1.0, eta_T))
    return eta_T, theta_diff_deg


def get_reflection_efficiency(S, theta_glass_deg, m_order=0):
    """
    Simulate light from within NBK7 at theta_glass_deg (TE),
    get m_order=0 reflection back into glass.
    
    For this, we flip the stack: excite from Substrate side.
    Actually in S4, we excite from the top (AirTop side).
    For glass-side excitation we use SetExcitationPlanewave from below.
    
    S4 convention: positive z is from AirTop down to Substrate.
    To simulate light coming UP from glass, we excite from Substrate
    using the backward direction, OR we rebuild the stack inverted.
    
    The cleaner approach: rebuild stack with NBK7 on top, Air on bottom.
    """
    # We need to rebuild the simulation with inverted stack
    # This is handled in run_reflection_simulation which creates the correct stack
    theta_rad = np.radians(theta_glass_deg)

    S.SetExcitationPlanewave(
        IncidenceAngles=(theta_glass_deg, 0),
        sAmplitude=1.0,
        pAmplitude=0.0,
        Order=0,
    )

    inc_fwd, inc_bwd = S.GetPoyntingFlux(Layer="AirTop", zOffset=0)
    P_inc = abs(inc_fwd)

    if P_inc < 1e-20:
        return 0.0

    # Zeroth order reflection: go back into the top material (NBK7 in inverted stack)
    orders = S.GetPoyntingFluxByOrder(Layer="AirTop", zOffset=0)
    basis = S.GetBasisSet()

    eta_R = 0.0
    for i, (nx, ny) in enumerate(basis):
        if int(round(nx)) == m_order and int(round(ny)) == 0:
            fwd, bwd = orders[i]
            eta_R = abs(bwd) / P_inc   # backward = reflected
            break

    eta_R = max(0.0, min(1.0, eta_R))
    return eta_R


def make_simulation_inverted(Ly_nm, wb_nm, pillar_w_nm, pillar_d_nm,
                              beam_x_center, pillar_x_center):
    """
    Inverted stack for glass-side excitation (reflection simulation).
    Stack: NBK7 superstrate | TiO2 features | Air substrate
    """
    lx = 1.0
    ly = Ly_nm / D_NM

    S = S4.New(Lattice=((lx, 0), (0, ly)), NumBasis=NUM_BASIS)

    S.AddMaterial(Name="Air",   Epsilon=EPS_AIR)
    S.AddMaterial(Name="TiO2",  Epsilon=EPS_TIO2)
    S.AddMaterial(Name="NBK7",  Epsilon=EPS_NBK7)

    # Inverted stack: NBK7 on top (superstrate), Air on bottom
    S.AddLayer(Name="AirTop",    Thickness=0,             Material="NBK7")   # glass superstrate
    S.AddLayer(Name="TiO2Layer", Thickness=H_NM / D_NM,  Material="Air")    # patterned layer
    S.AddLayer(Name="Substrate", Thickness=0,             Material="Air")    # air substrate

    # Same patterning
    bx  = beam_x_center / D_NM
    bhy = ly / 2.0
    bhx = (wb_nm / 2.0) / D_NM

    S.SetRegionRectangle(
        Layer="TiO2Layer", Material="TiO2",
        Center=(bx, 0), Angle=0, Halfwidths=(bhx, bhy),
    )

    px  = pillar_x_center / D_NM
    phx = (pillar_w_nm / 2.0) / D_NM
    phy = (min(pillar_d_nm, Ly_nm) / 2.0) / D_NM

    if abs(px - bx) * D_NM > 1.0:
        S.SetRegionRectangle(
            Layer="TiO2Layer", Material="TiO2",
            Center=(px, 0), Angle=0, Halfwidths=(phx, phy),
        )

    S.SetFrequency(FREQ)
    return S


# ─────────────────────────────────────────────────────────────────────────────
def run_zone_simulation(zone_id, Ly_nm, sep_nm):
    """
    Run complete simulation for one zone with given (Ly_nm, sep_nm).
    sep_nm = beam-edge to pillar-centre offset (positive = beam right of center,
             pillar at d/2 from beam edge).

    Returns dict with eta_T list and eta_R list.
    """
    z = ZONES[zone_id]
    wb     = z["wb"]
    dp     = z["dp"]
    pw     = z["pillar_w"]   # effective pillar width (clipped)

    # Beam centred at x=0 (left edge of cell), pillar at beam_edge + sep
    # Beam occupies [-wb/2, +wb/2] centered at 0
    beam_x_center   = 0.0                        # beam at cell centre
    pillar_x_center = wb / 2.0 + sep_nm          # beam right-edge + sep

    # Wrap pillar into cell [-d/2, +d/2] if needed
    while pillar_x_center > D_NM / 2:
        pillar_x_center -= D_NM

    eta_T_list = []
    theta_diff_list = []

    # ── Diffraction simulation (air → glass, +1 order) ────────────────────
    for theta_a in ANGLES_AIR_DEG:
        try:
            S = make_simulation(Ly_nm, wb, pw, dp, beam_x_center, pillar_x_center)
            eta_T, theta_d = get_diffraction_efficiency(S, theta_a, m_order=1)
            eta_T_list.append(float(eta_T))
            theta_diff_list.append(float(theta_d) if theta_d is not None else None)
        except Exception as e:
            log(f"  Zone{zone_id} diff sim FAILED theta_a={theta_a}: {e}")
            eta_T_list.append(0.0)
            theta_diff_list.append(None)

    # ── Reflection simulation (glass → glass, 0th order) ──────────────────
    eta_R_list = []
    for theta_g in ANGLES_GLASS_DEG:
        try:
            S_inv = make_simulation_inverted(Ly_nm, wb, pw, dp,
                                             beam_x_center, pillar_x_center)
            eta_R = get_reflection_efficiency(S_inv, theta_g, m_order=0)
            eta_R_list.append(float(eta_R))
        except Exception as e:
            log(f"  Zone{zone_id} refl sim FAILED theta_g={theta_g}: {e}")
            eta_R_list.append(0.0)

    return {
        "eta_T":      eta_T_list,
        "theta_diff": theta_diff_list,
        "eta_R":      eta_R_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
def merit(zone_id, res):
    """
    Score a (Ly, sep) combination for a given zone.
    Lower = better. We use RMS deviation from targets.
    """
    t = TARGETS[zone_id]
    eta_T = np.array(res["eta_T"])
    eta_R = np.array(res["eta_R"])

    # Mean of non-zero T efficiency
    mean_T = np.mean(eta_T[eta_T > 0]) if np.any(eta_T > 0) else 0.0
    mean_R = np.mean(eta_R) if len(eta_R) > 0 else 0.0

    score = (mean_T - t["eta_T_center"])**2 + (mean_R - t["eta_R_center"])**2
    return score, mean_T, mean_R


# ─────────────────────────────────────────────────────────────────────────────
def grid_scan_zone(zone_id):
    """
    Scan Ly and sep for a zone. Return best geometry + efficiency curves.
    """
    log(f"\n{'='*60}")
    log(f"Zone {zone_id} grid scan: {len(LY_SCAN)*len(SEP_SCAN)} combinations")
    log(f"{'='*60}")
    z = ZONES[zone_id]
    log(f"  wb={z['wb']} nm, dp={z['dp']} nm, pillar_w={z['pillar_w']} nm")

    best_score  = 1e9
    best_Ly     = None
    best_sep    = None
    best_res    = None

    for Ly, sep in product(LY_SCAN, SEP_SCAN):
        try:
            res   = run_zone_simulation(zone_id, Ly, sep)
            sc, mT, mR = merit(zone_id, res)
            log(f"  Ly={Ly:5.0f} sep={sep:4.0f}: mean_T={mT:.3f} mean_R={mR:.3f} score={sc:.5f}")
            if sc < best_score:
                best_score = sc
                best_Ly    = Ly
                best_sep   = sep
                best_res   = res
        except Exception as e:
            log(f"  Ly={Ly} sep={sep}: EXCEPTION {e}")

    log(f"\n  Zone {zone_id} BEST: Ly={best_Ly} nm, sep={best_sep} nm, score={best_score:.5f}")
    if best_res:
        log(f"  eta_T = {[f'{v:.3f}' for v in best_res['eta_T']]}")
        log(f"  eta_R = {[f'{v:.3f}' for v in best_res['eta_R']]}")

    return best_Ly, best_sep, best_res


# ─────────────────────────────────────────────────────────────────────────────
def compute_mfe(zone_results):
    """
    Compute minimum field efficiency across the FOV.

    FOV assignment:
      Zone 1: theta_air in [-10, -3.33] deg
      Zone 2: theta_air in (-3.33, +3.33) deg
      Zone 3: theta_air in [+3.33, +10] deg

    For each FOV angle:
      1. Look up eta_T(theta) for that zone
      2. Use grating equation to get theta_glass (diffraction angle)
      3. Interpolate eta_R at theta_glass for that zone
      4. coupling_eff = eta_T * (eta_R + (1-eta_R) * eta_T)
         (first interaction: transmit + reflect, second interaction: transmit again)

    MFE = min(coupling_eff over all theta_air)
    """
    fov_angles = ANGLES_AIR_DEG  # -10 to +10 step 2
    boundaries = (-3.33, 3.33)   # zone 1/2 and 2/3 boundaries

    zone_assign = []
    for ta in fov_angles:
        if ta <= boundaries[0]:
            zone_assign.append(1)
        elif ta <= boundaries[1]:
            zone_assign.append(2)
        else:
            zone_assign.append(3)

    coupling_eff = []

    for i, (ta, zid) in enumerate(zip(fov_angles, zone_assign)):
        res = zone_results[zid]

        # eta_T at this angle (direct lookup — same index order)
        eta_T_idx = ANGLES_AIR_DEG.index(ta)
        eta_T = res["eta_T"][eta_T_idx]
        theta_d = res["theta_diff"][eta_T_idx]

        if theta_d is None or eta_T < 1e-6:
            coupling_eff.append(0.0)
            continue

        # Interpolate eta_R at theta_glass = theta_d (in glass-side angles)
        glass_angles = np.array(ANGLES_GLASS_DEG)
        eta_R_arr    = np.array(res["eta_R"])
        # theta_d should fall within 41.5 to 62.5 deg
        if theta_d < glass_angles[0]:
            eta_R = eta_R_arr[0]
        elif theta_d > glass_angles[-1]:
            eta_R = eta_R_arr[-1]
        else:
            eta_R = float(np.interp(theta_d, glass_angles, eta_R_arr))

        # Goodsell 2023 two-interaction formula
        ce = eta_T * (eta_R + (1.0 - eta_R) * eta_T)
        coupling_eff.append(ce)

    mfe = min(coupling_eff) if coupling_eff else 0.0

    return {
        "mfe_value":                  mfe,
        "coupling_efficiency_per_angle": [float(c) for c in coupling_eff],
        "fov_angles":                 [float(a) for a in fov_angles],
        "zone_assignments":           zone_assign,
        "meets_target":               bool(mfe >= 0.25),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
log("\nStarting zone simulations...")
zone_results  = {}
zone_best_geo = {}

for zid in [1, 2, 3]:
    best_Ly, best_sep, best_res = grid_scan_zone(zid)
    zone_results[zid]  = best_res
    zone_best_geo[zid] = {"Ly_nm": best_Ly, "sep_nm": best_sep}

    z = ZONES[zid]
    out = {
        "zone":          zid,
        "geometry": {
            "d_nm":        D_NM,
            "h_nm":        H_NM,
            "Ly_nm":       best_Ly,
            "wb_nm":       z["wb"],
            "dp_nm":       z["dp"],
            "pillar_w_nm": z["pillar_w"],
            "sep_nm":      best_sep,
        },
        "angles_air":    ANGLES_AIR_DEG,
        "eta_T":         best_res["eta_T"] if best_res else [],
        "theta_diff":    best_res["theta_diff"] if best_res else [],
        "angles_glass":  ANGLES_GLASS_DEG,
        "eta_R":         best_res["eta_R"] if best_res else [],
    }
    fname = f"/workspace/photonics/zone{zid}_results.json"
    with open(fname, "w") as f:
        json.dump(out, f, indent=2)
    log(f"Wrote {fname}")

# ── MFE ──────────────────────────────────────────────────────────────────────
log("\nComputing MFE...")
mfe_out = compute_mfe(zone_results)

log(f"\n{'='*60}")
log(f"RESULTS SUMMARY")
log(f"{'='*60}")
for zid in [1, 2, 3]:
    geo = zone_best_geo[zid]
    log(f"Zone {zid}: Ly={geo['Ly_nm']} nm, sep={geo['sep_nm']} nm")
    if zone_results[zid]:
        log(f"  eta_T = {[f'{v:.3f}' for v in zone_results[zid]['eta_T']]}")
        log(f"  eta_R = {[f'{v:.3f}' for v in zone_results[zid]['eta_R']]}")
log(f"\nMFE = {mfe_out['mfe_value']:.4f} ({mfe_out['mfe_value']*100:.2f}%)")
log(f"Meets >= 25% target: {mfe_out['meets_target']}")
log(f"Coupling eff per angle: {[f'{v:.3f}' for v in mfe_out['coupling_efficiency_per_angle']]}")

with open("/workspace/photonics/mfe_result.json", "w") as f:
    json.dump(mfe_out, f, indent=2)
log("Wrote /workspace/photonics/mfe_result.json")

LOG.close()
print("SIMULATION COMPLETE", flush=True)
