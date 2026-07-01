"""
S4 RCWA simulation for 3-zone TiO2/N-BK7 metasurface in-coupler
Xiong et al., Optical Materials Express 2025

Reversed stack (glass incident on top) to simulate light in glass waveguide
hitting metasurface from below. Efficiencies normalized by incident Poynting flux.
"""
import S4
import numpy as np
import json
import os

# ── Physical constants ───────────────────────────────────────────────────────
lam      = 532e-9        # wavelength [m]
freq     = 1.0 / lam     # S4 frequency = 1/λ (when lengths in metres)
n_TiO2   = 2.35
n_glass  = 1.5195
n_air    = 1.0
h_TiO2   = 250e-9        # TiO2 layer thickness [m]
period_x = 453e-9        # grating period in x [m]

NUM_BASIS = 150          # Fourier basis truncation (convergence trade-off)

# ── Zone geometry from Table 1 / Fig 3 ──────────────────────────────────────
# Each zone: nano-beam (bar_w × unit_y rectangle) + nano-pillar
#   Zone 1: pillar = 100×100 nm square
#   Zone 2: pillar = partial circle → approx as rectangle 156.5 × unit_y
#   Zone 3: pillar = partial circle → approx as rectangle 160.5 × unit_y
#
# Placement (x ∈ [-period_x/2, +period_x/2]):
#   Nano-beam:  left-aligned, center_x = -period_x/2 + bar_w/2
#   Nano-pillar: right-aligned, center_x = +period_x/2 - pillar_wx/2
zones = {
    1: dict(bar_w=110e-9, pillar_wx=100e-9,  pillar_wy=100e-9,  unit_y=177e-9, partial=False),
    2: dict(bar_w=110e-9, pillar_wx=156.5e-9, pillar_wy=None,   unit_y=140e-9, partial=True),
    3: dict(bar_w=100e-9, pillar_wx=160.5e-9, pillar_wy=None,   unit_y=164e-9, partial=True),
}

# ── Angle arrays ─────────────────────────────────────────────────────────────
surface_angles_deg = np.linspace(-10, 10, 11)
surface_angles_rad = np.deg2rad(surface_angles_deg)

# Map surface FOV angle → glass TIR angle:
#   n_glass * sin(theta_g) = sin(theta_s) + lambda/period
sin_tg = (np.sin(surface_angles_rad) + lam / period_x) / n_glass
sin_tg = np.clip(sin_tg, -1.0 + 1e-9, 1.0 - 1e-9)
glass_angles_rad = np.arcsin(sin_tg)
glass_angles_deg = np.degrees(glass_angles_rad)

print("Surface angles (deg):", np.round(surface_angles_deg, 2))
print("Glass  angles  (deg):", np.round(glass_angles_deg,  2))
print()


