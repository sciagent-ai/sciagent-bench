"""
Multi-zone waveguide in-coupler coupling efficiency analysis.
Implements the Xiong et al. (Opt. Mat. Express 2025) model from Fig 2.
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import os

# ── Load RCWA data ──────────────────────────────────────────────────────────
with open('./_outputs/rcwa_results/results.json') as f:
    data = json.load(f)

# Per-zone arrays (22 points, 41.5° to 62.5° in 1° steps)
thetas_int = np.array(data['1']['thetas_int'])          # internal angles
T1   = {z: np.array(data[str(z)]['T1_vs_angle']) for z in [1,2,3]}
R0   = {z: np.array(data[str(z)]['R0_vs_angle']) for z in [1,2,3]}
T1p  = {z: np.array(data[str(z)]['T1_paper'])    for z in [1,2,3]}
R0p  = {z: np.array(data[str(z)]['R0_paper'])    for z in [1,2,3]}

# ── Physical parameters ──────────────────────────────────────────────────────
lambda_  = 532e-9   # m
d        = 453e-9   # m
n_glass  = 1.5195
t_wg     = 0.5e-3   # waveguide thickness [m]
L_coupler= 3.0e-3   # coupler total width  [m]

# Zone x-boundaries [m]
zone_bounds = [(0.0, 1.06e-3), (1.06e-3, 2.07e-3), (2.07e-3, 3.00e-3)]

def get_zone(x):
    """Return zone index (1,2,3) for position x in [0, 3mm]."""
    if   x < 1.06e-3: return 1
    elif x < 2.07e-3: return 2
    else:              return 3

def theta_int_from_ext(theta_x_deg):
    """Map external XFOV angle to internal first-order angle (degrees)."""
    sin_int = (np.sin(np.deg2rad(theta_x_deg)) + lambda_/d) / n_glass
    return np.rad2deg(np.arcsin(np.clip(sin_int, -1, 1)))

def angle_to_index(theta_int_deg):
    """Convert internal angle to array index (clipped to valid range)."""
    idx = int(round(theta_int_deg - 41.5))
    return np.clip(idx, 0, len(thetas_int)-1)

def get_T1(zone, theta_x_deg):
    """T+1 for zone at external angle theta_x_deg."""
    th_int = theta_int_from_ext(theta_x_deg)
    idx    = angle_to_index(th_int)
    return T1[zone][idx]

def get_R0(zone, theta_prop_deg):
    """R0 for zone at propagation angle theta_prop_deg (internal glass)."""
    idx = angle_to_index(theta_prop_deg)
    return R0[zone][idx]

def tir_step(theta_x_deg):
    """Horizontal TIR step distance s [m]."""
    sin_prop = (np.sin(np.deg2rad(theta_x_deg)) + lambda_/d) / n_glass
    sin_prop = np.clip(sin_prop, -1, 1)
    theta_prop = np.arcsin(sin_prop)
    return 2.0 * t_wg * np.tan(theta_prop)

# ── Coupling efficiency: Monte Carlo over entry positions ──────────────────
def coupling_efficiency(theta_x_deg, n_samples=300):
    """
    For each x0 uniformly sampled in [0, 3mm]:
      1) Primary coupling: T+1 of zone(x0)
      2) Successive secondary bounces: multiply by R0 of zone(x_n) while in coupler
    Return mean over all x0.
    """
    th_int   = theta_int_from_ext(theta_x_deg)
    s        = tir_step(theta_x_deg)
    
    x0_vals  = np.linspace(0, L_coupler, n_samples, endpoint=False)
    efficiencies = []
    
    for x0 in x0_vals:
        z_primary = get_zone(x0)
        eta = T1[z_primary][angle_to_index(th_int)]   # primary coupling
        
        # Walk secondary bounces
        x = x0 + s
        while 0.0 <= x <= L_coupler:
            z_sec = get_zone(x)
            eta  *= R0[z_sec][angle_to_index(th_int)]
            x    += s
        
        efficiencies.append(eta)
    
    return np.mean(efficiencies)

# ── Sweep XFOV ───────────────────────────────────────────────────────────────
xfov_angles = np.arange(-10.0, 10.5, 0.5)   # -10° to +10° in 0.5° steps
coup_eff    = np.array([coupling_efficiency(th) for th in xfov_angles])

MFE         = float(np.min(coup_eff))
MFE_angle   = xfov_angles[np.argmin(coup_eff)]
pass_fail   = "PASS" if MFE >= 0.25 else "FAIL"

print(f"MFE = {MFE*100:.2f}%  →  {pass_fail}  (target ≥ 25%)")
print(f"Minimum at XFOV = {MFE_angle:.1f}°")

# Per-zone statistics
for z in [1, 2, 3]:
    print(f"Zone {z}: mean T+1 = {np.mean(T1[z])*100:.1f}%,  mean R0 = {np.mean(R0[z])*100:.1f}%")

# ── External angle axis (for T+1 x-axis) ─────────────────────────────────────
# Map thetas_int → theta_x via inverse grating equation
sin_x_arr = n_glass * np.sin(np.deg2rad(thetas_int)) - lambda_/d
sin_x_arr = np.clip(sin_x_arr, -1, 1)
theta_x_arr = np.rad2deg(np.arcsin(sin_x_arr))   # external angle for each internal angle point

# ── Figure 1: Zone efficiencies (3-panel, paper Fig 3d-f style) ──────────────
paper_targets = {
    1: {'T1': 0.96, 'R0': 0.04},
    2: {'T1': 0.54, 'R0': 0.46},
    3: {'T1': 0.27, 'R0': 0.73},
}

fig1, axes = plt.subplots(1, 3, figsize=(15, 5))
zone_labels = {1: 'Zone 1 (1.06 mm)', 2: 'Zone 2 (1.01 mm)', 3: 'Zone 3 (0.93 mm)'}

for ax, z in zip(axes, [1, 2, 3]):
    ax.plot(theta_x_arr, T1[z]*100,  'r-',  lw=2,   label='T+1 (RCWA)')
    ax.plot(theta_x_arr, R0[z]*100,  'b-',  lw=2,   label='R0 (RCWA)')
    ax.plot(theta_x_arr, (T1[z]+R0[z])*100, 'k-', lw=2, label='T+1 + R0')
    
    # Paper targets (dashed)
    ax.axhline(paper_targets[z]['T1']*100, color='r', ls='--', lw=1.2,
               label=f"Target T+1={paper_targets[z]['T1']*100:.0f}%")
    ax.axhline(paper_targets[z]['R0']*100, color='b', ls='--', lw=1.2,
               label=f"Target R0={paper_targets[z]['R0']*100:.0f}%")
    
    ax.set_xlabel('Incident Angle (deg)', fontsize=11)
    ax.set_ylabel('Efficiency (%)', fontsize=11)
    ax.set_title(zone_labels[z], fontsize=12, fontweight='bold')
    ax.set_ylim(0, 105)
    ax.set_xlim(theta_x_arr[0], theta_x_arr[-1])
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%g'))
    ax.legend(fontsize=8, loc='upper right')
    ax.grid(True, alpha=0.3)

fig1.suptitle('Per-Zone Diffraction Efficiencies (Xiong et al. 2025)', fontsize=13, fontweight='bold')
fig1.tight_layout()
fig1.savefig('./_outputs/final_analysis/fig1_zone_efficiencies.png', dpi=150, bbox_inches='tight')
print("Saved fig1_zone_efficiencies.png")

# ── Figure 2: Coupling efficiency vs XFOV ────────────────────────────────────
fig2, ax2 = plt.subplots(figsize=(9, 5))

ax2.plot(xfov_angles, coup_eff*100, 'b-o', lw=2, ms=4, label='Coupling efficiency (RCWA model)')

# Mark minimum
ax2.plot(MFE_angle, MFE*100, 'rv', ms=12, zorder=5,
         label=f'MFE = {MFE*100:.2f}% @ {MFE_angle:.1f}°')

# Reference lines
ax2.axhline(25.3, color='orange', ls='--', lw=1.8, label='Paper MFE = 25.3%')
ax2.axhline(25.0, color='green',  ls='--', lw=1.8, label='Target MFE = 25.0%')

ax2.set_xlabel('XFOV Angle (deg)', fontsize=12)
ax2.set_ylabel('Coupling Efficiency (%)', fontsize=12)
ax2.set_title('Multi-zone In-coupler Coupling Efficiency vs XFOV\n(Xiong et al. Opt. Mat. Express 2025)',
              fontsize=12, fontweight='bold')
ax2.set_xlim(-11, 11)
ax2.set_ylim(0, max(coup_eff*100)*1.15)
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3)
ax2.set_xticks(np.arange(-10, 11, 2))

# Annotate pass/fail
bbox_props = dict(boxstyle="round,pad=0.4", fc="lightgreen" if pass_fail=="PASS" else "lightyellow",
                  ec="green" if pass_fail=="PASS" else "red", lw=1.5)
ax2.text(0.97, 0.05, f'{pass_fail}: MFE = {MFE*100:.2f}%',
         transform=ax2.transAxes, ha='right', va='bottom',
         fontsize=11, fontweight='bold', bbox=bbox_props)

fig2.tight_layout()
fig2.savefig('./_outputs/final_analysis/fig2_coupling_mfe.png', dpi=150, bbox_inches='tight')
print("Saved fig2_coupling_mfe.png")

# ── JSON summary ──────────────────────────────────────────────────────────────
summary = {
    "MFE_percent": round(MFE*100, 4),
    "MFE_angle_deg": float(MFE_angle),
    "pass_fail_25pct": pass_fail,
    "xfov_angles_deg": xfov_angles.tolist(),
    "coupling_efficiency": (coup_eff*100).tolist(),
    "per_zone": {
        str(z): {
            "mean_T1_percent": round(float(np.mean(T1[z]))*100, 3),
            "mean_R0_percent": round(float(np.mean(R0[z]))*100, 3),
            "paper_target_T1_percent": paper_targets[z]['T1']*100,
            "paper_target_R0_percent": paper_targets[z]['R0']*100,
        }
        for z in [1, 2, 3]
    },
    "model_parameters": {
        "lambda_nm": 532,
        "grating_period_nm": 453,
        "n_glass": 1.5195,
        "waveguide_thickness_mm": 0.5,
        "coupler_width_mm": 3.0,
        "zone_widths_mm": [1.06, 1.01, 0.93],
        "MC_samples": 300,
    }
}

with open('./_outputs/final_analysis/mfe_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)
print("Saved mfe_summary.json")

print("\n=== SUMMARY ===")
print(f"  MFE = {MFE*100:.2f}%  →  {pass_fail}  (target ≥ 25%)")
print(f"  MFE occurs at XFOV = {MFE_angle:.1f}°")
print("  Per-zone stats (RCWA):")
for z in [1,2,3]:
    pt = paper_targets[z]
    print(f"    Zone {z}: T+1={np.mean(T1[z])*100:.1f}% (target {pt['T1']*100:.0f}%),  "
          f"R0={np.mean(R0[z])*100:.1f}% (target {pt['R0']*100:.0f}%)")
