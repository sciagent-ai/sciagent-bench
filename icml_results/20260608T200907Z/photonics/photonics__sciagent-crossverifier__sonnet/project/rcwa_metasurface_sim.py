"""
S4 RCWA simulation — TiO2/N-BK7 metasurface waveguide in-coupler at 532 nm
Based on Xiong et al., Opt. Mat. Express 2025.

Stack (glass on top = incident medium):
  GlassTop  (N-BK7, n=1.5195)  — semi-infinite, source inside
  Grating   (TiO2 in Air, h=250 nm)
  AirBot    (Air, n=1.0)       — semi-infinite

Unit cell: d_x=453 nm  x  y_period (per-zone variable)
  nano-beam : rectangle, width=bar_w (x), full y extent
  nano-pillar: rectangle approx width=min(pil_d,0.95*d) x min(pil_d,0.95*yp)
               centred at (sep, 0) from bar centre

Excitation: TE plane wave (s-pol), angle theta_int inside glass.
Target order: m=-1 in S4 = paper's "T+1" (first diffraction order into air).
R0: m=0 backward in glass (zeroth-order reflection).
"""

import S4
import numpy as np
import json, os, sys
from scipy.optimize import minimize
from scipy.interpolate import interp1d

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ── Physical constants ─────────────────────────────────────────────────
LAMBDA_NM = 532.0
N_GLASS   = 1.5195
N_TIO2    = complex(2.35, 0.0005)
N_AIR     = 1.0
D_NM      = 453.0          # x-period
H_NM      = 250.0          # TiO2 thickness
NUM_BASIS = 40             # enough orders for 2-D cell

THETAS_INT = np.arange(41.5, 62.51, 1.0)   # internal angles in glass

ZONE_TARGETS = {
    1: {'T1': 0.96, 'R0': 0.04},
    2: {'T1': 0.54, 'R0': 0.46},
    3: {'T1': 0.27, 'R0': 0.73},
}

# Paper geometry starting points (nm)
ZONE_INIT = {
    1: {'bar_w': 110.0, 'pil_d': 100.0, 'sep': 160.0, 'yp': 177.0},
    2: {'bar_w': 110.0, 'pil_d': 170.0, 'sep': 160.0, 'yp': 180.0},
    3: {'bar_w': 100.0, 'pil_d': 196.0, 'sep': 140.0, 'yp': 144.0},
}

OUTPUT_DIR = '/workspace/rcwa_results'
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── S4 simulation ──────────────────────────────────────────────────────
def run_s4_one(bar_w, pil_d, sep, yp, theta_int_deg):
    """
    Single S4 run.  Returns (T1, R0) normalised to incident flux.
      T1 = m=-1 order forward into AirBot  (paper's T+1)
      R0 = m= 0 order backward in GlassTop (zeroth-order reflection)
    Normalization: incident = m=0 order forward in GlassTop.
    """
    lam = LAMBDA_NM
    dx  = D_NM / lam
    dy  = float(yp) / lam
    h   = H_NM / lam

    # clamp pillar to fit inside cell with a small margin
    bw = float(bar_w) / lam
    pd_x = min(float(pil_d), 0.95 * D_NM) / lam
    pd_y = min(float(pil_d), 0.95 * float(yp)) / lam

    # pillar x-centre relative to bar (bar at x=0 in [-dx/2, dx/2] cell)
    # sep is distance from bar centre to pillar centre
    pil_cx = float(sep) / lam
    # wrap into cell
    while pil_cx >  dx / 2: pil_cx -= dx
    while pil_cx < -dx / 2: pil_cx += dx

    S = S4.New(Lattice=((dx, 0), (0, dy)), NumBasis=NUM_BASIS)

    S.SetMaterial('Air',   N_AIR**2)
    S.SetMaterial('Glass', N_GLASS**2)
    S.SetMaterial('TiO2',  N_TIO2**2)

    # Glass on top (incident medium), Air on bottom (transmission)
    S.AddLayer('GlassTop', 0, 'Glass')
    S.AddLayer('Grating',  h, 'Air')
    S.AddLayer('AirBot',   0, 'Air')

    # nano-beam: full y extent, width bar_w in x
    S.SetRegionRectangle('Grating', 'TiO2',
                         (0.0, 0.0), 0, (bw/2, dy/2))

    # nano-pillar: rectangle approx of pillar
    S.SetRegionRectangle('Grating', 'TiO2',
                         (pil_cx, 0.0), 0, (pd_x/2, pd_y/2))

    S.SetFrequency(1.0)
    # TE = s-pol (E along y).  (theta, phi) in degrees; phi=0 → grating in x.
    S.SetExcitationPlanewave((float(theta_int_deg), 0.0), 1.0, 0.0)

    # Build order index map once  (GetBasisSet returns list of (mx,my))
    basis = S.GetBasisSet()
    idx_00  = next(i for i,(mx,my) in enumerate(basis) if mx== 0 and my==0)
    # m=-1 in S4 = paper's T+1 diffraction into air
    idx_m1  = next((i for i,(mx,my) in enumerate(basis) if mx==-1 and my==0), None)

    po_top = S.GetPowerFluxByOrder('GlassTop')
    po_bot = S.GetPowerFluxByOrder('AirBot')

    # Incident power = m=0 forward in GlassTop
    inc = abs(po_top[idx_00][0])
    if inc < 1e-12:
        return 0.0, 0.0

    T1 = abs(po_bot[idx_m1][0]) / inc if idx_m1 is not None else 0.0
    R0 = abs(po_top[idx_00][1]) / inc

    return float(T1), float(R0)


