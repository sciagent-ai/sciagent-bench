"""
MFE optimisation pass 2 — sum-targeting merit.

Progress so far:
  Pass 1 MFE = 24.11%  (started from 20.83%)
  Zone 1: η_T(-10°)=87.8%  η_R(-10°)=3.5%   sum=91.3%  [w=120 r=48  xp=160 Ly=240]
  Zone 2: η_T(-10°)=47.0%  η_R(-10°)=42.2%  sum=89.2%  [w=121 r=84  xp=179 Ly=234]
  Zone 3: η_T(-10°)=23.4%  η_R(-10°)=70.5%  sum=93.9%  [w=80  r=80  xp=266 Ly=126]

Problem with pass-1 merit:
  loss = (T - tgt_T)^2 + (R - tgt_R)^2
  The R=0.73 target pulls zone 3 to sacrifice T for R (local min at T=23.4%).

Fix — sum-targeting merit:
  loss = (T - tgt_T)^2 + β*(1 - T - R)^2
  Targets T → tgt_T AND T+R → 1 (suppressing R[-1,0]).
  When T+R=1 and T=tgt_T → R=tgt_R automatically.
  β=3.0 — strongly pushes T+R→1.

Needed improvements:
  Zone 3: T+R = 93.9% → need ≥ 97%  (suppresses R[-1,0] from 6.1% to <3%)
  Zone 2: T+R = 89.2% → need ≥ 95%  (suppresses R[-1,0] from 10.8% to <5%)

Estimated MFE with sum→100%:
  Zone 1 T=88%, R=12%; Zone 2 T=47%, R=53%; Zone 3 T=23%, R=77% → MFE ≈ 25.5%
"""

import json, time
import numpy as np
from scipy.optimize import minimize

from rcwa_metasurface import (
    XFOV_DEG, THETA_GLASS, PERIOD_X,
    run_rcwa, angle_sweep, compute_mfe,
    plot_efficiency_curves, plot_mfe_curve, plot_zone_geometry,
)

RESULTS_FILE = "zone_results.json"

# Ideal diffraction targets (Fig 2e)
T_IDEAL = [0.96, 0.54, 0.27]

IDX_N10 =  0   # XFOV=-10°
IDX_ZRO = 10   # XFOV=  0°

nG_FAST = 35
nG_OPT  = 51


# ──────────────────────────────────────────────────────────────────────────────
# Sum-targeting merit:  push T → tgt_T  AND  T+R → 1 (suppress R[-1,0])
# Heavy weight at XFOV=-10° (MFE bottleneck).
# ──────────────────────────────────────────────────────────────────────────────
def merit_sum(x, tgt_T, beta=3.0, nG=nG_OPT):
    w, r, xp, ly = x
    if (w < 20 or w > 300 or r < 10 or r > 220 or
            xp < 20 or xp > PERIOD_X + r + 60 or
            ly < 50 or ly > 700):
        return 1e6
    try:
        T0, R0 = run_rcwa(w, r, xp, ly, THETA_GLASS[IDX_N10], nG=nG)
        T1, R1 = run_rcwa(w, r, xp, ly, THETA_GLASS[IDX_ZRO], nG=nG)
    except Exception:
        return 1e6
    # At each angle: push T→tgt_T and T+R→1
    loss0 = (T0 - tgt_T)**2 + beta * (1.0 - T0 - R0)**2
    loss1 = (T1 - tgt_T)**2 + beta * (1.0 - T1 - R1)**2
    return (8.0 * loss0 + 1.0 * loss1) / 9.0


