"""
End-to-end runner for the three-zone TiO2/N-BK7 metasurface in-coupler.

Steps
-----
1. Start from Table 1 geometry (paper's designed values).
2. Run a quick local optimisation (Nelder-Mead) for each zone to push
   efficiencies toward per-zone targets.
3. Sweep incident angles and generate efficiency curves (Fig 3 style).
4. Calculate MFE using 1-D ray-tracing model.
5. Save results to JSON and PNG plots.
"""

import json, time, os
import numpy as np
from rcwa_metasurface import (
    XFOV_DEG, THETA_GLASS, TABLE1_PARAMS, OPT_BOUNDS,
    REALISTIC_TARGETS, IDEAL_TARGETS,
    N_BK7, N_TIO2, PERIOD_X, HEIGHT_NM,
    angle_sweep, optimize_zone, compute_mfe,
    plot_efficiency_curves, plot_mfe_curve, plot_zone_geometry,
    _x_pillar_from_truncation,
)

RESULTS_FILE = "zone_results.json"


# ──────────────────────────────────────────────────────────────────────────────
# Helper: print a compact summary for one zone
# ──────────────────────────────────────────────────────────────────────────────
def _summarise(zone_id, params, T_arr, R_arr):
    w, r, xp, ly = params
    print(f"\n  Zone {zone_id+1}  w_beam={w:.1f} nm  r_pillar={r:.1f} nm  "
          f"x_pillar={xp:.1f} nm  Λ_y={ly:.1f} nm")
    print(f"  {'XFOV':>6}  {'θ_glass':>8}  {'η_T(%)':>8}  {'η_R(%)':>8}  {'Sum(%)':>8}")
    for i, (ta, tg, T, R) in enumerate(
            zip(XFOV_DEG, THETA_GLASS, T_arr, R_arr)):
        if i % 4 == 0 or i in (0, len(XFOV_DEG)-1):
            print(f"  {ta:+6.1f}°  {tg:8.2f}°  {T*100:8.2f}  {R*100:8.2f}  {(T+R)*100:8.2f}")


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: run angle sweep with Table 1 initial geometry
# ──────────────────────────────────────────────────────────────────────────────
def stage_initial_sweep():
    print("\n" + "="*60)
    print("STAGE 1  —  Table 1 geometry angle sweep")
    print("="*60)

    results = []
    for k, p0 in enumerate(TABLE1_PARAMS):
        print(f"\nZone {k+1}: sweeping {len(THETA_GLASS)} angles …", end=" ", flush=True)
        t0 = time.time()
        T_arr, R_arr = angle_sweep(tuple(p0), nG=51)
        dt = time.time() - t0
        print(f"done in {dt:.1f}s")
        _summarise(k, p0, T_arr, R_arr)
        results.append({
            "zone": k+1, "params": p0,
            "T_array": T_arr.tolist(), "R_array": R_arr.tolist(),
        })
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: local optimisation for each zone
# ──────────────────────────────────────────────────────────────────────────────
def stage_optimise(initial_results):
    print("\n" + "="*60)
    print("STAGE 2  —  Per-zone local optimisation (Nelder-Mead)")
    print("="*60)

    opt_results = []
    for k in range(3):
        tgt_T, tgt_R = REALISTIC_TARGETS[k]
        p0 = initial_results[k]["params"]

        print(f"\nZone {k+1}  target η_T={tgt_T*100:.0f}%  η_R={tgt_R*100:.0f}% …",
              end=" ", flush=True)
        t0 = time.time()

        res = optimize_zone(
            zone_id   = k,
            x0        = list(p0),
            target_T  = tgt_T,
            target_R  = tgt_R,
            method    = "Nelder-Mead",
            maxiter   = 250,
            nG        = 51,
        )
        dt = time.time() - t0
        print(f"done in {dt:.1f}s   loss={res['loss']:.5f}   success={res['success']}")

        T_arr = np.array(res["T_array"])
        R_arr = np.array(res["R_array"])
        _summarise(k, res["params"], T_arr, R_arr)
        opt_results.append(res)

    return opt_results


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3: coarse differential-evolution (optional, if local opt is poor)
# ──────────────────────────────────────────────────────────────────────────────
def stage_global_opt(zone_id, initial_params):
    """
    Run differential evolution for one zone if requested.
    This is slower (~few minutes) but more thorough.
    """
    tgt_T, tgt_R = REALISTIC_TARGETS[zone_id]
    print(f"\nGlobal opt zone {zone_id+1}: target η_T={tgt_T*100:.0f}% η_R={tgt_R*100:.0f}%")
    bounds = OPT_BOUNDS[zone_id]
    res = optimize_zone(
        zone_id  = zone_id,
        x0       = initial_params,
        target_T = tgt_T,
        target_R = tgt_R,
        bounds   = bounds,
        method   = "differential_evolution",
        maxiter  = 80,
        nG       = 35,    # fewer harmonics for speed
    )
    return res


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4: MFE calculation and plotting
# ──────────────────────────────────────────────────────────────────────────────
def stage_mfe_and_plots(zone_results):
    print("\n" + "="*60)
    print("STAGE 4  —  MFE calculation and plots")
    print("="*60)

    T_zones = [np.array(r["T_array"]) for r in zone_results]
    R_zones = [np.array(r["R_array"]) for r in zone_results]
    params_list = [r["params"] for r in zone_results]

    mfe, coupling = compute_mfe(T_zones, R_zones)

    print(f"\n  MFE = {mfe*100:.2f}%  (paper: 25.3%,  target: ≥ 25%)")
    print(f"  Coupling efficiency range: "
          f"{coupling.min()*100:.1f}% – {coupling.max()*100:.1f}%")
    print(f"  MFE occurs at XFOV = {XFOV_DEG[np.argmin(coupling)]:+.1f}°")

    # Print per-angle coupling
    print("\n  XFOV  η_coupling")
    for ta, ec in zip(XFOV_DEG, coupling):
        flag = " ← MFE" if ec == coupling.min() else ""
        print(f"  {ta:+5.1f}°  {ec*100:6.2f}%{flag}")

    # Per-zone summary at worst-case angle
    wc_idx = int(np.argmin(coupling))
    print(f"\n  Zone efficiencies at worst-case XFOV = {XFOV_DEG[wc_idx]:+.1f}°:")
    for k in range(3):
        T = T_zones[k][wc_idx] * 100
        R = R_zones[k][wc_idx] * 100
        w, r, xp, ly = params_list[k]
        print(f"    Zone {k+1}:  η_T={T:5.1f}%  η_R={R:5.1f}%  sum={T+R:5.1f}%"
              f"  (w={w:.0f}, r={r:.0f}, xp={xp:.0f}, Λy={ly:.0f})")

    # Plots
    plot_efficiency_curves(T_zones, R_zones, params=params_list)
    plot_mfe_curve(coupling, mfe=mfe)
    plot_zone_geometry(params_list)

    return mfe, coupling


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "#"*60)
    print("#  TiO2/N-BK7 Metasurface In-Coupler RCWA Reproduction")
    print(f"#  λ={532} nm  period={PERIOD_X:.0f} nm  height={HEIGHT_NM:.0f} nm")
    print(f"#  N_BK7={N_BK7:.4f}  N_TiO2={N_TIO2.real:.3f}+{N_TIO2.imag:.4f}i")
    print("#"*60)

    # ── Step 1: initial sweep with Table 1 values ────────────────────────
    init_results = stage_initial_sweep()

    # ── Step 2: local optimisation ───────────────────────────────────────
    opt_results = stage_optimise(init_results)

    # ── Step 3: select best between initial and optimised ────────────────
    final_results = []
    for k in range(3):
        # Keep whichever has lower loss vs realistic target
        tgt_T, tgt_R = REALISTIC_TARGETS[k]
        def loss_of(r):
            T = np.array(r["T_array"])
            R = np.array(r["R_array"])
            return (T.mean() - tgt_T)**2 + (R.mean() - tgt_R)**2

        if loss_of(opt_results[k]) < loss_of(init_results[k]):
            chosen = opt_results[k]
            src = "optimised"
        else:
            chosen = init_results[k]
            src = "Table-1 initial"
        chosen["source"] = src
        final_results.append(chosen)
        print(f"\nZone {k+1}: using {src} geometry")

    # ── Step 4: MFE and plots ─────────────────────────────────────────────
    mfe, coupling = stage_mfe_and_plots(final_results)

    # ── Save results ──────────────────────────────────────────────────────
    out = {
        "xfov_deg":       XFOV_DEG.tolist(),
        "theta_glass_deg": THETA_GLASS.tolist(),
        "mfe":            mfe,
        "mfe_percent":    mfe * 100,
        "mfe_passes":     bool(mfe >= 0.25),
        "coupling_pct":   (coupling * 100).tolist(),
        "zones": [
            {
                "zone":    k + 1,
                "params":  final_results[k]["params"],
                "source":  final_results[k].get("source", ""),
                "T_pct":   (np.array(final_results[k]["T_array"]) * 100).tolist(),
                "R_pct":   (np.array(final_results[k]["R_array"]) * 100).tolist(),
                "T_mean_pct": float(np.mean(final_results[k]["T_array"]) * 100),
                "R_mean_pct": float(np.mean(final_results[k]["R_array"]) * 100),
            }
            for k in range(3)
        ],
    }

    with open(RESULTS_FILE, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nResults saved to {RESULTS_FILE}")

    # ── Final verdict ─────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"  MFE = {mfe*100:.2f}%  {'PASS ✓' if mfe >= 0.25 else 'FAIL ✗'}"
          f"  (target ≥ 25.0%,  paper = 25.3%)")
    print(f"  Coupling range:  {coupling.min()*100:.1f}% – {coupling.max()*100:.1f}%")
    for k in range(3):
        z = out["zones"][k]
        w, r, xp, ly = z["params"]
        print(f"  Zone {k+1}: η_T_avg={z['T_mean_pct']:.1f}%  η_R_avg={z['R_mean_pct']:.1f}%"
              f"  |  w={w:.0f} nm  r={r:.0f} nm  xp={xp:.0f} nm  Λy={ly:.0f} nm")


if __name__ == "__main__":
    main()
