"""
Publication-quality plots reproducing Fig 3(d-f) and MFE coupling efficiency curve
from Xiong et al. 2025 (Optical Materials Express).
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.interpolate import interp1d
import os

# ── Load data ──────────────────────────────────────────────────────────────────
base = "_outputs/photonics"

with open(f"{base}/zone1_results.json") as f: z1 = json.load(f)
with open(f"{base}/zone2_results.json") as f: z2 = json.load(f)
with open(f"{base}/zone3_results.json") as f: z3 = json.load(f)
with open(f"{base}/mfe_result.json")   as f: mfe = json.load(f)

zones     = [z1, z2, z3]
zone_lbls = ["Zone 1", "Zone 2", "Zone 3"]

# Grating / optical constants
n_glass = 1.5195
lam     = 532e-9   # [m]
d       = 453e-9   # [m]
m       = +1

def glass_to_air(theta_glass_deg):
    """
    Map θ_glass (TIR side) → equivalent θ_air (FOV angle) via inverse grating eq.
      sin(θ_air) = n_glass·sin(θ_glass) − m·λ/d
    Returns NaN if outside [-1,1].
    """
    tg  = np.deg2rad(np.asarray(theta_glass_deg, dtype=float))
    sin = n_glass * np.sin(tg) - m * lam / d
    sin = np.clip(sin, -1, 1)
    return np.degrees(np.arcsin(sin))

# ── Plot 1 – efficiency_curves.png ────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)
fig.subplots_adjust(wspace=0.12, left=0.07, right=0.97, top=0.90, bottom=0.13)

panel_letters = ["(d)", "(e)", "(f)"]

for ax, z, lbl, letter in zip(axes, zones, zone_lbls, panel_letters):

    angles_air   = np.array(z["angles_air"],   dtype=float)
    eta_T        = np.array(z["eta_T"],         dtype=float)
    angles_glass = np.array(z["angles_glass"],  dtype=float)
    eta_R        = np.array(z["eta_R"],         dtype=float)

    # Map η_R glass angles → equivalent FOV angles
    air_equiv = glass_to_air(angles_glass)

    # Interpolate η_R onto the same air-angle grid as η_T
    interp_R   = interp1d(air_equiv, eta_R, kind="linear",
                          bounds_error=False, fill_value="extrapolate")
    eta_R_grid = np.clip(interp_R(angles_air), 0, None)

    eta_sum = eta_T + eta_R_grid

    # ── curves ─────────────────────────────────────────────────────────────
    lw = 1.8
    ax.plot(angles_air, eta_T,     color="tab:red",   lw=lw, marker="o",
            ms=4, label="1st-order transmission ($\\eta_T$)")
    ax.plot(air_equiv,  eta_R,     color="tab:blue",  lw=lw, marker="s",
            ms=4, label="0th-order reflection ($\\eta_R$)")
    ax.plot(angles_air, eta_sum,   color="black",     lw=lw, marker="^",
            ms=4, ls="--", label="Sum $\\eta_T + \\eta_R$")

    # Reference line
    ax.axhline(1.0, color="gray", lw=0.9, ls=":", alpha=0.7)

    # ── cosmetics ──────────────────────────────────────────────────────────
    ax.set_xlim(-11, 11)
    ax.set_ylim(0, 1.05)
    ax.set_xticks([-10, -5, 0, 5, 10])
    ax.set_xlabel("Incident angle (deg)", fontsize=11)
    ax.set_title(f"{letter}  {lbl}", fontsize=12, fontweight="bold", pad=6)
    ax.tick_params(labelsize=10)
    ax.grid(True, ls=":", alpha=0.4)

    if ax is axes[0]:
        ax.set_ylabel("Efficiency", fontsize=11)
    if ax is axes[2]:
        ax.legend(loc="upper left", fontsize=8.5, framealpha=0.85)

# Global title
fig.suptitle("Diffraction efficiency curves — three-zone in-coupler (λ = 532 nm)",
             fontsize=12, y=0.98)

out1 = f"{base}/efficiency_curves.png"
fig.savefig(out1, dpi=300, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out1}")

# ── Plot 2 – coupling_efficiency.png ─────────────────────────────────────────
fov_angles   = np.array(mfe["fov_angles"],                  dtype=float)
coup_eff     = np.array(mfe["coupling_efficiency_per_angle"], dtype=float)
zone_assign  = np.array(mfe["zone_assignments"],             dtype=int)
mfe_val      = mfe["mfe_value"]

zone_colors = {1: "tab:blue", 2: "tab:orange", 3: "tab:green"}
zone_labels = {1: "Zone 1",   2: "Zone 2",     3: "Zone 3"}

fig2, ax2 = plt.subplots(figsize=(8, 5))

# Plot per-zone scatter + line (draw one legend handle per zone)
for zid in [1, 2, 3]:
    mask = zone_assign == zid
    ang  = fov_angles[mask]
    eff  = coup_eff[mask]
    col  = zone_colors[zid]
    ax2.plot(ang, eff, color=col, lw=1.6, zorder=3)
    ax2.scatter(ang, eff, color=col, s=40, zorder=4, label=zone_labels[zid])

# MFE minimum star
min_idx = np.argmin(coup_eff)
ax2.scatter(fov_angles[min_idx], coup_eff[min_idx],
            marker="*", s=220, color="crimson", zorder=5)
ax2.annotate(
    f"  MFE = {mfe_val*100:.1f}%",
    xy=(fov_angles[min_idx], coup_eff[min_idx]),
    xytext=(fov_angles[min_idx] + 0.5, coup_eff[min_idx] + 0.025),
    fontsize=10, color="crimson",
    arrowprops=dict(arrowstyle="->", color="crimson", lw=1.2),
)

# Reference lines
ax2.axhline(0.253, color="tab:red",   lw=1.4, ls="--",
            label="Paper MFE (25.3%)")
ax2.axhline(0.25,  color="tab:green", lw=1.4, ls="--",
            label="Target (25%)")

# Zone boundaries
for xb in [-4, 4]:
    ax2.axvline(xb, color="gray", lw=1.0, ls="--", alpha=0.7)
ax2.text(-7,  0.57, "Zone 1", ha="center", fontsize=9, color=zone_colors[1], alpha=0.85)
ax2.text( 1,  0.57, "Zone 2", ha="center", fontsize=9, color=zone_colors[2], alpha=0.85)
ax2.text( 7,  0.57, "Zone 3", ha="center", fontsize=9, color=zone_colors[3], alpha=0.85)

ax2.set_xlim(-11, 11)
ax2.set_ylim(0, 0.62)
ax2.set_xticks([-10, -5, 0, 5, 10])
ax2.set_xlabel("FOV angle (deg)", fontsize=12)
ax2.set_ylabel("Coupling efficiency", fontsize=12)
ax2.set_title("Three-Zone In-Coupler Coupling Efficiency (λ = 532 nm)",
              fontsize=12, fontweight="bold")
ax2.legend(loc="upper right", fontsize=9.5, framealpha=0.88)
ax2.grid(True, ls=":", alpha=0.4)
ax2.tick_params(labelsize=10)

out2 = f"{base}/coupling_efficiency.png"
fig2.savefig(out2, dpi=300, bbox_inches="tight")
plt.close(fig2)
print(f"Saved: {out2}")

# ── Verification summary ───────────────────────────────────────────────────────
print("\n" + "="*60)
print("VERIFICATION SUMMARY")
print("="*60)
print(f"MFE value           : {mfe_val:.4f}  ({mfe_val*100:.2f}%)")
print(f"MFE >= 25%          : {mfe_val >= 0.25}")
print(f"Meets paper target  : {mfe['meets_target']}")
print()
print(f"{'FOV angle (°)':>14}  {'Zone':>6}  {'Coupling eff.':>14}")
print("-"*38)
for ang, eff, zid in zip(fov_angles, coup_eff, zone_assign):
    print(f"{ang:>14.1f}  {zid:>6}  {eff:>14.4f}")
print("-"*38)
print(f"{'Min':>14}         {coup_eff.min():>14.4f}")
print(f"{'Max':>14}         {coup_eff.max():>14.4f}")
print(f"{'Mean':>14}         {coup_eff.mean():>14.4f}")
print("="*60)
