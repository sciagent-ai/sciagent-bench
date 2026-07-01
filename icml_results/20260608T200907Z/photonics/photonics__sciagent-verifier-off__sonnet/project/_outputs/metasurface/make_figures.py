"""
Generate publication-quality figures for 3-zone TiO2/N-BK7 metasurface in-coupler.
Reproduces Fig 3(d-f) and coupling efficiency summary.
"""
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.patches import FancyArrowPatch
import warnings
warnings.filterwarnings('ignore')

# ─── Load data ───────────────────────────────────────────────────────────────
with open('_outputs/metasurface/zone_efficiencies.json') as f:
    data = json.load(f)

angles      = np.array(data['angles_deg'])          # surface incident angles
glass_ang   = np.array(data['glass_angles_deg'])    # secondary glass angles

zones = {
    1: data['zone1'],
    2: data['zone2'],
    3: data['zone3'],
}

# paper targets
targets = {
    1: {'T1': 96, 'R0': 4},
    2: {'T1': 54, 'R0': 46},
    3: {'T1': 27, 'R0': 73},
}

# ─── Physics: multi-bounce coupling efficiency ────────────────────────────────
# Waveguide parameters
t_wg = 0.5e-3        # 0.5 mm waveguide thickness
W    = 3.00e-3       # 3 mm in-coupler aperture (mm → m)

# Zone boundaries [mm → m]
zone_bounds = [
    (0.00e-3, 1.06e-3),
    (1.06e-3, 2.07e-3),
    (2.07e-3, 3.00e-3),
]

# Grating equation: n_g * sin(theta_g) = sin(theta_s) + lambda/period
n_glass = 1.5195
lam     = 532e-9     # m
period  = 453e-9     # m

def zone_at(x):
    """Return zone index (0,1,2) for position x [m]."""
    for i, (lo, hi) in enumerate(zone_bounds):
        if lo <= x < hi:
            return i
    return 2  # default last zone

def get_eta(zone_idx, angle_idx, kind):
    """Return eta_T1 or eta_R0 for a zone at a given angle index."""
    key = f'zone{zone_idx+1}'
    arr = zones[zone_idx+1][f'eta_{kind}']
    return arr[angle_idx]

# Build interpolators (linear) for each zone, T1 and R0
from scipy.interpolate import interp1d

interp = {}
for zn in [1, 2, 3]:
    interp[(zn, 'T1')] = interp1d(angles, zones[zn]['eta_T1'],
                                   kind='linear', fill_value='extrapolate')
    interp[(zn, 'R0')] = interp1d(angles, zones[zn]['eta_R0'],
                                   kind='linear', fill_value='extrapolate')

def theta_glass(theta_s_deg):
    """Glass-side refracted angle (degrees) from surface angle."""
    theta_s = np.deg2rad(theta_s_deg)
    sin_tg  = (np.sin(theta_s) + lam / period) / n_glass
    sin_tg  = np.clip(sin_tg, -1, 1)
    return np.rad2deg(np.arcsin(sin_tg))

def coupling_efficiency_at(theta_s_deg, N=5000):
    """
    Multi-bounce model:
    eta(x0, theta) = T1(zone@x0) × ∏_{bounces} R0(zone@xk)
    Integrate over x0 ∈ [0, W].
    """
    tg  = theta_glass(theta_s_deg)
    dx  = 2.0 * t_wg * np.tan(np.deg2rad(tg))  # bounce step

    x0_arr  = np.linspace(0, W, N)
    weights = np.ones(N)  # uniform

    eta_arr = np.zeros(N)
    for i, x0 in enumerate(x0_arr):
        z0  = zone_at(x0)
        t1  = float(interp[(z0+1, 'T1')](theta_s_deg))
        eta = t1
        # subsequent bounces
        x   = x0 + dx
        while 0 < x < W:
            z    = zone_at(x)
            r0   = float(interp[(z+1, 'R0')](theta_s_deg))
            eta *= r0
            x   += dx
        eta_arr[i] = eta

    return float(np.mean(eta_arr)) * 100.0   # → %

# Compute coupling efficiency over XFOV
xfov_angles = np.linspace(-10, 10, 201)
ce_arr      = np.array([coupling_efficiency_at(a) for a in xfov_angles])

# MFE = minimum of coupling efficiency
mfe_idx = np.argmin(ce_arr)
mfe_val = ce_arr[mfe_idx]
mfe_ang = xfov_angles[mfe_idx]

# Also compute at the 11 sampled angles
ce_sampled = np.array([coupling_efficiency_at(a) for a in angles])

print(f"MFE = {mfe_val:.2f}% at {mfe_ang:.1f} deg")
print(f"Coupling efficiency range: {ce_arr.min():.1f}% – {ce_arr.max():.1f}%")