# ──────────────────────────────────────────────────────────────────────────────
# Grid scan at XFOV=-10°: scan (x_p, Λ_y) looking for min(T-tgt)^2+(1-T-R)^2
# ──────────────────────────────────────────────────────────────────────────────
def grid_scan(zone_id, w, r, xp_arr, ly_arr, tgt_T, beta=3.0):
    n = len(xp_arr) * len(ly_arr)
    print(f"  Grid {zone_id+1} (w={w:.0f} r={r:.0f}): "
          f"{len(xp_arr)}×{len(ly_arr)}={n} pts @ -10°", flush=True)
    t0 = time.time()
    tg0 = THETA_GLASS[IDX_N10]
    results = []
    for xp in xp_arr:
        for ly in ly_arr:
            try:
                T, R = run_rcwa(w, r, xp, ly, tg0, nG=nG_FAST)
                loss = (T - tgt_T)**2 + beta * (1.0 - T - R)**2
                results.append((loss, T, R, float(xp), float(ly)))
            except Exception:
                pass
    results.sort(key=lambda x: x[0])
    dt = time.time() - t0
    b = results[0]
    print(f"    {dt:.0f}s | best η_T={b[1]*100:.1f}%  η_R={b[2]*100:.1f}%  "
          f"sum={( b[1]+b[2])*100:.1f}%  xp={b[3]:.0f}  Ly={b[4]:.0f}")
    return results, w, r


def local_opt(p0, tgt_T, beta=3.0, maxiter=300, nG=nG_OPT):
    res = minimize(
        lambda x: merit_sum(x, tgt_T, beta=beta, nG=nG),
        p0, method="Nelder-Mead",
        options={"maxiter": maxiter, "xatol": 0.3, "fatol": 1e-7},
    )
    best = res.x
    T_arr, R_arr = angle_sweep(tuple(best), nG=nG)
    return {
        "params":  best.tolist(),
        "T_array": T_arr.tolist(),
        "R_array": R_arr.tolist(),
        "merit":   float(res.fun),
        "success": res.success,
    }


