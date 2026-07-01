"""
TiO2/N-BK7 three-zone metasurface in-coupler RCWA simulation.

Reproduces the design from:
  "Design and experimental validation of a high-efficiency multi-zone
   metasurface waveguide in-coupler", Optical Materials Express, 2025.

Key design choices (Table 1 / Fig 3):
  - λ = 532 nm, grating period = 453 nm, TiO2 height = 250 nm (shared)
  - Three zones: widths 1.06 / 1.01 / 0.93 mm
  - Per-zone targets (Fig 2e): η_T = 96/54/27%, η_R = 4/46/73%
  - Simulation: TE-polarised source from N-BK7 glass, angle range 41–63°
    (equivalent to XFOV −10° to +10° by light-reversibility)
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.optimize import minimize, differential_evolution
import json
import os

import grcwa

# ──────────────────────────────────────────────────────────────────────────────
# Physical constants
# ──────────────────────────────────────────────────────────────────────────────
LAMBDA_NM  = 532.0     # wavelength (nm)
PERIOD_X   = 453.0     # grating period in x (nm)
HEIGHT_NM  = 250.0     # TiO2 nano-structure height, fixed for all zones (nm)
T_WG_MM    = 0.5       # waveguide thickness (mm)
L_INCOUPLER_MM = 3.0   # total in-coupler length (mm)
# Zone widths from Fig 2(e)
ZONE_WIDTHS_MM = [1.06, 1.01, 0.93]
# Accumulated zone boundaries [0, 1.06, 2.07, 3.00] mm
ZONE_BOUNDS_MM = [0.0] + list(np.cumsum(ZONE_WIDTHS_MM))


# ──────────────────────────────────────────────────────────────────────────────
# Refractive indices
# ──────────────────────────────────────────────────────────────────────────────
def _n_nbk7(lam_um: float) -> float:
    """N-BK7 Sellmeier equation, λ in µm."""
    l2 = lam_um ** 2
    return float(np.sqrt(
        1
        + 1.03961212 * l2 / (l2 - 0.00600069867)
        + 0.231792344 * l2 / (l2 - 0.0200179144)
        + 1.01046945  * l2 / (l2 - 103.560653)
    ))


N_BK7  = _n_nbk7(LAMBDA_NM / 1000.0)   # ≈ 1.5195
N_TIO2 = complex(2.370, 0.001)         # ALD TiO2 at 532 nm (small imaginary for material loss)
N_AIR  = 1.0

# Ideal per-zone diffraction targets from Fig 2(e) (sum = 100%)
IDEAL_TARGETS = [
    (0.96, 0.04),   # Zone 1: η_T, η_R
    (0.54, 0.46),   # Zone 2
    (0.27, 0.73),   # Zone 3
]

# Adjusted realistic targets (sum < 100% due to absorption and other orders)
# Derived from Fig 3(d-f) simulation curves
REALISTIC_TARGETS = [
    (0.75, 0.08),   # Zone 1
    (0.52, 0.35),   # Zone 2
    (0.26, 0.60),   # Zone 3
]


# ──────────────────────────────────────────────────────────────────────────────
# Angle conversions  (grating equation, m = +1 into glass)
# ──────────────────────────────────────────────────────────────────────────────
def xfov_to_glass(theta_air_deg: float) -> float:
    """XFOV (air) → equivalent glass angle via +1-order grating equation."""
    s = (np.sin(np.radians(theta_air_deg)) + LAMBDA_NM / PERIOD_X) / N_BK7
    return float(np.degrees(np.arcsin(np.clip(s, -1, 1))))


def glass_to_xfov(theta_glass_deg: float) -> float:
    """Glass angle → XFOV (air) via −1-order grating equation."""
    s = N_BK7 * np.sin(np.radians(theta_glass_deg)) - LAMBDA_NM / PERIOD_X
    return float(np.degrees(np.arcsin(np.clip(s, -1, 1))))


# XFOV range and corresponding glass angles
XFOV_DEG    = np.linspace(-10.0, 10.0, 21)
THETA_GLASS = np.array([xfov_to_glass(t) for t in XFOV_DEG])


# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────────────
def _make_epsilon_grid(
    w_beam_nm:    float,   # beam (bar) width in x
    r_pillar_nm:  float,   # pillar radius
    x_pillar_nm:  float,   # pillar centre x  (can be > PERIOD_X/2, handled by PBC)
    period_y_nm:  float,   # y unit-cell size
    Nx: int = 200,
    Ny: int = 50,
) -> np.ndarray:
    """
    Return flattened Nx*Ny epsilon array for one metasurface unit cell.

    x ∈ [0, PERIOD_X],  y ∈ [0, period_y].
    Nano-beam  : rectangle of width w_beam centred at x=0 (periodic boundary
                 ensures wrapping: occupies x ∈ [0, w/2] ∪ [Px−w/2, Px]).
    Nano-pillar: circle of radius r_p centred at (x_p, period_y/2).
                 If x_p + r_p > PERIOD_X the circle wraps around x; grcwa
                 handles this naturally via Fourier periodicity once the grid
                 is filled with wrapped coordinates.
    """
    eps_tio2 = N_TIO2 ** 2
    eps_air  = N_AIR  ** 2

    x = np.linspace(0, PERIOD_X,  Nx, endpoint=False)
    y = np.linspace(0, period_y_nm, Ny, endpoint=False)
    XX, YY = np.meshgrid(x, y, indexing="ij")   # shape (Nx, Ny)

    grid = np.full((Nx, Ny), eps_air, dtype=complex)

    # ── nano-beam: centred at x = 0, full y-extent ──────────────────────────
    half = w_beam_nm / 2.0
    beam_mask = (XX <= half) | (XX >= PERIOD_X - half)
    grid[beam_mask] = eps_tio2

    # ── nano-pillar: centred at (x_p, period_y/2), periodic in x ─────────
    cy = period_y_nm / 2.0
    # Compute wrapped x-distance to handle circular periodicity
    dx = XX - x_pillar_nm
    dx_wrap = dx - PERIOD_X * np.round(dx / PERIOD_X)   # nearest-image in x
    dy = YY - cy
    # Also wrap in y (though usually period_y > 2*r_p for zone 1;
    # zones 2/3 may have pillar at x-boundary only)
    dy_wrap = dy - period_y_nm * np.round(dy / period_y_nm)
    dist = np.sqrt(dx_wrap ** 2 + dy_wrap ** 2)
    grid[dist < r_pillar_nm] = eps_tio2

    return grid.flatten()


# ──────────────────────────────────────────────────────────────────────────────
# Core grcwa RCWA simulation
# ──────────────────────────────────────────────────────────────────────────────
def run_rcwa(
    w_beam_nm:   float,
    r_pillar_nm: float,
    x_pillar_nm: float,
    period_y_nm: float,
    theta_glass_deg: float,
    nG: int = 51,
    Nx: int = 200,
    Ny: int = 50,
) -> tuple:
    """
    Single-angle grcwa RCWA call.

    Source: TE plane wave from glass substrate at polar angle theta_glass_deg.
    Stack (front → back in grcwa): glass | metasurface | air.

    Returns
    -------
    T_m1 : float  – η_{T,−1}(glass) = η_{T,+1}(air), first-order diffraction
    R_0  : float  – η_{R,0}(glass), zeroth-order reflection
    """
    freq = 1.0 / LAMBDA_NM          # in 1/nm (lengths in nm throughout)
    theta_rad = np.radians(theta_glass_deg)

    L1 = [PERIOD_X,    0.0        ]
    L2 = [0.0,         period_y_nm]

    obj = grcwa.obj(nG, L1, L2, freq,
                    theta=theta_rad, phi=0.0, verbose=0)

    # Layers: glass (incident) → patterned metasurface → air (exit)
    obj.Add_LayerUniform(0.0,       N_BK7  ** 2)          # substrate (semi-∞)
    obj.Add_LayerGrid   (HEIGHT_NM, Nx, Ny)               # metasurface
    obj.Add_LayerUniform(0.0,       N_AIR  ** 2 + 0j)     # air (semi-∞)

    obj.Init_Setup(Gmethod=1)    # rectangular G-vector truncation

    eps_flat = _make_epsilon_grid(w_beam_nm, r_pillar_nm,
                                  x_pillar_nm, period_y_nm, Nx, Ny)
    obj.GridLayer_geteps(eps_flat)

    # TE excitation from glass (s-amplitude = 1, p = 0)
    obj.MakeExcitationPlanewave(p_amp=0, p_phase=0,
                                s_amp=1, s_phase=0,
                                order=0, direction="forward")

    R_arr, T_arr = obj.RT_Solve(normalize=1, byorder=1)

    G = obj.G  # shape (nG_actual, 2)

    # η_{T,−1,0}: (m,n) = (−1, 0) order in air exit layer
    idx_m10 = np.where((G[:, 0] == -1) & (G[:, 1] == 0))[0]
    T_m1 = float(T_arr[idx_m10[0]]) if len(idx_m10) else 0.0

    # η_{R,0,0}: (0,0) order in glass input layer
    idx_00 = np.where((G[:, 0] == 0) & (G[:, 1] == 0))[0]
    R_0 = float(R_arr[idx_00[0]]) if len(idx_00) else 0.0

    # Clamp small numerical negatives
    T_m1 = max(T_m1, 0.0)
    R_0  = max(R_0,  0.0)
    return T_m1, R_0


# ──────────────────────────────────────────────────────────────────────────────
# Angle sweep for one zone
# ──────────────────────────────────────────────────────────────────────────────
def angle_sweep(
    params: tuple,
    theta_glass_arr: np.ndarray = THETA_GLASS,
    **rcwa_kw,
) -> tuple:
    """
    Run RCWA at each angle in theta_glass_arr.
    params = (w_beam_nm, r_pillar_nm, x_pillar_nm, period_y_nm).
    Returns (T_arr, R_arr) each shape (n_angles,).
    """
    w, r, xp, ly = params
    T_list, R_list = [], []
    for tg in theta_glass_arr:
        T, R = run_rcwa(w, r, xp, ly, tg, **rcwa_kw)
        T_list.append(T)
        R_list.append(R)
    return np.array(T_list), np.array(R_list)


# ──────────────────────────────────────────────────────────────────────────────
# Optimisation merit function
# ──────────────────────────────────────────────────────────────────────────────
def _merit(x, target_T, target_R, theta_glass_arr, zone_id, **rcwa_kw):
    """
    MSE between simulated average efficiencies and targets.
    x = [w_beam, r_pillar, x_pillar, period_y]  (all in nm, un-bounded).
    """
    w, r, xp, ly = x
    # Hard constraints
    if w < 20 or w > 300 or r < 10 or r > 250 or xp < 10 or ly < 50:
        return 1e6
    if xp > PERIOD_X + r:   # pillar entirely outside cell even with wrap
        return 1e6

    T_arr, R_arr = angle_sweep((w, r, xp, ly), theta_glass_arr, **rcwa_kw)

    # Zone 1: balance across full XFOV (weight both ends equally)
    # Zones 2, 3: optimised primarily for left end of XFOV (−10°)
    if zone_id == 0:
        # Average over full XFOV with extra weight on edges
        weights = np.ones(len(T_arr))
        weights[0]  = 3.0   # −10° end
        weights[-1] = 2.0   # +10° end
        weights /= weights.sum()
    else:
        # Weight strongly toward −10° (left end, small glass angle)
        weights = np.ones(len(T_arr))
        weights[0] = 5.0
        weights /= weights.sum()

    T_mean = float(np.dot(weights, T_arr))
    R_mean = float(np.dot(weights, R_arr))

    loss = (T_mean - target_T) ** 2 + (R_mean - target_R) ** 2
    return loss


def optimize_zone(
    zone_id:  int,
    x0:       list,
    target_T: float,
    target_R: float,
    bounds:   list = None,
    method:   str  = "Nelder-Mead",
    maxiter:  int  = 300,
    **rcwa_kw,
) -> dict:
    """
    Optimise geometry for a single zone.

    Parameters
    ----------
    zone_id  : 0, 1, or 2
    x0       : [w_beam, r_pillar, x_pillar, period_y] initial guess (nm)
    target_T : target first-order diffraction efficiency (0–1)
    target_R : target zeroth-order reflection efficiency (0–1)
    bounds   : list of (lo, hi) for each variable
    method   : scipy.optimize method
    """
    theta_arr = THETA_GLASS

    def merit(x):
        return _merit(x, target_T, target_R, theta_arr, zone_id, **rcwa_kw)

    options = {"maxiter": maxiter, "xatol": 1.0, "fatol": 1e-4}

    if method == "differential_evolution":
        if bounds is None:
            raise ValueError("bounds required for differential_evolution")
        result = differential_evolution(merit, bounds, maxiter=maxiter,
                                        tol=1e-4, seed=42, workers=1)
    else:
        result = minimize(merit, x0, method=method, options=options)

    best = result.x
    T_arr, R_arr = angle_sweep(tuple(best), theta_arr, **rcwa_kw)
    return {
        "params":  best.tolist(),
        "T_array": T_arr.tolist(),
        "R_array": R_arr.tolist(),
        "loss":    float(result.fun),
        "success": result.success,
    }


# ──────────────────────────────────────────────────────────────────────────────
# MFE  — 1D ray-tracing model
# ──────────────────────────────────────────────────────────────────────────────
def compute_coupling_efficiency(
    T_zones:  list,    # [T_arr_zone0, T_arr_zone1, T_arr_zone2]  shape (n_ang,)
    R_zones:  list,    # [R_arr_zone0, …]
    xfov_deg: np.ndarray = XFOV_DEG,
    n_x:      int = 2000,
) -> np.ndarray:
    """
    Compute coupling efficiency η_c(θ_i) using a 1-D ray-tracing model.

    For a ray entering at position x_0 in the in-coupler [0, L_total]:
      • Primary coupling: η_T(zone at x_0)  — fraction entering waveguide.
      • The trapped beam travels at angle θ_glass; TIR pitch = 2t·tan(θ_glass).
      • Each time it hits the in-coupler from below: it retains η_R(zone at x_n)
        of its power (0th-order reflection); the rest diffracts back out (loss).
    η_c(x_0) = η_T(x_0) · ∏_{n=1}^{N} η_R(x_n)   where x_n = x_0 + n·pitch,
               N = max n such that x_n < L_total.
    η_c_total(θ_i) = mean over x_0 ∈ [0, L_total].

    Returns array of coupling efficiencies, shape (n_angles,).
    """
    L      = ZONE_BOUNDS_MM[-1]                # 3.0 mm
    bounds = ZONE_BOUNDS_MM                    # [0, 1.06, 2.07, 3.0]
    x0     = np.linspace(0, L, n_x, endpoint=False)
    n_zones = len(ZONE_WIDTHS_MM)

    coupling = []
    for ai, theta_air in enumerate(xfov_deg):
        # Glass angle and TIR pitch (in mm)
        tg_rad = np.radians(xfov_to_glass(theta_air))
        pitch  = 2.0 * T_WG_MM * np.tan(tg_rad)   # mm

        # Zone index for each starting position
        zone_of = np.searchsorted(bounds[1:], x0)
        zone_of = np.clip(zone_of, 0, n_zones - 1)

        # Primary coupling: η_T of the zone at x0
        eta_c = np.array([T_zones[z][ai] for z in zone_of], dtype=float)

        # Secondary interactions: multiply by η_R for each bounce inside coupler
        # Vectorised over bounces; max bounces = ceil(L/pitch)
        if pitch > 0:
            max_bounces = int(np.ceil(L / pitch)) + 1
        else:
            max_bounces = 0

        for n in range(1, max_bounces + 1):
            xn = x0 + n * pitch
            inside = xn < L
            if not np.any(inside):
                break
            zn = np.searchsorted(bounds[1:], xn[inside])
            zn = np.clip(zn, 0, n_zones - 1)
            r_vals = np.array([R_zones[z][ai] for z in zn], dtype=float)
            eta_c[inside] *= r_vals

        coupling.append(float(np.mean(eta_c)))

    return np.array(coupling)


def compute_mfe(T_zones, R_zones, xfov_deg=XFOV_DEG):
    """Return (mfe, coupling_array)."""
    coupling = compute_coupling_efficiency(T_zones, R_zones, xfov_deg)
    mfe = float(np.min(coupling))
    return mfe, coupling


# ──────────────────────────────────────────────────────────────────────────────
# Plotting
# ──────────────────────────────────────────────────────────────────────────────
def plot_efficiency_curves(
    T_zones:   list,
    R_zones:   list,
    xfov_deg:  np.ndarray = XFOV_DEG,
    params:    list = None,
    out_path:  str = "fig3_efficiency_curves.png",
):
    """Reproduce Fig 3(d-f): efficiency vs incident angle for all 3 zones."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharey=True)

    sec_ax_labels = [f"{xfov_to_glass(t):.1f}" for t in xfov_deg[::5]]
    sec_ax_ticks  = xfov_deg[::5]

    for k, ax in enumerate(axes):
        T = np.array(T_zones[k]) * 100
        R = np.array(R_zones[k]) * 100
        S = T + R

        ax.plot(xfov_deg, T, "r-o",  ms=4, lw=1.5, label=r"$\eta_{T,+1}$ (sim)")
        ax.plot(xfov_deg, R, "b-s",  ms=4, lw=1.5, label=r"$\eta_{R,0}$ (sim)")
        ax.plot(xfov_deg, S, "k--",  ms=3, lw=1.0, label="Sum")

        if params is not None:
            w, r, xp, ly = params[k]
            ax.set_title(
                f"Zone {k+1}\n"
                f"w={w:.0f} nm, d_p={2*r:.0f} nm\n"
                f"x_p={xp:.0f} nm, Λ_y={ly:.0f} nm",
                fontsize=8,
            )
        else:
            ax.set_title(f"Zone {k+1}", fontsize=10)

        ax.set_xlabel("Incident angle (deg)", fontsize=9)
        ax.set_xlim(-10, 10)
        ax.set_ylim(0, 105)
        ax.axvline(0, color="gray", lw=0.5, ls=":")
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(True, alpha=0.3)

        # Secondary x-axis (glass angle)
        ax2 = ax.twiny()
        ax2.set_xlim(ax.get_xlim())
        ax2.set_xticks(sec_ax_ticks)
        ax2.set_xticklabels(sec_ax_labels, fontsize=6, rotation=30)
        ax2.set_xlabel("Glass angle (deg)", fontsize=7)

    axes[0].set_ylabel("Efficiency (%)", fontsize=9)
    fig.suptitle(
        f"TiO₂/N-BK7 Metasurface In-Coupler — Efficiency Curves\n"
        f"λ=532 nm, period={PERIOD_X:.0f} nm, height={HEIGHT_NM:.0f} nm",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_mfe_curve(
    coupling:  np.ndarray,
    xfov_deg:  np.ndarray = XFOV_DEG,
    mfe:       float = None,
    out_path:  str = "fig4_coupling_efficiency.png",
):
    """Reproduce Fig 4(b) cross-section: coupling efficiency vs XFOV."""
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(xfov_deg, coupling * 100, "b-o", ms=5, lw=2, label="Simulation")
    if mfe is not None:
        ax.axhline(mfe * 100, color="r", ls="--", lw=1.5,
                   label=f"MFE = {mfe*100:.1f}%")
    ax.axhline(25.3, color="g", ls=":", lw=1.5, label="Paper MFE = 25.3%")
    ax.set_xlabel("X-FOV (degrees)", fontsize=11)
    ax.set_ylabel("Coupling efficiency (%)", fontsize=11)
    ax.set_title("Three-Zone Metasurface In-Coupler — Coupling Efficiency\n"
                 "(XFOV cross-section)", fontsize=10)
    ax.set_xlim(-10, 10)
    ax.set_ylim(0, 80)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_zone_geometry(params_list, out_path="zone_geometry.png"):
    """
    Visualise the top-down epsilon map for each zone unit cell.
    """
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for k, ax in enumerate(axes):
        w, r, xp, ly = params_list[k]
        Nx, Ny = 300, 80
        eps = _make_epsilon_grid(w, r, xp, ly, Nx, Ny)
        eps_2d = eps.reshape(Nx, Ny).real
        im = ax.imshow(
            eps_2d.T,
            extent=[0, PERIOD_X, 0, ly],
            origin="lower", aspect="auto",
            cmap="RdYlBu_r", vmin=1, vmax=N_TIO2.real ** 2,
        )
        ax.set_title(
            f"Zone {k+1}\nw={w:.0f}, d_p={2*r:.0f}, x_p={xp:.0f}, Λ_y={ly:.0f} nm",
            fontsize=8,
        )
        ax.set_xlabel("x (nm)", fontsize=8)
        ax.set_ylabel("y (nm)", fontsize=8)
        fig.colorbar(im, ax=ax, label="Re(ε)")
    fig.suptitle("Unit-cell permittivity maps (top view, TiO₂ in red)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ──────────────────────────────────────────────────────────────────────────────
# Default starting geometry (from Table 1, with estimated x_p / period_y)
# ──────────────────────────────────────────────────────────────────────────────
#
# Geometry interpretation (confirmed by SEM in Fig 5 and paper text):
#   • The grating period is in x (Λ_x = 453 nm).
#   • Each unit cell has a nano-beam (running the full y-extent) and a
#     nano-pillar (circular cylinder).
#   • For zones 2 & 3 the pillar diameter d_p EXCEEDS Λ_y, so the pillar is
#     truncated at the y-boundaries, appearing as a "partial circle" in SEM.
#   • "Pillar width" w_p (Table 1) = chord length in x at the y=0 boundary:
#       w_p = 2·√(r_p² − (Λ_y/2)²)  →  Λ_y = 2·√(r_p² − (w_p/2)²)
#   • x_p (pillar centre x) is between beam right edge and PERIOD_X − beam_half,
#     estimated from figures (~200 nm from left edge for zones 2/3).

def _lambda_y_from_truncation(r_nm: float, w_p_nm: float) -> float:
    """Λ_y given pillar radius r_p and chord width w_p at y-boundary."""
    val = r_nm**2 - (w_p_nm / 2.0)**2
    return float(2.0 * np.sqrt(max(val, 0.0)))

def _x_pillar_from_truncation(r_nm, w_p_nm):
    """Legacy: x_p if truncation were in x direction (not used for Table-1 params)."""
    delta = float(np.sqrt(max(r_nm**2 - (w_p_nm/2)**2, 0)))
    return PERIOD_X - delta


# Λ_y for zones 2 & 3 from y-truncation condition (Table 1 designed values)
_LY2 = _lambda_y_from_truncation(85.0,  156.5)   # zone 2: ~66.4 nm
_LY3 = _lambda_y_from_truncation(98.0,  160.5)   # zone 3: ~112.4 nm

TABLE1_PARAMS = [
    # Zone 1: full circle (no truncation); x_p ≈ 125 nm (gap~20 nm), Λ_y ≈ 350 nm
    #   Table 1 design: w_b=110, d_p=100 — gives η_T~87%, η_R~6% at XFOV=-10°
    [110.0, 50.0,  125.0, 350.0],
    # Zone 2: Table 1 design: w_b=110, d_p=170
    #   Best x_p/Ly from grid scan targeting η_T~54%, η_R~46%
    #   xp=160, Ly=225 → η_T=48.6%, η_R=34.7% at XFOV=-10°  (R[-1,0]=14%)
    [110.0, 85.0,  160.0, 225.0],
    # Zone 3: Table 1 design: w_b=100, d_p=196
    #   Best x_p/Ly from grid scan targeting η_T~27%, η_R~73%
    #   xp=300, Ly=200 → η_T=25.7%, η_R=55.9% at XFOV=-10°  (R[-1,0]=12.3%)
    [100.0, 98.0,  300.0, 200.0],
]

# Optimisation bounds: [w_beam, r_pillar, x_pillar, period_y]
OPT_BOUNDS = [
    [(60,  200), (20, 120), ( 60, 380), (150, 600)],   # Zone 1
    [(60,  200), (50, 130), ( 80, 380), (100, 400)],   # Zone 2
    [(60,  200), (60, 150), (150, 400), (100, 400)],   # Zone 3
]