# ─── Matplotlib style ─────────────────────────────────────────────────────────
plt.rcParams.update({
    'font.family':       'sans-serif',
    'font.size':         10,
    'axes.linewidth':    1.2,
    'axes.labelsize':    11,
    'axes.titlesize':    12,
    'legend.fontsize':   9,
    'xtick.major.width': 1.0,
    'ytick.major.width': 1.0,
    'lines.linewidth':   1.8,
    'figure.dpi':        150,
})

# Color palette
CLR_RED   = '#d62728'
CLR_BLUE  = '#1f77b4'
CLR_BLACK = '#1a1a1a'
CLR_GRAY  = '#888888'

# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 1 – Zone efficiency curves (Fig 3d-f)
# ─────────────────────────────────────────────────────────────────────────────
fig1, axes1 = plt.subplots(1, 3, figsize=(13, 4.5), sharey=True)
fig1.subplots_adjust(wspace=0.08, left=0.08, right=0.97, top=0.82, bottom=0.22)

zone_labels = ['Zone 1', 'Zone 2', 'Zone 3']

for col, (zn, ax) in enumerate(zip([1, 2, 3], axes1)):
    T1 = np.array(zones[zn]['eta_T1']) * 100
    R0 = np.array(zones[zn]['eta_R0']) * 100
    S  = T1 + R0

    # bottom x-axis: surface incident angles
    ax.plot(angles, T1, color=CLR_RED,   marker='o', ms=4, label='1st order diffraction')
    ax.plot(angles, R0, color=CLR_BLUE,  marker='s', ms=4, label='0th order reflection')
    ax.plot(angles, S,  color=CLR_BLACK, marker='^', ms=4, label='Sum')

    # dashed target lines
    tgt_T1 = targets[zn]['T1']
    tgt_R0 = targets[zn]['R0']
    ax.axhline(tgt_T1, color=CLR_RED,   ls='--', lw=1.2, alpha=0.7)
    ax.axhline(tgt_R0, color=CLR_BLUE,  ls='--', lw=1.2, alpha=0.7)

    # axis limits & ticks
    ax.set_xlim(-10, 10)
    ax.set_ylim(0, 105)
    ax.set_xticks(np.arange(-10, 11, 2))
    ax.set_yticks(np.arange(0, 101, 20))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))

    ax.set_title(zone_labels[col], fontweight='bold')
    ax.set_xlabel('Surface incident angle (deg)', labelpad=4)
    ax.grid(True, alpha=0.3, linewidth=0.6)

    if col == 0:
        ax.set_ylabel('Efficiency (%)')

    # secondary (top) x-axis: glass angles
    ax2 = ax.twiny()
    ax2.set_xlim(-10, 10)
    # Map top axis ticks from glass_angle space → surface angle space
    # We'll set custom tick positions at a few evenly-spaced glass angles
    target_glass = np.linspace(glass_ang.min(), glass_ang.max(), 5)
    # Invert the grating eq: sin(theta_s) = n_g*sin(theta_g) - lambda/period
    sin_ts = n_glass * np.sin(np.deg2rad(target_glass)) - lam / period
    sin_ts = np.clip(sin_ts, -1, 1)
    top_tick_surf = np.rad2deg(np.arcsin(sin_ts))
    ax2.set_xticks(top_tick_surf)
    ax2.set_xticklabels([f'{g:.1f}°' for g in target_glass], fontsize=8)
    ax2.set_xlabel('Secondary incident angle (deg)', labelpad=4)

    # legend on first panel only
    if col == 0:
        ax.legend(loc='upper right', framealpha=0.85, edgecolor='gray')
    
    # annotate target values
    ax.text(0.03, tgt_T1 + 2, f'T₁={tgt_T1}%', color=CLR_RED,
            fontsize=7.5, transform=ax.get_yaxis_transform(), ha='left')
    ax.text(0.03, tgt_R0 + 2, f'R₀={tgt_R0}%', color=CLR_BLUE,
            fontsize=7.5, transform=ax.get_yaxis_transform(), ha='left')

fig1.suptitle('TiO₂/N-BK7 Metasurface In-coupler – Zone Diffraction Efficiency (Fig 3d-f)',
              fontsize=12, fontweight='bold', y=0.98)

fig1.savefig('_outputs/metasurface/fig3_zone_efficiency_curves.png',
             dpi=300, bbox_inches='tight', facecolor='white')
print("Saved fig3_zone_efficiency_curves.png")

# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 2 – Coupling efficiency + MFE (Fig 4b style)
# ─────────────────────────────────────────────────────────────────────────────
fig2, ax2m = plt.subplots(figsize=(7, 4.5))
fig2.subplots_adjust(left=0.13, right=0.95, top=0.88, bottom=0.13)

ax2m.plot(xfov_angles, ce_arr, color=CLR_BLUE, lw=2.0, label='Coupling efficiency')