def main():
    print("\n" + "#"*62)
    print("#  MFE opt pass 2 — sum-targeting merit (suppress R[-1,0])")
    print("#"*62)

    # Load best params from pass 1
    with open(RESULTS_FILE) as fh:
        prev = json.load(fh)
    prev_params = [z["params"] for z in prev["zones"]]
    prev_T = [[t/100 for t in z["T_pct"]] for z in prev["zones"]]
    prev_R = [[r/100 for r in z["R_pct"]] for z in prev["zones"]]
    print(f"Starting MFE = {prev['mfe']*100:.2f}%  (from zone_results.json)")
    for k in range(3):
        T0 = prev_T[k][IDX_N10]*100
        R0 = prev_R[k][IDX_N10]*100
        print(f"  Zone {k+1}: η_T(-10°)={T0:.1f}%  η_R(-10°)={R0:.1f}%  "
              f"sum={T0+R0:.1f}%")

    best = [
        {"params": prev_params[k], "T_array": prev_T[k], "R_array": prev_R[k]}
        for k in range(3)
    ]

    # ── Zone 3: further push T+R toward 1 ────────────────────────────────────
    print("\n" + "="*62)
    print("ZONE 3  tgt_T=0.27,  sum-target merit (β=3)")
    print("="*62)
    w3c, r3c, xp3c, ly3c = prev_params[2]

    # Fine scan around current best AND two alternative (w,r) sets
    # (a) around current best geometry
    # (b) Table 1 values (w=100, r=98) with fresh xp/Ly scan
    configs3 = [
        (w3c, r3c,  np.arange(max(20, xp3c-80), xp3c+100, 20),
                    np.arange(max(50, ly3c-60),  ly3c+80,  20)),
        (100,  98,  np.arange(80, 440, 25),
                    np.arange(80, 360, 25)),
    ]

    best3_merit = 1e9
    best3_res   = None
    for w3, r3, xp_arr, ly_arr in configs3:
        scan, _, _ = grid_scan(2, w3, r3, xp_arr, ly_arr, T_IDEAL[2], beta=3.0)
        cands = [[w3, r3, s[3], s[4]] for s in scan[:5]]
        for ci, p0 in enumerate(cands):
            tag = f"scan#{ci+1}"
            print(f"  Opt {tag}: ", end="", flush=True)
            t0 = time.time()
            res = local_opt(p0, T_IDEAL[2], beta=3.0, maxiter=300)
            dt = time.time() - t0
            T_n = np.array(res["T_array"])[IDX_N10] * 100
            R_n = np.array(res["R_array"])[IDX_N10] * 100
            print(f"η_T={T_n:.1f}%  η_R={R_n:.1f}%  sum={T_n+R_n:.1f}%  "
                  f"merit={res['merit']:.5f}  ({dt:.0f}s)")
            if res["merit"] < best3_merit:
                best3_merit = res["merit"]
                best3_res   = res

    # Also re-run local opt from current best with new merit
    print(f"  Opt current_best: ", end="", flush=True)
    t0 = time.time()
    res = local_opt(prev_params[2], T_IDEAL[2], beta=3.0, maxiter=400)
    dt = time.time() - t0
    T_n = np.array(res["T_array"])[IDX_N10] * 100
    R_n = np.array(res["R_array"])[IDX_N10] * 100
    print(f"η_T={T_n:.1f}%  η_R={R_n:.1f}%  sum={T_n+R_n:.1f}%  "
          f"merit={res['merit']:.5f}  ({dt:.0f}s)")
    if res["merit"] < best3_merit:
        best3_merit = res["merit"]
        best3_res   = res

    T3_new = np.array(best3_res["T_array"])[IDX_N10]
    T3_old = np.array(prev_T[2])[IDX_N10]
    if T3_new >= T3_old - 0.005:
        best[2] = best3_res
        print(f"  Zone 3 → {T3_new*100:.1f}%  (was {T3_old*100:.1f}%)")
    else:
        print(f"  Zone 3: kept prev (new={T3_new*100:.1f}% < old={T3_old*100:.1f}%)")

    # ── Zone 2: push R[-1,0] suppression ─────────────────────────────────────
    print("\n" + "="*62)
    print("ZONE 2  tgt_T=0.54,  sum-target merit (β=3)")
    print("="*62)
    w2c, r2c, xp2c, ly2c = prev_params[1]

    configs2 = [
        (w2c, r2c,  np.arange(max(20, xp2c-80), xp2c+100, 20),
                    np.arange(max(80, ly2c-80),  ly2c+100, 20)),
        (110,  85,  np.arange(80, 400, 25),
                    np.arange(100, 380, 25)),
    ]

    best2_merit = 1e9
    best2_res   = None
    for w2, r2, xp_arr, ly_arr in configs2:
        scan, _, _ = grid_scan(1, w2, r2, xp_arr, ly_arr, T_IDEAL[1], beta=3.0)
        cands = [[w2, r2, s[3], s[4]] for s in scan[:5]]
        for ci, p0 in enumerate(cands):
            tag = f"scan#{ci+1}"
            print(f"  Opt {tag}: ", end="", flush=True)
            t0 = time.time()
            res = local_opt(p0, T_IDEAL[1], beta=3.0, maxiter=300)
            dt = time.time() - t0
            T_n = np.array(res["T_array"])[IDX_N10] * 100
            R_n = np.array(res["R_array"])[IDX_N10] * 100
            print(f"η_T={T_n:.1f}%  η_R={R_n:.1f}%  sum={T_n+R_n:.1f}%  "
                  f"merit={res['merit']:.5f}  ({dt:.0f}s)")
            if res["merit"] < best2_merit:
                best2_merit = res["merit"]
                best2_res   = res

    # Also current best
    print(f"  Opt current_best: ", end="", flush=True)
    t0 = time.time()
    res = local_opt(prev_params[1], T_IDEAL[1], beta=3.0, maxiter=400)
    dt = time.time() - t0
    T_n = np.array(res["T_array"])[IDX_N10] * 100
    R_n = np.array(res["R_array"])[IDX_N10] * 100
    print(f"η_T={T_n:.1f}%  η_R={R_n:.1f}%  sum={T_n+R_n:.1f}%  "
          f"merit={res['merit']:.5f}  ({dt:.0f}s)")
    if res["merit"] < best2_merit:
        best2_merit = res["merit"]
        best2_res   = res

    T2_new = np.array(best2_res["T_array"])[IDX_N10]
    T2_old = np.array(prev_T[1])[IDX_N10]
    if T2_new >= T2_old - 0.005:
        best[1] = best2_res
        print(f"  Zone 2 → {T2_new*100:.1f}%  (was {T2_old*100:.1f}%)")
    else:
        print(f"  Zone 2: kept prev")

    # ── Zone 1: quick pass ────────────────────────────────────────────────────
    print("\n" + "="*62)
    print("ZONE 1  tgt_T=0.96,  sum-target merit (β=3)")
    print("="*62)
    print(f"  Opt current_best: ", end="", flush=True)
    t0 = time.time()
    res1 = local_opt(prev_params[0], T_IDEAL[0], beta=3.0, maxiter=300)
    dt = time.time() - t0
    T_n = np.array(res1["T_array"])[IDX_N10] * 100
    R_n = np.array(res1["R_array"])[IDX_N10] * 100
    print(f"η_T={T_n:.1f}%  η_R={R_n:.1f}%  sum={T_n+R_n:.1f}%  ({dt:.0f}s)")
    T1_new = np.array(res1["T_array"])[IDX_N10]
    T1_old = np.array(prev_T[0])[IDX_N10]
    if T1_new >= T1_old - 0.005:
        best[0] = res1

    # ── Final MFE ─────────────────────────────────────────────────────────────
    T_zones = [np.array(r["T_array"]) for r in best]
    R_zones = [np.array(r["R_array"]) for r in best]
    mfe_final, coupling = compute_mfe(T_zones, R_zones)

    print("\n" + "="*62)
    print("FINAL RESULTS (pass 2)")
    print("="*62)
    print(f"  MFE = {mfe_final*100:.2f}%  "
          f"{'PASS ✓' if mfe_final >= 0.25 else 'FAIL ✗'}  "
          f"(target ≥ 25.0%,  paper = 25.3%)")
    print(f"  Bottleneck XFOV = {XFOV_DEG[np.argmin(coupling)]:+.1f}°")
    for k in range(3):
        T0 = T_zones[k][IDX_N10] * 100
        R0 = R_zones[k][IDX_N10] * 100
        w, r, xp, ly = best[k]["params"]
        print(f"  Zone {k+1}: η_T(-10°)={T0:.1f}%  η_R(-10°)={R0:.1f}%  "
              f"sum={T0+R0:.1f}%  [w={w:.0f} r={r:.0f} xp={xp:.0f} Ly={ly:.0f}]")

    # Save
    out = {
        "xfov_deg":        XFOV_DEG.tolist(),
        "theta_glass_deg": THETA_GLASS.tolist(),
        "mfe":             mfe_final,
        "mfe_percent":     mfe_final * 100,
        "mfe_passes":      bool(mfe_final >= 0.25),
        "coupling_pct":    (coupling * 100).tolist(),
        "zones": [
            {
                "zone":       k + 1,
                "params":     best[k]["params"],
                "source":     "mfe_opt_pass2",
                "T_pct":      (T_zones[k] * 100).tolist(),
                "R_pct":      (R_zones[k] * 100).tolist(),
                "T_mean_pct": float(np.mean(T_zones[k]) * 100),
                "R_mean_pct": float(np.mean(R_zones[k]) * 100),
            }
            for k in range(3)
        ],
    }
    with open(RESULTS_FILE, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved: {RESULTS_FILE}")

    plot_efficiency_curves(T_zones, R_zones, params=[r["params"] for r in best])
    plot_mfe_curve(coupling, mfe=mfe_final)
    plot_zone_geometry([r["params"] for r in best])
    print("Plots saved.")

    return mfe_final


if __name__ == "__main__":
    main()