def run_zone(zone_id, zp):
    """
    Run S4 RCWA for one zone across all surface angles.
    Returns arrays eta_T1, eta_R0 each of length n_angles.

    Stack (top→bottom): GlassInc (semi-inf) | Metasurface (250nm) | AirTrans (semi-inf)
    Light incident from GlassInc at theta_g (TIR angle in glass).

    eta_T1 = fraction of incident power diffracted into order (-1,0) in AirTrans (T+1)
    eta_R0 = fraction reflected into order (0,0) back in GlassInc (R0)
    Both normalized to incident Poynting flux P_inc = Re[GetPoyntingFlux("GlassInc")[0]]
    """
    unit_y   = zp['unit_y']
    bar_w    = zp['bar_w']
    pillar_wx = zp['pillar_wx']
    # Pillar y-extent: full unit cell for partial circles, else actual dimension
    pillar_wy = unit_y if zp['partial'] else zp['pillar_wy']

    # Placements
    beam_cx    = -period_x / 2.0 + bar_w / 2.0
    beam_cy    = 0.0
    beam_hw_x  = bar_w / 2.0
    beam_hw_y  = unit_y / 2.0

    pillar_cx  = period_x / 2.0 - pillar_wx / 2.0
    pillar_cy  = 0.0
    pillar_hw_x = pillar_wx / 2.0
    pillar_hw_y = pillar_wy / 2.0

    eta_T1_arr = np.zeros(len(surface_angles_deg))
    eta_R0_arr = np.zeros(len(surface_angles_deg))

    for i, theta_g_rad in enumerate(glass_angles_rad):
        theta_g_deg = glass_angles_deg[i]

        # ── Build simulation ──────────────────────────────────────────────
        S = S4.New(
            Lattice=((period_x, 0), (0, unit_y)),
            NumBasis=NUM_BASIS
        )

        S.AddMaterial("Glass", complex(n_glass**2, 0))
        S.AddMaterial("TiO2",  complex(n_TiO2**2,  0))
        S.AddMaterial("Air",   complex(n_air**2,   0))

        # Reversed stack: glass (incident) → patterned TiO2 layer → air (transmitted)
        S.AddLayer("GlassInc",    0,       "Glass")
        S.AddLayer("Metasurface", h_TiO2,  "Glass")   # background glass, TiO2 inclusions
        S.AddLayer("AirTrans",    0,       "Air")

        # TiO2 nano-beam
        S.SetRegionRectangle(
            "Metasurface", "TiO2",
            (beam_cx, beam_cy), 0, (beam_hw_x, beam_hw_y)
        )
        # TiO2 nano-pillar
        S.SetRegionRectangle(
            "Metasurface", "TiO2",
            (pillar_cx, pillar_cy), 0, (pillar_hw_x, pillar_hw_y)
        )

        S.SetFrequency(freq)
        # TE = s-polarization; phi=0 (in-plane along x)
        S.SetExcitationPlanewave(
            IncidenceAngles=(theta_g_deg, 0.0),
            sAmplitude=complex(1, 0),
            pAmplitude=complex(0, 0),
            Order=0
        )

        # ── Incident power (normalisation) ───────────────────────────────
        # Re[forward flux in GlassInc] = incident Poynting flux
        fwd_inc, _bwd_inc = S.GetPoyntingFlux("GlassInc", 0)
        P_inc = max(float(np.real(fwd_inc)), 1e-30)   # guard against zero

        # ── Basis order map ───────────────────────────────────────────────
        basis = S.GetBasisSet()   # tuple of (gx, gy) int pairs
        order_map = {(int(round(gx)), int(round(gy))): idx
                     for idx, (gx, gy) in enumerate(basis)}

        # ── T+1: order (-1,0) forward in AirTrans ────────────────────────
        ret_air = S.GetPoyntingFluxByOrder("AirTrans", 0)
        idx_m1 = order_map.get((-1, 0), None)
        if idx_m1 is not None and idx_m1 < len(ret_air):
            fwd_T1 = float(np.real(ret_air[idx_m1][0]))
            eta_T1 = max(0.0, fwd_T1 / P_inc)
        else:
            eta_T1 = 0.0

        # ── R0: order (0,0) backward in GlassInc ─────────────────────────
        ret_glass = S.GetPoyntingFluxByOrder("GlassInc", 0)
        idx_00 = order_map.get((0, 0), None)
        if idx_00 is not None and idx_00 < len(ret_glass):
            bwd_R0 = float(np.real(ret_glass[idx_00][1]))
            eta_R0 = max(0.0, -bwd_R0 / P_inc)   # backward flux is negative → flip sign
        else:
            eta_R0 = 0.0

        eta_T1_arr[i] = eta_T1
        eta_R0_arr[i] = eta_R0

        print(f"  Z{zone_id} | theta_s={surface_angles_deg[i]:+6.1f}° "
              f"| theta_g={theta_g_deg:5.2f}° "
              f"| P_inc={P_inc:.4f} "
              f"| eta_T1={eta_T1:.4f}  eta_R0={eta_R0:.4f}")

    return eta_T1_arr, eta_R0_arr


# ── Run all 3 zones ──────────────────────────────────────────────────────────
results = {}
for zid, zp in zones.items():
    print(f"\n{'='*60}")
    print(f"=== Zone {zid}  (unit_y={zp['unit_y']*1e9:.0f} nm, "
          f"bar_w={zp['bar_w']*1e9:.0f} nm, "
          f"pillar_wx={zp['pillar_wx']*1e9:.1f} nm) ===")
    print(f"{'='*60}")
    t1, r0 = run_zone(zid, zp)
    results[zid] = dict(eta_T1=t1.tolist(), eta_R0=r0.tolist())
    print(f"  T+1 : {np.round(t1, 4)}")
    print(f"  R0  : {np.round(r0, 4)}")
    print(f"  T+R0: {np.round(t1+r0, 4)}")