# mark minimum
ax2m.plot(mfe_ang, mfe_val, marker='v', color=CLR_RED, ms=9, zorder=5,
          label=f'Min @ {mfe_ang:.1f}°')

# paper MFE line
paper_mfe = 25.3
ax2m.axhline(paper_mfe, color=CLR_RED, ls='--', lw=1.5,
             label=f'Paper MFE = {paper_mfe}%')
ax2m.text(9.5, paper_mfe + 1.0, f'{paper_mfe}%', color=CLR_RED,
          fontsize=9, ha='right', va='bottom')

# simulated MFE line
ax2m.axhline(mfe_val, color='#2ca02c', ls='--', lw=1.5,
             label=f'Simulated MFE = {mfe_val:.1f}%')
ax2m.text(9.5, mfe_val + 1.0, f'{mfe_val:.1f}%', color='#2ca02c',
          fontsize=9, ha='right', va='bottom')

ax2m.set_xlim(-10, 10)
ax2m.set_ylim(0, 80)
ax2m.set_xticks(np.arange(-10, 11, 2))
ax2m.set_yticks(np.arange(0, 81, 10))
ax2m.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
ax2m.set_xlabel('XFOV (degrees)', fontsize=11)
ax2m.set_ylabel('Coupling Efficiency (%)', fontsize=11)
ax2m.set_title('Metasurface In-coupler Coupling Efficiency (Fig 4b)',
               fontweight='bold')
ax2m.legend(loc='upper left', framealpha=0.85, edgecolor='gray')
ax2m.grid(True, alpha=0.3, linewidth=0.6)

fig2.savefig('_outputs/metasurface/fig4_coupling_mfe.png',
             dpi=300, bbox_inches='tight', facecolor='white')
print("Saved fig4_coupling_mfe.png")

# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 3 – Combined 2×3 summary panel
# ─────────────────────────────────────────────────────────────────────────────
fig3 = plt.figure(figsize=(15, 9))
fig3.subplots_adjust(wspace=0.12, hspace=0.45, left=0.07, right=0.97,
                     top=0.92, bottom=0.10)

# Row 1: Zone panels (a-c) – columns 1-3
axes_top = [fig3.add_subplot(2, 3, c+1) for c in range(3)]
# Row 2: Coupling efficiency in first two cols span → use subplot2grid trick
ax_bot = fig3.add_subplot(2, 3, (4, 6))

panel_labels = ['(a)', '(b)', '(c)', '(d)']

for col, (zn, ax) in enumerate(zip([1, 2, 3], axes_top)):
    T1 = np.array(zones[zn]['eta_T1']) * 100
    R0 = np.array(zones[zn]['eta_R0']) * 100
    S  = T1 + R0

    ax.plot(angles, T1, color=CLR_RED,   marker='o', ms=3.5, lw=1.6,
            label='1st order diffraction')
    ax.plot(angles, R0, color=CLR_BLUE,  marker='s', ms=3.5, lw=1.6,
            label='0th order reflection')
    ax.plot(angles, S,  color=CLR_BLACK, marker='^', ms=3.5, lw=1.6,
            label='Sum')

    tgt_T1 = targets[zn]['T1']
    tgt_R0 = targets[zn]['R0']
    ax.axhline(tgt_T1, color=CLR_RED,  ls='--', lw=1.1, alpha=0.7)
    ax.axhline(tgt_R0, color=CLR_BLUE, ls='--', lw=1.1, alpha=0.7)

    ax.set_xlim(-10, 10)
    ax.set_ylim(0, 105)
    ax.set_xticks(np.arange(-10, 11, 4))
    ax.set_yticks(np.arange(0, 101, 25))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.set_title(f'{panel_labels[col]} {zone_labels[col]}', fontweight='bold', fontsize=11)
    ax.set_xlabel('Incident angle (deg)', fontsize=9)
    ax.grid(True, alpha=0.3, linewidth=0.5)

    if col == 0:
        ax.set_ylabel('Efficiency (%)', fontsize=9)
    if col == 0:
        ax.legend(loc='upper right', fontsize=7.5, framealpha=0.85)

    # secondary x-axis
    ax2t = ax.twiny()
    ax2t.set_xlim(-10, 10)
    sin_ts = n_glass * np.sin(np.deg2rad(target_glass)) - lam / period
    sin_ts = np.clip(sin_ts, -1, 1)
    top_tick_surf = np.rad2deg(np.arcsin(sin_ts))
    ax2t.set_xticks(top_tick_surf)
    ax2t.set_xticklabels([f'{g:.0f}°' for g in target_glass], fontsize=7)
    ax2t.set_xlabel('Glass angle (deg)', fontsize=8, labelpad=3)

    # target text
    ax.text(0.03, tgt_T1 + 2, f'{tgt_T1}%', color=CLR_RED,
            fontsize=7, transform=ax.get_yaxis_transform())
    ax.text(0.03, tgt_R0 + 2, f'{tgt_R0}%', color=CLR_BLUE,
            fontsize=7, transform=ax.get_yaxis_transform())