def sweep_angles(bar_w, pil_d, sep, yp, thetas=THETAS_INT):
    T1s, R0s = [], []
    for th in thetas:
        t1, r0 = run_s4_one(bar_w, pil_d, sep, yp, th)
        T1s.append(t1)
        R0s.append(r0)
    return np.array(T1s), np.array(R0s)


# ── Merit / optimisation ───────────────────────────────────────────────
def merit(params, zone_id, weights=None):
    bar_w, pil_d, sep, yp = params
    # hard bounds check — penalty if out of range
    if bar_w < 30 or bar_w > 220:   return 1e6
    if pil_d < 30 or pil_d > 240:   return 1e6
    if sep   < 40 or sep   > 320:   return 1e6
    if yp    < 80 or yp    > 320:   return 1e6
    tgt_T1 = ZONE_TARGETS[zone_id]['T1']
    tgt_R0 = ZONE_TARGETS[zone_id]['R0']
    T1s, R0s = sweep_angles(bar_w, pil_d, sep, yp)
    err = np.mean((T1s - tgt_T1)**2 + (R0s - tgt_R0)**2)
    return err


def optimise_zone(zone_id):
    print(f"\n{'='*60}")
    print(f"Zone {zone_id}  |  target T+1={ZONE_TARGETS[zone_id]['T1']:.2f}  R0={ZONE_TARGETS[zone_id]['R0']:.2f}")
    ini = ZONE_INIT[zone_id]
    x0  = np.array([ini['bar_w'], ini['pil_d'], ini['sep'], ini['yp']])

    T1i, R0i = sweep_angles(*x0)
    m0 = merit(x0, zone_id)
    print(f"  Paper geometry merit={m0:.5f}  <T+1>={np.mean(T1i)*100:.1f}%  <R0>={np.mean(R0i)*100:.1f}%")

    # Nelder-Mead with adaptive step sizes — fast near good starting point
    opt = minimize(
        merit,
        x0,
        args=(zone_id,),
        method='Nelder-Mead',
        options={
            'maxiter': 2000,
            'xatol':   2.0,    # nm tolerance
            'fatol':   1e-4,
            'adaptive': True,
            'disp':     True,
        }
    )

    bar_w_o, pil_d_o, sep_o, yp_o = opt.x
    T1o, R0o = sweep_angles(bar_w_o, pil_d_o, sep_o, yp_o)
    print(f"  Optimised merit={opt.fun:.5f}  <T+1>={np.mean(T1o)*100:.1f}%  <R0>={np.mean(R0o)*100:.1f}%")
    print(f"  bar_w={bar_w_o:.1f}  pil_d={pil_d_o:.1f}  sep={sep_o:.1f}  yp={yp_o:.1f} nm")

    return {
        'zone':         zone_id,
        'bar_w':        float(bar_w_o),
        'pil_d':        float(pil_d_o),
        'sep':          float(sep_o),
        'yp':           float(yp_o),
        'merit':        float(opt.fun),
        'T1_vs_angle':  T1o.tolist(),
        'R0_vs_angle':  R0o.tolist(),
        'thetas_int':   THETAS_INT.tolist(),
        # also store paper-geometry for reference
        'T1_paper':     T1i.tolist(),
        'R0_paper':     R0i.tolist(),
    }


# ── Grating equation: internal → external angle ───────────────────────
def int_to_xfov(theta_int_deg, m_paper=1):
    """
    n_glass * sin(theta_int) = sin(theta_ext) + m * lambda/d  (m=+1 in paper)
    => sin(theta_ext) = n_glass*sin(theta_int) - lambda/d
    """
    sin_ext = N_GLASS * np.sin(np.radians(theta_int_deg)) - LAMBDA_NM / D_NM
    if abs(sin_ext) > 1.0:
        return np.nan
    return float(np.degrees(np.arcsin(sin_ext)))


