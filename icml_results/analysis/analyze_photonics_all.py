"""Sweep every photonics cell in icml_results and emit one comparison table.

Cell discovery: enumerate `icml_results/*/photonics/photonics__*/`. Classify
adapter by cell-id substring (`__sciagent` → sciagent, else cc-bare, matching
the same convention `reverify_cells.py::_adapter_of` uses). Skip anything
that doesn't have the expected artifacts on disk (a run killed before
`stdout.txt` / `provenance.jsonl` landed).

For each cell:
  - cc-bare cells: analyze_cc_bare() from analyze_pair.py (parses stdout.txt).
  - sciagent cells: analyze_sciagent() from analyze_pair.py (parses
    provenance.jsonl + recursively walks child sessions).

Output: `icml_results/reports/photonics_all.md` — one wide markdown table,
one row per cell, plus a CSV mirror for programmatic consumption.

Intentionally NOT touched: the per-cell rollup functions live in
analyze_pair.py, unchanged. This file is only orchestration + row assembly.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))

from analyze_pair import analyze_cc_bare, analyze_sciagent  # noqa: E402


ICML = _THIS.parent.parent


def _is_sciagent(cell_id: str) -> bool:
    # Same rule reverify uses: "__sciagent" anywhere in cell id → sciagent
    # adapter; everything else (cc-bare, cc-sky-registry) → claude_code.
    return "__sciagent" in cell_id


def discover_photonics_cells(icml_root: Path) -> list[Path]:
    cells: list[Path] = []
    for ts_dir in sorted(icml_root.iterdir()):
        if not ts_dir.is_dir():
            continue
        task_dir = ts_dir / "photonics"
        if not task_dir.exists():
            continue
        for cell in sorted(task_dir.iterdir()):
            if not cell.is_dir():
                continue
            if not cell.name.startswith("photonics__"):
                continue
            cells.append(cell)
    return cells


def _cc_row(cell_dir: Path) -> dict:
    r = analyze_cc_bare(cell_dir)
    # cc-bare stores duration in ms (from Claude Code's `duration_ms`); the
    # main-agent model id lives on the `model_init` system event.
    duration_ms = r.get("duration_ms") or 0
    return {
        "ts":            cell_dir.parent.parent.name,
        "cell_id":       cell_dir.name,
        "adapter":       "cc-bare",
        "main_model":    r.get("model_init") or "",
        "iterations":    r.get("num_turns", ""),
        "wall_seconds":  f"{duration_ms / 1000.0:.1f}",
        "tool_calls":    sum(r.get("tool_uses", {}).values()),
        "tokens_in":     r.get("input_tokens", 0)
                         + r.get("cache_creation_input_tokens", 0)
                         + r.get("cache_read_input_tokens", 0),
        "tokens_out":    r.get("output_tokens", 0),
        "llm_cost_usd":  f"{r.get('total_cost_usd', 0.0):.4f}",
        "compute_cost_usd": "0.0000",
        "n_subagents":   0,
        "n_compute_jobs": 0,
        "n_sessions":    1,
    }


def _sci_row(cell_dir: Path) -> dict:
    r = analyze_sciagent(cell_dir)
    n_sessions = len(r.get("per_session_rollup", {}) or {})
    return {
        "ts":            cell_dir.parent.parent.name,
        "cell_id":       cell_dir.name,
        "adapter":       "sciagent",
        "main_model":    r.get("model_main") or "",
        "iterations":    r.get("total_iterations", 0),
        "wall_seconds":  f"{r.get('wall_seconds', 0.0):.1f}",
        "tool_calls":    sum(r.get("tool_calls", {}).values()),
        "tokens_in":     r.get("total_tokens_in", 0),
        "tokens_out":    r.get("total_tokens_out", 0),
        "llm_cost_usd":  f"{r.get('total_llm_cost_usd', 0.0):.4f}",
        "compute_cost_usd": f"{r.get('compute_cost_usd', 0.0):.4f}",
        "n_subagents":   len(r.get("subagent_rollups", []) or []),
        "n_compute_jobs": r.get("n_compute_jobs", 0),
        "n_sessions":    n_sessions,
    }


def analyze_cell(cell_dir: Path) -> dict | None:
    try:
        if _is_sciagent(cell_dir.name):
            if not (cell_dir / "provenance.jsonl").exists():
                return None
            return _sci_row(cell_dir)
        else:
            if not (cell_dir / "stdout.txt").exists():
                return None
            return _cc_row(cell_dir)
    except Exception as e:
        # Corrupt cell — flag but keep going.
        return {
            "ts": cell_dir.parent.parent.name,
            "cell_id": cell_dir.name,
            "adapter": "sciagent" if _is_sciagent(cell_dir.name) else "cc-bare",
            "main_model": "",
            "iterations": "",
            "wall_seconds": "",
            "tool_calls": "",
            "tokens_in": "",
            "tokens_out": "",
            "llm_cost_usd": "",
            "compute_cost_usd": "",
            "n_subagents": "",
            "n_compute_jobs": "",
            "n_sessions": "",
            "error": f"{type(e).__name__}: {e}",
        }


FIELDS = [
    "ts", "cell_id", "adapter", "main_model",
    "iterations", "wall_seconds", "tool_calls",
    "tokens_in", "tokens_out",
    "llm_cost_usd", "compute_cost_usd",
    "n_subagents", "n_compute_jobs", "n_sessions",
]


def write_csv(rows: list[dict], path: Path) -> None:
    fields = FIELDS + (["error"] if any(r.get("error") for r in rows) else [])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def write_markdown(rows: list[dict], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Photonics — all runs, side by side")
    lines.append("")
    lines.append(f"Total cells: {len(rows)}. Sources under `icml_results/*/photonics/`.")
    lines.append("")
    lines.append(
        "Sciagent rows are the recursive rollup: parent session + every "
        "child session referenced via `subagent_completed.child_session_id`. "
        "cc-bare rows come from `stdout.txt` (Claude Code's session summary). "
        "Compute cost is `sky.cost_report()` for the cluster referenced by "
        "the first `compute_job_launched` event (empty when the run stayed "
        "local)."
    )
    lines.append("")
    header = ("| " + " | ".join(FIELDS) + " |")
    align  = ("|" + "|".join(":---" if f in ("ts","cell_id","adapter","main_model") else "---:" for f in FIELDS) + "|")
    lines.append(header)
    lines.append(align)
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(f, "")) for f in FIELDS) + " |")
    lines.append("")
    err_rows = [r for r in rows if r.get("error")]
    if err_rows:
        lines.append("## Errors")
        lines.append("")
        for r in err_rows:
            lines.append(f"- `{r['ts']}/{r['cell_id']}`: {r['error']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML,
                    help=f"Root icml_results dir (default: {ICML})")
    ap.add_argument("--out-dir",   type=Path, default=ICML / "reports",
                    help="Where to write photonics_all.{md,csv}")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cells = discover_photonics_cells(args.icml_root)
    if not cells:
        print(f"no photonics cells found under {args.icml_root}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    for cell in cells:
        print(f"→ {cell.parent.parent.name}/{cell.name}", flush=True)
        row = analyze_cell(cell)
        if row is None:
            print(f"  skipped (missing artifacts)")
            continue
        if row.get("error"):
            print(f"  ERROR: {row['error']}")
        rows.append(row)

    csv_path = args.out_dir / "photonics_all.csv"
    md_path  = args.out_dir / "photonics_all.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)
    print()
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