# ── MFE computation (geometric multi-bounce model) ───────────────────────────
zone_bounds = [(0.0, 1.06), (1.06, 2.07), (2.07, 3.00)]   # mm
t_mm    = 0.5     # waveguide thickness [mm]
W_total = 3.0     # in-coupler width [mm]
N_x0    = 1000    # integration points

def get_zone_idx(pos_mm):
    for k, (lo, hi) in enumerate(zone_bounds):
        if lo <= pos_mm < hi:
            return k
    return 2

coupling_eff = np.zeros(len(surface_angles_deg))

print(f"\n{'='*60}")
print("=== MFE Computation ===")

for i, theta_s_deg in enumerate(surface_angles_deg):
    theta_g_rad_i = glass_angles_rad[i]
    delta_x_mm = 2.0 * t_mm * np.tan(theta_g_rad_i)

    x0_arr = np.linspace(0.0, W_total, N_x0, endpoint=False)
    total_coup = 0.0

    for x0 in x0_arr:
        remaining     = 1.0
        point_coupled = 0.0
        pos = x0
        n_bounce = 0
        while pos < W_total and remaining > 1e-8:
            zk  = get_zone_idx(pos)
            t1  = results[zk + 1]['eta_T1'][i]
            r0  = results[zk + 1]['eta_R0'][i]
            coupled    = remaining * t1
            point_coupled += coupled
            remaining  = remaining * (1.0 - t1) * r0
            pos       += delta_x_mm
            n_bounce  += 1
            if n_bounce > 500:
                break
        total_coup += point_coupled

    coupling_eff[i] = total_coup / N_x0
    print(f"  theta_s={theta_s_deg:+6.1f}°  delta_x={delta_x_mm:.3f} mm"
          f"  coupling={100*coupling_eff[i]:.2f}%")

MFE = float(np.min(coupling_eff))
MFE_angle = surface_angles_deg[np.argmin(coupling_eff)]
print(f"\n>>> MFE = {MFE:.4f}  ({100*MFE:.2f}%)  at theta_s = {MFE_angle:.1f}°")


# ── Save JSON ────────────────────────────────────────────────────────────────
out_dir = os.environ.get("OUTPUTS_DIR", "/workspace")
os.makedirs(out_dir, exist_ok=True)

data = {
    "angles_deg":          surface_angles_deg.tolist(),
    "glass_angles_deg":    glass_angles_deg.tolist(),
    "MFE":                 MFE,
    "MFE_angle_deg":       float(MFE_angle),
    "coupling_efficiency": coupling_eff.tolist(),
    "zone1": {
        "eta_T1":   results[1]['eta_T1'],
        "eta_R0":   results[1]['eta_R0'],
        "geometry": {"bar_w_nm": 110, "pillar_nm": 100, "unit_y_nm": 177, "partial": False}
    },
    "zone2": {
        "eta_T1":   results[2]['eta_T1'],
        "eta_R0":   results[2]['eta_R0'],
        "geometry": {"bar_w_nm": 110, "pillar_wx_nm": 156.5, "unit_y_nm": 140, "partial": True}
    },
    "zone3": {
        "eta_T1":   results[3]['eta_T1'],
        "eta_R0":   results[3]['eta_R0'],
        "geometry": {"bar_w_nm": 100, "pillar_wx_nm": 160.5, "unit_y_nm": 164, "partial": True}
    },
    "parameters": {
        "wavelength_nm": 532,
        "period_x_nm": 453,
        "n_TiO2": n_TiO2,
        "n_glass": n_glass,
        "h_TiO2_nm": 250,
        "NumBasis": NUM_BASIS,
        "t_waveguide_mm": t_mm,
        "W_incoupler_mm": W_total,
        "zone_bounds_mm": zone_bounds
    }
}
json_path = os.path.join(out_dir, "zone_efficiencies_v2.json")
with open(json_path, "w") as f:
    json.dump(data, f, indent=2)
