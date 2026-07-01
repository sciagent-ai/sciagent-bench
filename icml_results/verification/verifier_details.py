"""Detailed dump of sciagent's in-loop verifier for each case study.

`verify_and_compare.py` reports the verifier's TOP-LINE verdict + confidence
(one column each). This script goes deeper: it dumps every field the
`verification_result` event carries so a reader can see WHY the verifier
landed on that verdict, WHAT it flagged as concerning, and WHAT evidence
it explicitly could not verify.

Per case study, extracts:
  - top-line verdict + confidence + verifier_model
  - reasoning (full free-text paragraph)
  - supporting_facts (bulleted — what the verifier confirmed)
  - fabrication_indicators (bulleted — what the verifier suspected)
  - missing_evidence (bulleted — what the log didn't let it check)
  - issues (severity / category / message table)

Emits `verifier_details.md` next to this script. No cc-bare content — cc-bare
cells never emit `verification_result` events (no in-loop verifier). Use
`verify_and_compare.py` for the cross-adapter picture.

Cell layout is hardcoded (`_CELLS`) to keep the report deterministic. Add
rows here when new sciagent case studies land.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
ICML  = _THIS.parent.parent


# One line per sciagent cell to dump. Same style as
# compare_cc_vs_sciagent.py::_CELLS — explicit is better than glob when
# the audit report needs to be reproducible.
_CELLS: list[tuple[str, str, str, str]] = [
    # (task, condition, ts, cell_id)
    ("photonics",             "sciagent-verifier-on-default",
     "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet"),
    ("brca1_fitness_structure", "sciagent-verifier-on-default",
     "20260630T135609Z", "brca1_fitness_structure__sciagent-verifier-on-default__sonnet"),
    ("cfd_fig3_kde",          "sciagent-verifier-on-default",
     "20260630T184838Z", "cfd_fig3_kde__sciagent-verifier-on-default__sonnet"),
]


def _last_verification_result(provenance: Path) -> dict:
    """Return the last verification_result event (there's always exactly
    one per sciagent run today, but we take the last if that changes)."""
    if not provenance.exists():
        return {}
    last: dict = {}
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


def _fmt_confidence(c) -> str:
    if isinstance(c, (int, float)):
        return f"{c:.2f}"
    return str(c or "—")


def _bulleted(items: list, empty_msg: str = "(none reported)") -> list[str]:
    if not items:
        return [f"_{empty_msg}_"]
    out: list[str] = []
    for it in items:
        # Preserve multi-line messages by joining with a soft-return.
        text = str(it).strip()
        out.append(f"- {text}")
    return out


def _issues_table(issues: list) -> list[str]:
    if not issues:
        return ["_(no issues)_"]
    out = ["| severity | category | message |", "|:---|:---|:---|"]
    for i in issues:
        if not isinstance(i, dict):
            out.append(f"|  |  | {str(i)} |")
            continue
        sev = str(i.get("severity", "") or "").replace("|", "\\|")
        cat = str(i.get("category", "") or "").replace("|", "\\|")
        msg = str(i.get("message", "") or "").replace("|", "\\|").replace("\n", " ")
        out.append(f"| {sev} | {cat} | {msg} |")
    return out


def render_case_study(task: str, cell_id: str, ts: str, cell_dir: Path) -> str:
    prov = cell_dir / "provenance.jsonl"
    ev   = _last_verification_result(prov)
    if not ev:
        return f"## {task}\n\n_No `verification_result` event found under `{prov}`._\n"

    verdict     = ev.get("verdict", "?")
    confidence  = _fmt_confidence(ev.get("confidence"))
    verifier    = ev.get("verifier", "?")
    gate        = ev.get("gate", "?")
    issues      = ev.get("issues", []) or []
    evidence    = ev.get("evidence", {}) or {}
    reasoning   = evidence.get("reasoning", "") or ""
    supporting  = evidence.get("supporting_facts", []) or []
    fabrication = evidence.get("fabrication_indicators", []) or []
    missing     = evidence.get("missing_evidence", []) or []
    session_log = evidence.get("session_log", "") or ""

    lines: list[str] = []
    lines.append(f"## {task}")
    lines.append("")
    lines.append(f"- **cell**: `{cell_id}` (ts `{ts}`)")
    lines.append(f"- **verdict**: `{verdict}` @ **confidence {confidence}**")
    lines.append(f"- **verifier**: `{verifier}` (gate `{gate}`)")
    lines.append(f"- **parent session log**: `{session_log}`")
    lines.append(f"- **issue count**: {len(issues)}  ·  "
                 f"**supporting facts**: {len(supporting)}  ·  "
                 f"**fabrication indicators**: {len(fabrication)}  ·  "
                 f"**missing evidence**: {len(missing)}")
    lines.append("")

    lines.append("### Reasoning")
    lines.append("")
    lines.append(reasoning.strip() or "_(empty)_")
    lines.append("")

    lines.append("### Supporting facts")
    lines.append("")
    lines.extend(_bulleted(supporting))
    lines.append("")

    lines.append("### Fabrication indicators")
    lines.append("")
    lines.extend(_bulleted(fabrication, empty_msg="(none flagged)"))
    lines.append("")

    lines.append("### Missing evidence")
    lines.append("")
    lines.extend(_bulleted(missing, empty_msg="(nothing marked missing)"))
    lines.append("")

    lines.append("### Issues")
    lines.append("")
    lines.extend(_issues_table(issues))
    lines.append("")

    return "\n".join(lines) + "\n"


def render_summary_table(rows: list[dict]) -> str:
    lines = [
        "| task | verdict | confidence | issues | supporting | fabrication | missing |",
        "|:---|:---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['task']} | {r['verdict']} | {r['confidence']} | "
            f"{r['n_issues']} | {r['n_supporting']} | "
            f"{r['n_fabrication']} | {r['n_missing']} |"
        )
    return "\n".join(lines) + "\n"


def build_report(icml_root: Path) -> str:
    intro = (
        "# In-loop verifier — detailed dump per case study\n\n"
        "Every field emitted by the sciagent CLI's `_emit_llm_verification_event`\n"
        "for each case-study cell. Numbers alone (verdict, confidence) hide the\n"
        "*why*; this file surfaces the verifier's own reasoning, what it counted\n"
        "as supporting evidence, what it flagged as suspicious, and what it\n"
        "couldn't check from the trajectory alone.\n\n"
        "cc-bare cells aren't included — they carry no `verification_result`\n"
        "events by construction (no in-loop verifier). For the cross-adapter\n"
        "table see `verification_comparison.md`.\n\n"
    )

    summary_rows: list[dict] = []
    case_studies: list[str] = []
    for task, condition, ts, cell_id in _CELLS:
        cell_dir = icml_root / ts / task / cell_id
        prov     = cell_dir / "provenance.jsonl"
        ev       = _last_verification_result(prov) if prov.exists() else {}
        evidence = ev.get("evidence", {}) or {}
        summary_rows.append({
            "task":          task,
            "verdict":       ev.get("verdict", "—"),
            "confidence":    _fmt_confidence(ev.get("confidence")),
            "n_issues":      len(ev.get("issues", []) or []),
            "n_supporting":  len(evidence.get("supporting_facts", []) or []),
            "n_fabrication": len(evidence.get("fabrication_indicators", []) or []),
            "n_missing":     len(evidence.get("missing_evidence", []) or []),
        })
        case_studies.append(render_case_study(task, cell_id, ts, cell_dir))

    header = intro + "## Summary table\n\n" + render_summary_table(summary_rows) + "\n---\n\n"
    return header + "\n---\n\n".join(case_studies)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML,
                    help=f"Root icml_results dir (default: {ICML})")
    ap.add_argument("--out",       type=Path, default=_THIS.parent / "verifier_details.md",
                    help="Output markdown path")
    args = ap.parse_args(argv)

    report = build_report(args.icml_root)
    args.out.write_text(report)
    print(f"wrote {args.out}  ({len(report):,} chars, "
          f"{len(_CELLS)} case studies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
