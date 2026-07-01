#!/usr/bin/env python3
"""
Extract T and V (cell volumes) from OpenFOAM ASCII scalar fields and write T_V.csv.
Usage: python3 extract_TV.py <case_dir> <time_dir>
"""
import sys
import os
import csv

def parse_foam_scalar_field(filepath):
    """Parse OpenFOAM ASCII internalField scalar list."""
    values = []
    with open(filepath, 'r') as f:
        lines = f.readlines()

    # Find 'internalField' line
    idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('internalField'):
            idx = i
            break
    if idx is None:
        raise ValueError(f"No internalField found in {filepath}")

    # internalField uniform <val>;  or nonuniform List<scalar>
    rest = lines[idx].strip()
    if 'uniform' in rest:
        # uniform value
        val = float(rest.split('uniform')[1].strip().rstrip(';'))
        # We need the cell count — look ahead for it or return a single value marker
        # Try to get count from next nonuniform field
        return None, val  # signal uniform

    # nonuniform List<scalar>
    # Next non-empty line should be the count
    i = idx + 1
    while i < len(lines) and lines[i].strip() == '':
        i += 1
    count = int(lines[i].strip())
    i += 1  # skip '('
    while i < len(lines) and lines[i].strip() == '(':
        i += 1
    # Now read count values
    for _ in range(count):
        while i < len(lines) and lines[i].strip() == '':
            i += 1
        values.append(float(lines[i].strip()))
        i += 1
    return values, None


def main():
    if len(sys.argv) < 3:
        print("Usage: extract_TV.py <case_dir> <time_dir>")
        sys.exit(1)

    case_dir = sys.argv[1]
    time_dir = sys.argv[2]

    T_path = os.path.join(case_dir, time_dir, 'T')
    V_path = os.path.join(case_dir, time_dir, 'V')
    out_path = os.path.join(case_dir, 'T_V.csv')

    print(f"Reading T from: {T_path}")
    print(f"Reading V from: {V_path}")

    T_vals, T_uniform = parse_foam_scalar_field(T_path)
    V_vals, V_uniform = parse_foam_scalar_field(V_path)

    if T_vals is None or V_vals is None:
        print("ERROR: one of T or V is uniform — cannot build per-cell CSV")
        sys.exit(1)

    if len(T_vals) != len(V_vals):
        print(f"WARNING: T has {len(T_vals)} cells, V has {len(V_vals)} cells — truncating to min")
        n = min(len(T_vals), len(V_vals))
        T_vals = T_vals[:n]
        V_vals = V_vals[:n]

    print(f"Writing {len(T_vals)} rows to {out_path}")
    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['T', 'V'])
        for t, v in zip(T_vals, V_vals):
            writer.writerow([t, v])

    print(f"Done. T range: {min(T_vals):.4f} – {max(T_vals):.4f} K")
    print(f"      V range: {min(V_vals):.6e} – {max(V_vals):.6e} m^3")


if __name__ == '__main__':
    main()