# Bottom panel: coupling efficiency
ax_bot.plot(xfov_angles, ce_arr, color=CLR_BLUE, lw=2.0, label='Coupling efficiency')
ax_bot.plot(mfe_ang, mfe_val, marker='v', color=CLR_RED, ms=9, zorder=5,
            label=f'Min @ {mfe_ang:.1f}°')
ax_bot.axhline(paper_mfe, color=CLR_RED, ls='--', lw=1.5,
               label=f'Paper MFE = {paper_mfe}%')
ax_bot.axhline(mfe_val, color='#2ca02c', ls='--', lw=1.5,
               label=f'Simulated MFE = {mfe_val:.1f}%')
ax_bot.text(9.5, paper_mfe + 1.0, f'{paper_mfe}%', color=CLR_RED,
            fontsize=9, ha='right', va='bottom')
ax_bot.text(9.5, mfe_val + 1.0, f'{mfe_val:.1f}%', color='#2ca02c',
            fontsize=9, ha='right', va='bottom')
ax_bot.set_xlim(-10, 10)
ax_bot.set_ylim(0, 80)
ax_bot.set_xticks(np.arange(-10, 11, 2))
ax_bot.set_yticks(np.arange(0, 81, 10))
ax_bot.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
ax_bot.set_xlabel('XFOV (degrees)', fontsize=11)
ax_bot.set_ylabel('Coupling Efficiency (%)', fontsize=11)
ax_bot.set_title('(d) Coupling Efficiency & MFE', fontweight='bold', fontsize=11)
ax_bot.legend(loc='upper left', framealpha=0.85, edgecolor='gray', fontsize=9)
ax_bot.grid(True, alpha=0.3, linewidth=0.5)

# Annotation textbox
def fmts(v, tgt):
    diff = v - tgt
    sym  = '+' if diff >= 0 else ''
    return f'{v:.1f}% (target {tgt}%, {sym}{diff:.1f}%)'

textstr = (
    f'Simulated MFE = {mfe_val:.1f}%  |  Paper = {paper_mfe}%\n'
    f'Zone 1 T₁ @ -10°: {zones[1]["eta_T1"][0]*100:.1f}% (target 96%)\n'
    f'Zone 2 T₁ @ -10°: {zones[2]["eta_T1"][0]*100:.1f}% (target 54%)\n'
    f'Zone 3 T₁ @ -10°: {zones[3]["eta_T1"][0]*100:.1f}% (target 27%)'
)
props = dict(boxstyle='round', facecolor='lightyellow', alpha=0.85, edgecolor='goldenrod')
ax_bot.text(0.02, 0.97, textstr, transform=ax_bot.transAxes,
            fontsize=8, verticalalignment='top', bbox=props)

fig3.suptitle('TiO₂/N-BK7 Metasurface In-coupler – Summary',
              fontsize=13, fontweight='bold', y=0.97)

fig3.savefig('_outputs/metasurface/metasurface_summary.png',
             dpi=300, bbox_inches='tight', facecolor='white')
print("Saved metasurface_summary.png")

# ─────────────────────────────────────────────────────────────────────────────
# MFE report JSON
# ─────────────────────────────────────────────────────────────────────────────
# coupling efficiency at the 11 sampled angles
ce_by_angle = {str(int(a)): float(ce_sampled[i]) for i, a in enumerate(angles)}

report = {
    "MFE_pct":               float(mfe_val),
    "MFE_angle_deg":         float(mfe_ang),
    "coupling_efficiency_pct": ce_by_angle,
    "zone1_at_neg10": {
        "T1_pct":        float(zones[1]['eta_T1'][0] * 100),
        "R0_pct":        float(zones[1]['eta_R0'][0] * 100),
        "target_T1_pct": 96,
        "target_R0_pct": 4,
    },
    "zone2_at_neg10": {
        "T1_pct":        float(zones[2]['eta_T1'][0] * 100),
        "R0_pct":        float(zones[2]['eta_R0'][0] * 100),
        "target_T1_pct": 54,
        "target_R0_pct": 46,
    },
    "zone3_at_neg10": {
        "T1_pct":        float(zones[3]['eta_T1'][0] * 100),
        "R0_pct":        float(zones[3]['eta_R0'][0] * 100),
        "target_T1_pct": 27,
        "target_R0_pct": 73,
    },
    "paper_MFE_pct": 25.3,
}

with open('_outputs/metasurface/mfe_report.json', 'w') as f:
    json.dump(report, f, indent=2)
print("Saved mfe_report.json")
print(json.dumps(report, indent=2))
