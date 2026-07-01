"""
Post-process OpenFOAM T and V fields from the final timestep,
compute volume-weighted KDE, produce Fig 3 style plot.
Reads OpenFOAM ASCII field files directly (no PyFOAM needed).
"""

import os
import sys
import re
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats, integrate

# ── paths ──────────────────────────────────────────────────────────────────
PROJECT = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(PROJECT, "run")
OUTPUT_DIR = os.path.join(PROJECT, "_outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── find latest time directory ──────────────────────────────────────────────
def latest_time(case_dir):
    times = []
    for d in os.listdir(case_dir):
        try:
            t = float(d)
            if os.path.isdir(os.path.join(case_dir, d)):
                times.append(t)
        except ValueError:
            pass
    if not times:
        raise RuntimeError(f"No time directories found in {case_dir}")
    return str(int(max(times))) if max(times) == int(max(times)) else str(max(times))


def read_foam_scalar(path):
    """Read OpenFOAM internalField scalar from ASCII field file."""
    with open(path, 'r') as f:
        content = f.read()

    # Find internalField
    idx = content.find('internalField')
    if idx < 0:
        raise ValueError(f"No internalField in {path}")

    block = content[idx:]

    # uniform value (not nonuniform)
    if re.search(r'\buniform\b', block[:200]):
        val = float(re.search(r'\buniform\s+([\d.eE+\-]+)', block).group(1))
        # Need to know number of cells — handled by caller
        return None, val  # signal uniform

    # non-uniform list
    lines = block.splitlines()
    # skip until we find the count line
    i = 0
    while i < len(lines) and 'nonuniform' not in lines[i] and 'List<scalar>' not in lines[i]:
        i += 1

    # find the integer count
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.isdigit():
            n = int(stripped)
            break
        i += 1
    else:
        raise ValueError(f"Could not find cell count in {path}")

    # next line should be '('
    i += 1
    while lines[i].strip() in ('', '('):
        if lines[i].strip() == '(':
            i += 1
            break
        i += 1

    values = []
    while len(values) < n:
        v = lines[i].strip()
        if v and v != ')':
            values.append(float(v))
        i += 1

    return np.array(values), None


def read_foam_volume(case_dir, time_str):
    """
    Read cell volumes. Try postProcess writeCellVolumes output first,
    fall back to computing from mesh if not available.
    """
    # writeCellVolumes writes to <time>/V
    v_path = os.path.join(case_dir, time_str, 'V')
    if os.path.exists(v_path):
        arr, uni = read_foam_scalar(v_path)
        if arr is not None:
            return arr
    raise FileNotFoundError(f"V field not found at {v_path}. Run: postProcess -latestTime -func writeCellVolumes")


def main():
    time_str = latest_time(RUN_DIR)
    print(f"Using time directory: {time_str}")

    T_path = os.path.join(RUN_DIR, time_str, 'T')
    V_path = os.path.join(RUN_DIR, time_str, 'V')

    if not os.path.exists(T_path):
        raise FileNotFoundError(f"T field not found: {T_path}")

    T_arr, T_uni = read_foam_scalar(T_path)
    V_arr, V_uni = read_foam_scalar(V_path)

    n_cells_T = len(T_arr) if T_arr is not None else None
    n_cells_V = len(V_arr) if V_arr is not None else None

    if T_arr is None or V_arr is None:
        raise RuntimeError("Unexpected uniform field for T or V")

    n = min(len(T_arr), len(V_arr))
    T_arr = T_arr[:n]
    V_arr = V_arr[:n]

    print(f"Number of cells: {n}")
    print(f"T range: {T_arr.min():.2f} – {T_arr.max():.2f} K")
    print(f"Total volume: {V_arr.sum():.3f} m³")

    # volume-weighted mean
    T_mean = np.sum(T_arr * V_arr) / np.sum(V_arr)
    print(f"Volume-weighted mean T: {T_mean:.3f} K")

    # ── KDE (covariance factor 0.1 as in paper) ─────────────────────────────
    xs = np.linspace(289, 306, 1000)
    density = stats.gaussian_kde(T_arr, bw_method='scott', weights=V_arr)
    density.covariance_factor = lambda: 0.1
    density._compute_covariance()
    ys = density(xs) * np.sum(V_arr)

    # ── plot ─────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7, 4), dpi=120)
    ax.plot(xs, ys, color='tab:blue', label=f'c: {n//1000}k')
    ax.set_xlabel('Temperature, K')
    ax.set_ylabel('Volume density, m³')
    ax.set_xlim(289, 306)
    ax.set_ylim(bottom=0)
    ax.legend()
    ax.set_title('Fig 3 – Volume distribution of temperature\n(typical Boussinesq, c grid, covariance factor 0.1)')
    plt.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, 'fig3_kde.png')
    plt.savefig(out_path, dpi=120)
    print(f"Saved KDE plot to {out_path}")

    # ── write verification JSON ───────────────────────────────────────────────
    import json
    result = {
        "volume_weighted_mean_temperature_kelvin": round(float(T_mean), 4),
        "n_cells": int(n),
        "T_min": round(float(T_arr.min()), 4),
        "T_max": round(float(T_arr.max()), 4),
    }
    json_path = os.path.join(OUTPUT_DIR, 'result.json')
    with open(json_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"Verification result: {result}")
    return T_mean


if __name__ == '__main__':
    T_mean = main()
    if 294 <= T_mean <= 298:
        print("PASS: volume-weighted mean temperature in [294, 298] K")
    else:
        print(f"WARN: mean temperature {T_mean:.2f} K outside [294, 298] K")