# ── MFE computation ───────────────────────────────────────────────────
def compute_mfe(results):
    """
    Simple coupling model for a 3-zone waveguide coupler.
    For each XFOV angle, one zone provides T+1 and R0.
    Coupling eff = T+1 * R0  (in-coupler T * secondary bounce R).
    MFE = min over all angles.
    Zones partitioned by XFOV: zone1 [-10,-4], zone2 [-3,+3], zone3 [+4,+10].
    """
    xfov_angles = np.arange(-10, 11, 1.0)

    # Build interpolators per zone
    zone_T1 = {}
    zone_R0 = {}
    for zid in [1, 2, 3]:
        r = results[zid]
        thetas = np.array(r['thetas_int'])
        xfov_mapped = np.array([int_to_xfov(th) for th in thetas])
        valid = ~np.isnan(xfov_mapped)
        xv = xfov_mapped[valid]
        T1v = np.array(r['T1_vs_angle'])[valid]
        R0v = np.array(r['R0_vs_angle'])[valid]
        if len(xv) >= 2:
            zone_T1[zid] = interp1d(xv, T1v, bounds_error=False, fill_value=(T1v[0], T1v[-1]))
            zone_R0[zid] = interp1d(xv, R0v, bounds_error=False, fill_value=(R0v[0], R0v[-1]))
        else:
            zone_T1[zid] = lambda x, v=np.mean(T1v): v
            zone_R0[zid] = lambda x, v=np.mean(R0v): v

    def get_zone(xfov):
        if xfov <= -4:   return 1
        elif xfov <= 3:  return 2
        else:            return 3

    coupling = []
    for xfov in xfov_angles:
        z = get_zone(xfov)
        T1 = float(np.clip(zone_T1[z](xfov), 0, 1))
        R0 = float(np.clip(zone_R0[z](xfov), 0, 1))
        coupling.append(T1 * R0)

    coupling = np.array(coupling)
    MFE = float(np.min(coupling))
    return xfov_angles, coupling, MFE


# ── Plotting ───────────────────────────────────────────────────────────
def make_fig1(results):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for idx, zid in enumerate([1, 2, 3]):
        r   = results[zid]
        ax  = axes[idx]
        th  = np.array(r['thetas_int'])
        T1  = np.array(r['T1_vs_angle'])
        R0  = np.array(r['R0_vs_angle'])
        T1p = np.array(r['T1_paper'])
        R0p = np.array(r['R0_paper'])

        ax.plot(th, T1*100,  'r-o', ms=4, lw=1.5, label='T+1 (opt)')
        ax.plot(th, R0*100,  'b-s', ms=4, lw=1.5, label='R0  (opt)')
        ax.plot(th, (T1+R0)*100, 'k--', ms=3, lw=1, label='T+1+R0')
        ax.plot(th, T1p*100, 'r:',  ms=3, lw=1, alpha=0.5, label='T+1 (paper geom)')
        ax.plot(th, R0p*100, 'b:',  ms=3, lw=1, alpha=0.5, label='R0  (paper geom)')
        ax.axhline(ZONE_TARGETS[zid]['T1']*100, color='r', ls='--', alpha=0.35)
        ax.axhline(ZONE_TARGETS[zid]['R0']*100, color='b', ls='--', alpha=0.35)
        ax.set_title(f"Zone {zid}\nbw={r['bar_w']:.0f}  pd={r['pil_d']:.0f}"
                     f"  sep={r['sep']:.0f}  yp={r['yp']:.0f} nm", fontsize=9)
        ax.set_xlabel('Internal angle θ (deg)')
        ax.set_ylabel('Efficiency (%)')
        ax.set_ylim(-5, 115)
        ax.legend(fontsize=6.5)
        ax.grid(True, alpha=0.3)
    fig.suptitle('S4 RCWA: TiO2/N-BK7 Metasurface In-Coupler — Efficiency vs Internal Angle\n'
                 '(dashed targets from paper Fig 2e)', fontsize=11)
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, 'fig1_efficiency_vs_angle.png')
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved {out}")


def make_fig2(xfov, coupling, MFE):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xfov, coupling*100, 'g-o', ms=5, lw=2, label='Coupling eff = T+1·R0')
    ax.axhline(25.3, color='r', ls='--', lw=1.5, label='Paper MFE = 25.3%')
    ax.axhline(MFE*100, color='g', ls=':', lw=1.5, label=f'Computed MFE = {MFE*100:.1f}%')
    ax.fill_between(xfov, 0, coupling*100, alpha=0.15, color='green')
    ax.set_xlabel('XFOV angle (deg)')
    ax.set_ylabel('Coupling efficiency (%)')
    ax.set_title(f'Waveguide Coupler — Coupling Efficiency vs XFOV\nMFE = {MFE*100:.1f}%'
                 f'  ({"≥25.3% ✓" if MFE>=0.253 else "<25.3% ✗ — below paper target"})')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(0, 100)
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, 'fig2_coupling_vs_xfov.png')
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved {out}")


