"""Deterministic T3 (Correct?) verification comparison, cc-bare vs sciagent.

Joins three sources:
  1. Task YAMLs (`sciagent-bench/tasks/<task>.yaml`) — the objective bar:
     verification_criteria = {key_value, comparator, threshold, paper_value}.
  2. Hand-filled `claim_values.csv` — the agent's stated numeric result,
     pulled by a human from each cell's result.txt / project/_outputs/.
     One row per (task, condition) pair.
  3. Sciagent in-loop verifier events — `verification_result` events already
     written into each sciagent cell's `provenance.jsonl` by the CLI's LLM
     verification gate. cc-bare cells have none (no in-loop verifier).

Produces `verification_comparison.{md,csv}` under the same folder.

Design-doc mapping: this covers axis T3 (Correct?) of the Phase 10 rubric
uniformly across both adapters, plus the sciagent-only in-loop verdict —
enough to see (a) does the claim beat the threshold and (b) does sciagent's
own verifier agree. Does NOT cover T1 (Computed?) or T2 (Traceable?) — those
need the Claude Code labeler (or reverify_cells.py, which the user has
already run separately).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import yaml

_THIS   = Path(__file__).resolve()
ICML    = _THIS.parent.parent
BENCH   = ICML.parent
TASKS   = BENCH / "tasks"


def _load_criteria(task: str) -> dict:
    """Pull verification_criteria out of tasks/<task>.yaml."""
    p = TASKS / f"{task}.yaml"
    if not p.exists():
        return {}
    t = yaml.safe_load(p.read_text()) or {}
    return t.get("verification_criteria") or {}


def _apply_comparator(value: float, comparator: str, threshold) -> bool | None:
    """Return True/False if the deterministic check applies; None if the
    comparator isn't recognized (defensive)."""
    if value is None:
        return None
    if comparator == ">=":
        return value >= float(threshold)
    if comparator == "<=":
        return value <= float(threshold)
    if comparator == ">":
        return value > float(threshold)
    if comparator == "<":
        return value < float(threshold)
    if comparator == "in":
        lo, hi = threshold
        return float(lo) <= value <= float(hi)
    return None


def _find_cell_dir(icml_root: Path, task: str, cell_id: str) -> Path | None:
    """Walk the icml TS dirs to find the matching cell dir. First match wins;
    if the same cell_id lives in multiple TS dirs, whichever comes first in
    sorted order is used (rare — flag as ambiguous in extraction_notes if so)."""
    for ts in sorted(icml_root.iterdir()):
        if not ts.is_dir():
            continue
        candidate = ts / task / cell_id
        if candidate.exists():
            return candidate
    return None


def _last_verification_result(provenance: Path) -> dict:
    """Return the last verification_result event from a sciagent provenance
    log, or {} if none. Only relevant to sciagent cells; cc-bare cells have
    no provenance.jsonl."""
    if not provenance.exists():
        return {}
    last = {}
    for line in provenance.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event_kind") == "verification_result":
            last = ev
    return last


def _parse_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


FIELDS = [
    "task", "condition", "cell_id",
    "criterion",              # human-readable comparator + threshold
    "paper_value",
    "claimed_value",
    "passes_threshold",       # deterministic T3
    "sci_verdict",            # in-loop verifier verdict (sciagent only)
    "sci_confidence",
    "sci_verifier_model",
    "agreement",              # for sciagent only: T3 pass matches sci verdict?
    "extraction_notes",
]


def _criterion_str(crit: dict) -> str:
    """Render the criterion as a compact human-readable string, e.g.
    "≥ 0.25" or "in [294, 298]"."""
    comp = crit.get("comparator", "?")
    thr  = crit.get("threshold", "?")
    if comp == "in" and isinstance(thr, (list, tuple)) and len(thr) == 2:
        return f"in [{thr[0]}, {thr[1]}]"
    op = {">=": "≥", "<=": "≤"}.get(comp, comp)
    return f"{op} {thr}"


def _sci_agrees(passes: bool | None, sci_verdict: str) -> str:
    """Do the deterministic threshold check and the sciagent in-loop verdict
    agree? Only defined when both are present."""
    if passes is None or not sci_verdict:
        return ""
    verified_or_supported = sci_verdict in ("verified", "supported")
    return "yes" if verified_or_supported == passes else "no"


