"""Cross-task cc-bare vs sciagent-verifier-on-default comparison.

Six cells across three tasks (photonics / brca1_fitness_structure / cfd_fig3_kde),
each with the pair (cc-bare, sciagent-verifier-on-default). Uses the same
rollup functions as analyze_pair.py / analyze_photonics_all.py — no duplication.

Cell discovery: hard-coded pointers (`_CELLS`) because the cells for this
comparison live across four different TS dirs. Fixed layout keeps this
explicit — every cell used in the paper table is one line here.

Output: `icml_results/reports/cc_vs_sciagent_default.md` — one wide table
comparing the pair per task, plus a CSV mirror.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))

from analyze_photonics_all import _cc_row, _sci_row, FIELDS as BASE_FIELDS  # noqa: E402


ICML = _THIS.parent.parent


# One entry per (task, adapter) pair. The `ts` picks which TS dir the cell
# lives in — photonics's cc-bare wasn't rerun in June, so it points at the
# 2026-06-08 dir. Everything else is a fresh 2026-06-30 run.
_CELLS = [
    # photonics
    ("photonics", "cc-bare",
     "20260608T200907Z", "photonics__cc-bare__sonnet"),
    ("photonics", "sciagent-verifier-on-default",
     "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet"),
    # brca1_fitness_structure
    ("brca1_fitness_structure", "cc-bare",
     "20260630T135609Z", "brca1_fitness_structure__cc-bare__sonnet"),
    ("brca1_fitness_structure", "sciagent-verifier-on-default",
     "20260630T135609Z", "brca1_fitness_structure__sciagent-verifier-on-default__sonnet"),
    # cfd_fig3_kde
    ("cfd_fig3_kde", "cc-bare",
     "20260630T184838Z", "cfd_fig3_kde__cc-bare__sonnet"),
    ("cfd_fig3_kde", "sciagent-verifier-on-default",
     "20260630T184838Z", "cfd_fig3_kde__sciagent-verifier-on-default__sonnet"),
]


FIELDS = ["task", "condition"] + [f for f in BASE_FIELDS if f not in ("ts",)]


def _cell_dir(icml_root: Path, task: str, ts: str, cell_id: str) -> Path:
    return icml_root / ts / task / cell_id


def build_row(icml_root: Path, task: str, condition: str, ts: str, cell_id: str) -> dict:
    cell_dir = _cell_dir(icml_root, task, ts, cell_id)
    if not cell_dir.exists():
        return {
            "task": task, "condition": condition, "cell_id": cell_id,
            "adapter": condition,
            "error": f"cell dir missing: {cell_dir}",
        }
    if condition == "cc-bare":
        row = _cc_row(cell_dir)
    else:
        row = _sci_row(cell_dir)
    row["task"] = task
    row["condition"] = condition
    row.pop("ts", None)
    return row


def write_csv(rows: list[dict], path: Path) -> None:
    fields = FIELDS + (["error"] if any(r.get("error") for r in rows) else [])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def write_markdown(rows: list[dict], path: Path) -> None:
    lines: list[str] = []
    lines.append("# cc-bare vs sciagent-verifier-on-default across three tasks")
    lines.append("")
    lines.append("Comparison table for the 6 cells used in the paper's main efficiency claim.")
    lines.append("Each task contributes one cc-bare row and one sciagent row; both cells for a task use the same LLM (anthropic/claude-sonnet-4-6).")
    lines.append("")
    header = "| " + " | ".join(FIELDS) + " |"
    align_cells = []
    for f in FIELDS:
        align_cells.append(":---" if f in ("task", "condition", "cell_id", "adapter", "main_model") else "---:")
    align = "|" + "|".join(align_cells) + "|"
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
            lines.append(f"- `{r['task']}/{r.get('cell_id','?')}`: {r['error']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML,
                    help=f"Root icml_results dir (default: {ICML})")
    ap.add_argument("--out-dir",   type=Path, default=ICML / "reports",
                    help="Where to write cc_vs_sciagent_default.{md,csv}")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for task, condition, ts, cell_id in _CELLS:
        print(f"→ {task} / {condition}", flush=True)
        try:
            row = build_row(args.icml_root, task, condition, ts, cell_id)
        except Exception as e:
            row = {
                "task": task, "condition": condition, "cell_id": cell_id,
                "adapter": condition,
                "error": f"{type(e).__name__}: {e}",
            }
            print(f"  ERROR: {row['error']}")
        if row.get("error"):
            print(f"  ERROR: {row['error']}")
        rows.append(row)

    csv_path = args.out_dir / "cc_vs_sciagent_default.csv"
    md_path  = args.out_dir / "cc_vs_sciagent_default.md"
    write_csv(rows, csv_path)
    write_markdown(rows, md_path)
    print()
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