def make_fig3(results):
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.axis('off')
    cols = ['Zone', 'bar_w (nm)', 'pil_d (nm)', 'sep (nm)', 'yp (nm)',
            'Mean T+1 (%)', 'Mean R0 (%)', 'Target T+1 (%)', 'Target R0 (%)']
    rows = []
    for zid in [1, 2, 3]:
        r = results[zid]
        T1m = np.mean(r['T1_vs_angle'])*100
        R0m = np.mean(r['R0_vs_angle'])*100
        rows.append([
            str(zid),
            f"{r['bar_w']:.1f}", f"{r['pil_d']:.1f}",
            f"{r['sep']:.1f}",   f"{r['yp']:.1f}",
            f"{T1m:.1f}", f"{R0m:.1f}",
            f"{ZONE_TARGETS[zid]['T1']*100:.0f}",
            f"{ZONE_TARGETS[zid]['R0']*100:.0f}",
        ])
    tbl = ax.table(cellText=rows, colLabels=cols, loc='center', cellLoc='center')
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.1, 2.0)
    ax.set_title('Optimised Geometry — S4 RCWA Results', pad=15, fontsize=11)
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, 'fig3_geometry_table.png')
    plt.savefig(out, dpi=150)
    plt.close()
    print(f"Saved {out}")


# ── Main ───────────────────────────────────────────────────────────────
def main():
    print("="*60)
    print("S4 RCWA — TiO2/N-BK7 Metasurface In-Coupler at 532 nm")
    print(f"lambda={LAMBDA_NM} nm, d={D_NM} nm, h={H_NM} nm")
    print(f"Angle sweep: {THETAS_INT[0]}–{THETAS_INT[-1]}° ({len(THETAS_INT)} pts)")
    print("="*60)

    results = {}
    for zid in [1, 2, 3]:
        results[zid] = optimise_zone(zid)

    # ── Save JSON ──────────────────────────────────────────────────────
    def to_native(v):
        if isinstance(v, np.ndarray): return v.tolist()
        if isinstance(v, (np.floating, np.integer)): return float(v)
        return v

    ser = {str(z): {k: to_native(v) for k,v in r.items()} for z,r in results.items()}
    with open(os.path.join(OUTPUT_DIR, 'results.json'), 'w') as f:
        json.dump(ser, f, indent=2)
    print(f"\nSaved results.json")

    # ── MFE ───────────────────────────────────────────────────────────
    xfov, coupling, MFE = compute_mfe(results)
    print(f"\nMFE = {MFE*100:.2f}%  ({'✓ ≥25.3%' if MFE>=0.253 else '✗ below paper 25.3%'})")

    # ── Plots ─────────────────────────────────────────────────────────
    make_fig1(results)
    make_fig2(xfov, coupling, MFE)
    make_fig3(results)

    # ── Text report ────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SUMMARY REPORT")
    print("="*60)
    for zid in [1, 2, 3]:
        r = results[zid]
        th  = np.array(r['thetas_int'])
        T1  = np.array(r['T1_vs_angle'])
        R0  = np.array(r['R0_vs_angle'])
        xfov_z = np.array([int_to_xfov(t) for t in th])
        print(f"\nZone {zid}: bar_w={r['bar_w']:.1f} nm, pil_d={r['pil_d']:.1f} nm, "
              f"sep={r['sep']:.1f} nm, yp={r['yp']:.1f} nm")
        print(f"  merit={r['merit']:.5f}  <T+1>={np.mean(T1)*100:.1f}%  <R0>={np.mean(R0)*100:.1f}%")
        for xfov_key in [-10, 0, 10]:
            dists = np.abs(xfov_z - xfov_key)
            dists[np.isnan(dists)] = 1e9
            idx = int(np.argmin(dists))
            print(f"  XFOV≈{xfov_key:+3d}° (θ_int={th[idx]:.1f}°): "
                  f"T+1={T1[idx]*100:.1f}%  R0={R0[idx]*100:.1f}%")

    print(f"\nMFE = {MFE*100:.2f}%")
    print(f"Target (paper): 25.3%  →  {'PASS ✓' if MFE>=0.253 else 'BELOW TARGET ✗'}")
    print(f"\nAll outputs: {OUTPUT_DIR}/")

    summary = {
        'MFE_percent': round(MFE*100, 2),
        'MFE_pass':    bool(MFE >= 0.253),
        'paper_target_percent': 25.3,
        'xfov_angles':    xfov.tolist(),
        'coupling_eff':   coupling.tolist(),
        'zones': ser,
    }
    with open(os.path.join(OUTPUT_DIR, 'summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)
    print("Saved summary.json")


if __name__ == '__main__':
    main()