def build_rows(claim_csv: Path, icml_root: Path) -> list[dict]:
    rows: list[dict] = []
    for row in csv.DictReader(claim_csv.open()):
        task      = row["task"]
        condition = row["condition"]
        cell_id   = row["cell_id"]
        crit      = _load_criteria(task)

        claim_val = _parse_float(row.get("claimed_value", ""))
        passes    = _apply_comparator(claim_val, crit.get("comparator", ""), crit.get("threshold"))

        cell_dir  = _find_cell_dir(icml_root, task, cell_id)
        sci_verdict = ""
        sci_conf    = ""
        sci_model   = ""
        if cell_dir is not None and "sciagent" in condition:
            ev = _last_verification_result(cell_dir / "provenance.jsonl")
            sci_verdict = ev.get("verdict", "")
            sci_conf    = ev.get("confidence", "")
            sci_model   = ev.get("verifier", "")

        rows.append({
            "task":             task,
            "condition":        condition,
            "cell_id":          cell_id,
            "criterion":        _criterion_str(crit),
            "paper_value":      crit.get("paper_value", ""),
            "claimed_value":    row.get("claimed_value", "") or "",
            "passes_threshold": "" if passes is None else ("pass" if passes else "fail"),
            "sci_verdict":      sci_verdict,
            "sci_confidence":   f"{sci_conf:.2f}" if isinstance(sci_conf, (int, float)) else sci_conf,
            "sci_verifier_model": sci_model,
            "agreement":        _sci_agrees(passes, sci_verdict),
            "extraction_notes": row.get("extraction_notes", "") or "",
        })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def write_markdown(rows: list[dict], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Verification comparison — cc-bare vs sciagent (T3 axis)")
    lines.append("")
    lines.append(
        "Deterministic Correctness check (does the claim satisfy the paper's "
        "numeric threshold?) applied uniformly to both adapters, joined with "
        "sciagent's own in-loop LLM-verifier verdict (which cc-bare cells "
        "lack entirely). See `README.md` for the full method."
    )
    lines.append("")

    # Compact display columns (full data lives in the CSV).
    display = [
        "task", "condition", "criterion", "paper_value",
        "claimed_value", "passes_threshold",
        "sci_verdict", "sci_confidence", "agreement",
    ]
    header = "| " + " | ".join(display) + " |"
    align  = "|" + "|".join(":---" if f in ("task","condition","criterion","sci_verdict","agreement") else "---:" for f in display) + "|"
    lines.append(header)
    lines.append(align)
    for r in rows:
        cells = []
        for f in display:
            v = r.get(f, "")
            cells.append(str(v) if v != "" else "—")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # Notes for any rows the user still needs to hand-fill.
    todo = [r for r in rows if not r["claimed_value"]]
    if todo:
        lines.append("## Rows awaiting hand-filled `claimed_value`")
        lines.append("")
        for r in todo:
            lines.append(f"- **{r['task']} / {r['condition']}** — {r['extraction_notes']}")
        lines.append("")
        lines.append("Edit `claim_values.csv` in this folder, then rerun `verify_and_compare.py`.")
        lines.append("")

    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claim-csv", type=Path, default=_THIS.parent / "claim_values.csv",
                    help="Hand-filled claim_values.csv")
    ap.add_argument("--icml-root", type=Path, default=ICML,
                    help=f"Root icml_results dir (default: {ICML})")
    ap.add_argument("--out-dir",   type=Path, default=_THIS.parent,
                    help="Where to write verification_comparison.{md,csv}")
    args = ap.parse_args(argv)

    if not args.claim_csv.exists():
        print(f"error: {args.claim_csv} does not exist", file=sys.stderr)
        return 2

    rows = build_rows(args.claim_csv, args.icml_root)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_out = args.out_dir / "verification_comparison.csv"
    md_out  = args.out_dir / "verification_comparison.md"
    write_csv(rows, csv_out)
    write_markdown(rows, md_out)

    print(f"wrote {csv_out}")
    print(f"wrote {md_out}")
    filled = sum(1 for r in rows if r["claimed_value"])
    print(f"claimed_value filled: {filled}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