print(f"\nSaved JSON -> {json_path}")


# ── Figure 1: Zone efficiency panels (Fig 3 d-f style) ───────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 3, figsize=(16, 5))
zone_labels = ["Zone 1\n(beam 110 nm + pillar 100 nm, Λy=177 nm)",
               "Zone 2\n(beam 110 nm + pillar 156.5 nm, Λy=140 nm)",
               "Zone 3\n(beam 100 nm + pillar 160.5 nm, Λy=164 nm)"]

for idx in range(3):
    ax  = axes[idx]
    zid = idx + 1
    t1  = np.array(results[zid]['eta_T1'])
    r0  = np.array(results[zid]['eta_R0'])

    ax2 = ax.twinx()
    l1, = ax.plot(surface_angles_deg,  t1,      'r-o', ms=5, lw=1.8, label=r'$\eta_{T+1}$ (left)')
    l2, = ax2.plot(glass_angles_deg,   r0,      'b-s', ms=5, lw=1.8, label=r'$\eta_{R0}$ (right)')
    l3, = ax.plot(surface_angles_deg,  t1 + r0, 'k--', ms=3, lw=1.2, alpha=0.7, label=r'$T+1+R_0$')

    ax.set_xlabel("Surface angle θ_s (deg)", fontsize=11)
    ax.set_ylabel(r"$\eta_{T+1}$", color='red', fontsize=12)
    ax2.set_ylabel(r"$\eta_{R0}$", color='blue', fontsize=12)
    ax.tick_params(axis='y', labelcolor='red')
    ax2.tick_params(axis='y', labelcolor='blue')
    ax.set_title(zone_labels[idx], fontsize=10)
    ax.set_xlim(-11, 11)
    ax.set_ylim(0, 1.05)
    ax2.set_ylim(0, 1.05)
    ax.grid(True, alpha=0.25)

    lns = [l1, l2, l3]
    labs = [l.get_label() for l in lns]
    ax.legend(lns, labs, fontsize=8, loc='upper right')

plt.suptitle("Diffraction Efficiencies — TiO₂/N-BK7 Metasurface In-coupler (λ=532 nm, Λ_x=453 nm)",
             fontsize=12, y=1.01)
plt.tight_layout()
fig_path1 = os.path.join(out_dir, "zone_efficiency_plots_v2.png")
plt.savefig(fig_path1, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved zone efficiency plot -> {fig_path1}")


# ── Figure 2: Coupling efficiency vs XFOV ────────────────────────────────────
fig2, ax = plt.subplots(figsize=(8, 5))
ax.plot(surface_angles_deg, coupling_eff * 100, 'ko-', ms=7, lw=2.2, label="Coupling efficiency")
ax.axhline(25.0,      color='red',   ls='--', lw=1.5, label="25% threshold")
ax.axhline(MFE * 100, color='green', ls=':',  lw=2.0,
           label=f"MFE = {100*MFE:.1f}%  (at {MFE_angle:.1f}°)")
ax.fill_between(surface_angles_deg, coupling_eff * 100, alpha=0.12, color='steelblue')
ax.set_xlabel("Surface FOV angle θ_s (deg)", fontsize=13)
ax.set_ylabel("Coupling efficiency (%)",      fontsize=13)
ax.set_title("Multi-bounce In-coupler Coupling Efficiency vs XFOV\n"
             "(TiO₂/N-BK7, 3-zone, λ=532 nm, t=0.5 mm waveguide)", fontsize=12)
ax.set_xlim(-11, 11)
ymax = max(80.0, 110 * np.max(coupling_eff))
ax.set_ylim(0, ymax)
ax.legend(fontsize=11)
ax.grid(True, alpha=0.3)
fig_path2 = os.path.join(out_dir, "coupling_efficiency_v2.png")
plt.savefig(fig_path2, dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved coupling efficiency plot -> {fig_path2}")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("="*60)
print(f"  FINAL RESULT: MFE = {MFE:.4f}  ({100*MFE:.2f}%)")
print(f"  at surface angle = {MFE_angle:.1f} deg")
print(f"  Coupling range: {100*np.min(coupling_eff):.2f}% – {100*np.max(coupling_eff):.2f}%")
print("="*60)
