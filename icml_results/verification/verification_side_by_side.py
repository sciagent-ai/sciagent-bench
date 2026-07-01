"""Side-by-side verification report: sciagent verifier vs cc-bare trajectory.

For each of the three case studies, dumps:
  - sciagent side  — full `verification_result` event contents from
    provenance.jsonl (verdict, confidence, reasoning,
    supporting_facts, fabrication_indicators, missing_evidence,
    issues). Same source `verifier_details.py` uses.
  - cc-bare side   — deterministic reconstruction from `stdout.txt`
    (Claude Code's stream JSON): what tools ran, whether the required
    scientific tool was invoked (T1), whether the claim traces to a
    tool_result (T2), whether the claim beats the threshold (T3),
    session-level rollup (cost, tokens, turns, terminal reason).
  - narrative     — one-paragraph comparison flagging the audit-grade
    differential per case study.

cc-bare has no in-loop verifier so there is nothing on that side that
mirrors sciagent's `reasoning` / `supporting_facts` / etc. structured
output. The report is honest about that gap — it dumps every
deterministic signal we CAN pull from the trajectory but does not
fabricate verifier-like commentary. The narrative section makes the
gap explicit.

Emits `verification_side_by_side.md` next to this script.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


_THIS = Path(__file__).resolve()
ICML  = _THIS.parent.parent
sys.path.insert(0, str(_THIS.parent))

# Reuse T1/T2/T3 helpers so this script stays a thin composition layer
# rather than a duplicate implementation.
from verify_and_compare import (  # noqa: E402
    _load_criteria, _load_services_needed, _apply_comparator,
    _last_verification_result, _t1_computed, _t2_traceable,
    _cc_bare_t1, _cc_bare_t2, _parse_float, _criterion_str,
    _iter_cc_bare_stream,
)


# Same case-study set as verifier_details.py + compare_cc_vs_sciagent.py.
# Explicit list keeps the report reproducible when new sciagent runs land
# elsewhere in icml_results.
_CASE_STUDIES: list[dict] = [
    {
        "task":  "photonics",
        "sci":   ("20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet"),
        "cc":    ("20260608T200907Z", "photonics__cc-bare__sonnet"),
    },
    {
        "task":  "brca1_fitness_structure",
        "sci":   ("20260630T135609Z", "brca1_fitness_structure__sciagent-verifier-on-default__sonnet"),
        "cc":    ("20260630T135609Z", "brca1_fitness_structure__cc-bare__sonnet"),
    },
    {
        "task":  "cfd_fig3_kde",
        "sci":   ("20260630T184838Z", "cfd_fig3_kde__sciagent-verifier-on-default__sonnet"),
        "cc":    ("20260630T184838Z", "cfd_fig3_kde__cc-bare__sonnet"),
    },
]


# Bash-command substrings worth calling out when they appear in a
# cc-bare trajectory. These aren't required (T1 uses its own signature
# dict); they're signals of HOW cc-bare achieved the result — cluster
# vs Docker vs local Python, and which specific library it chose.
_CC_HIGHLIGHT_TERMS = [
    "docker", "sky launch", "sky exec",              # deployment path
    "S4", "grcwa", "meent", "rcwa",                  # photonics libs
    "biopython", "Bio.PDB", "from Bio",              # brca1 libs
    "openfoam", "swak", "buoyantBoussinesqSimpleFoam",
    "blockMesh", "snappyHexMesh", "simpleFoam",
]


def _fmt_confidence(c) -> str:
    if isinstance(c, (int, float)):
        return f"{c:.2f}"
    return str(c or "—")


def _bulleted(items, empty="_(none)_") -> list[str]:
    if not items:
        return [empty]
    return [f"- {str(x).strip()}" for x in items]


def _issues_table(issues: list) -> list[str]:
    if not issues:
        return ["_(no issues)_"]
    out = ["| severity | category | message |", "|:---|:---|:---|"]
    for i in issues:
        if not isinstance(i, dict):
            out.append(f"|  |  | {i} |")
            continue
        sev = str(i.get("severity", "") or "")
        cat = str(i.get("category", "") or "")
        msg = str(i.get("message", "") or "").replace("|", "\\|").replace("\n", " ")
        out.append(f"| {sev} | {cat} | {msg} |")
    return out


# ---------------------------------------------------------------------------
# sciagent side — same shape as verifier_details.py
# ---------------------------------------------------------------------------


def _render_sciagent_block(cell_dir: Path) -> list[str]:
    prov = cell_dir / "provenance.jsonl"
    ev   = _last_verification_result(prov)
    if not ev:
        return [f"_No verification_result event found at `{prov}`._"]
    evidence = ev.get("evidence", {}) or {}
    verdict     = ev.get("verdict", "?")
    confidence  = _fmt_confidence(ev.get("confidence"))
    verifier    = ev.get("verifier", "?")
    reasoning   = (evidence.get("reasoning") or "").strip()
    supporting  = evidence.get("supporting_facts") or []
    fabrication = evidence.get("fabrication_indicators") or []
    missing     = evidence.get("missing_evidence") or []
    issues      = ev.get("issues") or []

    lines: list[str] = []
    lines.append(f"**Verdict**: `{verdict}` @ **confidence {confidence}**  ·  "
                 f"verifier `{verifier}`")
    lines.append(f"**Counts**: {len(supporting)} supporting facts · "
                 f"{len(fabrication)} fabrication indicators · "
                 f"{len(missing)} missing evidence · {len(issues)} issues")
    lines.append("")
    lines.append("**Reasoning** (verbatim from provenance):")
    lines.append("")
    lines.append(reasoning or "_(empty)_")
    lines.append("")

    lines.append("**Supporting facts**")
    lines.append("")
    lines.extend(_bulleted(supporting))
    lines.append("")

    lines.append("**Fabrication indicators**")
    lines.append("")
    lines.extend(_bulleted(fabrication, empty="_(none flagged)_"))
    lines.append("")

    lines.append("**Missing evidence**")
    lines.append("")
    lines.extend(_bulleted(missing, empty="_(nothing marked missing)_"))
    lines.append("")

    lines.append("**Issues**")
    lines.append("")
    lines.extend(_issues_table(issues))
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# cc-bare side — deterministic reconstruction from stdout.txt
# ---------------------------------------------------------------------------


def _cc_bare_rollup(stdout_path: Path) -> dict:
    """Walk Claude Code's stream JSON and produce a per-cell summary:
    tool histogram, notable Bash-command term counts, session-level cost
    / tokens / turns / terminal reason, rate-limit-event count."""
    tool_uses    = Counter()
    n_asst       = 0
    rate_limits  = 0
    highlight_hits = Counter()
    init         = None
    result       = None

    for ev in _iter_cc_bare_stream(stdout_path):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            init = ev
        elif t == "result":
            result = ev
        elif t == "rate_limit_event":
            rate_limits += 1
        elif t == "assistant":
            n_asst += 1
            for blk in (ev.get("message") or {}).get("content") or []:
                if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                    continue
                name = blk.get("name", "")
                tool_uses[name] += 1
                if name == "Bash":
                    cmd = (blk.get("input") or {}).get("command", "") or ""
                    low = cmd.lower()
                    for term in _CC_HIGHLIGHT_TERMS:
                        if term.lower() in low:
                            highlight_hits[term] += 1

    def _num(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return {
        "model":           (init or {}).get("model") or "?",
        "n_asst":          n_asst,
        "tool_uses":       dict(tool_uses),
        "rate_limits":     rate_limits,
        "highlight_hits":  dict(highlight_hits),
        "cost_usd":        _num((result or {}).get("total_cost_usd"), 0.0),
        "num_turns":       (result or {}).get("num_turns"),
        "duration_ms":     (result or {}).get("duration_ms"),
        "is_error":        (result or {}).get("is_error"),
        "terminal_reason": (result or {}).get("terminal_reason"),
    }


def _cc_bare_claim(cell_dir: Path) -> str:
    p = cell_dir / "result.txt"
    if not p.exists():
        return "_(no result.txt)_"
    return p.read_text().strip()


def _render_cc_bare_block(cell_dir: Path, task: str, claim_val: float | None,
                          criterion_str: str, services: list[str]) -> list[str]:
    stdout = cell_dir / "stdout.txt"
    if not stdout.exists():
        return [f"_No stdout.txt at `{stdout}` — cc-bare cell did not produce a trajectory._"]

    r = _cc_bare_rollup(stdout)

    # T1 / T2 / T3 for cc-bare (same functions verify_and_compare uses)
    t1_verdict, t1_ev = _cc_bare_t1(stdout, services)
    if claim_val is not None:
        t2_ok, t2_ev = _cc_bare_t2(stdout, claim_val)
        t2_verdict = "yes" if t2_ok else "no"
    else:
        t2_verdict, t2_ev = "—", ""
    crit_json = _load_criteria(task)
    t3_ok = _apply_comparator(claim_val, crit_json.get("comparator", ""),
                              crit_json.get("threshold"))
    t3_verdict = "" if t3_ok is None else ("pass" if t3_ok else "fail")

    dur_s = (r["duration_ms"] or 0) / 1000.0 if r.get("duration_ms") is not None else None

    lines: list[str] = []
    lines.append("**No in-loop verifier** — cc-bare emits no `verification_result` event. "
                 "The block below is a deterministic reconstruction from `stdout.txt`.")
    lines.append("")

    # Session summary
    lines.append("**Session summary** (Claude Code's own `result` event):")
    lines.append("")
    lines.append(f"- model: `{r['model']}`")
    if r["num_turns"] is not None:
        lines.append(f"- turns (Claude Code): {r['num_turns']}")
    if dur_s is not None:
        lines.append(f"- duration: {dur_s:,.1f} s")
    lines.append(f"- total cost: ${r['cost_usd']:.4f}")
    lines.append(f"- assistant messages: {r['n_asst']}")
    if r["rate_limits"]:
        lines.append(f"- rate-limit events: {r['rate_limits']}")
    if r["terminal_reason"]:
        lines.append(f"- terminal reason: `{r['terminal_reason']}`")
    if r["is_error"] is not None:
        lines.append(f"- is_error: `{r['is_error']}`")
    lines.append("")

    # Tool histogram
    lines.append("**Tool use histogram** (all Claude Code tool_use blocks):")
    lines.append("")
    if r["tool_uses"]:
        for k, v in sorted(r["tool_uses"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{k}` × {v}")
    else:
        lines.append("_(no tool_use blocks)_")
    lines.append("")

    # Scientific-tool signature
    lines.append("**Scientific-tool signal in Bash commands** (substring hits):")
    lines.append("")
    if r["highlight_hits"]:
        for k, v in sorted(r["highlight_hits"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{k}` × {v}")
    else:
        lines.append("_(no signature terms observed)_")
    lines.append("")

    # T1/T2/T3 verdicts
    lines.append("**Deterministic audit** (uniform T1/T2/T3 rubric):")
    lines.append("")
    lines.append(f"- **T1** (Computed? — required service invoked): **{t1_verdict}**"
                 + (f"  ·  evidence: {t1_ev}" if t1_ev else ""))
    lines.append(f"- **T2** (Traceable? — claim appears in a tool_result): **{t2_verdict}**"
                 + (f"  ·  evidence: {t2_ev[:200]}" if t2_ev else ""))
    lines.append(f"- **T3** (Correct? — satisfies criterion `{criterion_str}`): **{t3_verdict or '—'}**")
    lines.append("")

    # The agent's final claim (short excerpt)
    claim_text = _cc_bare_claim(cell_dir)
    if len(claim_text) > 900:
        claim_text = claim_text[:900] + "\n\n_…[truncated; see cell's `result.txt` for full text]…_"
    lines.append("**Agent's final claim** (from `result.txt`):")
    lines.append("")
    lines.append("```")
    lines.append(claim_text)
    lines.append("```")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# narrative
# ---------------------------------------------------------------------------


def _narrative_for(task: str, sci_ev: dict, cc_r: dict, cc_signature_hits: dict) -> str:
    """One-paragraph audit-grade differential. Highlights when sciagent's
    verifier flagged something the cc-bare trajectory shows no equivalent
    trail for, or when cc-bare followed a substantively different tool
    path than the task specified."""
    verdict = sci_ev.get("verdict", "?")
    confidence = _fmt_confidence(sci_ev.get("confidence"))
    evidence = sci_ev.get("evidence", {}) or {}
    n_fab = len(evidence.get("fabrication_indicators") or [])
    n_iss = len(sci_ev.get("issues") or [])

    parts: list[str] = []
    parts.append(
        f"Sciagent's in-loop verifier landed on `{verdict}` (confidence "
        f"{confidence}) with {n_fab} fabrication indicator(s) and {n_iss} "
        f"issue(s), all readable directly from `provenance.jsonl`."
    )
    parts.append(
        "cc-bare produced no equivalent structured audit — anyone wanting "
        "the same signals for cc-bare must reconstruct them from the "
        "Claude Code stream by hand or via a post-hoc labeler."
    )
    # Task-specific colour: what tool path each side used.
    hits = {k.lower(): v for k, v in cc_signature_hits.items()}
    if task == "photonics":
        s4 = hits.get("s4", 0)
        grcwa = hits.get("grcwa", 0)
        if grcwa > s4 and grcwa > 0:
            parts.append(
                f"Tool path: sciagent invoked S4 via the `rcwa` cluster "
                f"service; cc-bare's trajectory has {grcwa} `grcwa` "
                f"substring hits vs {s4} `S4` — cc-bare used the pure-Python "
                f"`grcwa` library locally instead of the task-specified S4. "
                f"Sciagent's verifier explicitly noted the S3-materialized "
                f"MFE value as its trace anchor; cc-bare's numeric claim "
                f"lives only in the trajectory."
            )
    elif task == "brca1_fitness_structure":
        docker = hits.get("docker", 0)
        parts.append(
            f"Tool path: sciagent's verifier caught a scope downgrade — the "
            f"SkyPilot cluster stuck in INIT and computation actually ran "
            f"via local Docker (`ghcr.io/sciagent-ai/biopython`). "
            f"cc-bare stayed local from the start "
            f"({docker} Docker mentions in its Bash commands) — same "
            f"execution environment, but no structured audit signal that "
            f"a cluster was ever expected."
        )
    elif task == "cfd_fig3_kde":
        docker = hits.get("docker", 0)
        of = hits.get("openfoam", 0)
        parts.append(
            f"Tool path: sciagent ran the full 12-job OpenFOAM chain on "
            f"cluster `sciagent-358f91c80960-cfd` with service "
            f"`openfoam-swak4foam-2012`; cc-bare stayed local, invoking "
            f"OpenFOAM via Docker "
            f"({docker} `docker` and {of} `openfoam` substring hits in "
            f"Bash). Both reached results inside the [294, 298] K "
            f"criterion, but only sciagent recorded the cluster lifecycle, "
            f"S3 artifact URIs, and independent parent-session re-computation."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# top-level renderer
# ---------------------------------------------------------------------------


def _find_cell_dir(icml_root: Path, task: str, ts: str, cell_id: str) -> Path:
    return icml_root / ts / task / cell_id


def _cc_bare_claim_value_from_csv(claim_csv: Path, task: str, cell_id: str) -> float | None:
    """Reuse the hand-filled claim value from claim_values.csv so this
    script agrees with verify_and_compare.py on the claim number."""
    if not claim_csv.exists():
        return None
    import csv as _csv
    for r in _csv.DictReader(claim_csv.open()):
        if r["task"] == task and r["cell_id"] == cell_id:
            return _parse_float(r.get("claimed_value", ""))
    return None


def _summary_table(rows: list[dict]) -> list[str]:
    out = [
        "| task | sci verdict | sci conf | sci issues | sci fab | cc T1 | cc T2 | cc T3 |",
        "|:---|:---|---:|---:|---:|:---|:---|:---|",
    ]
    for r in rows:
        out.append(
            f"| {r['task']} | {r['sci_verdict']} | {r['sci_conf']} | "
            f"{r['sci_issues']} | {r['sci_fab']} | "
            f"{r['cc_t1']} | {r['cc_t2']} | {r['cc_t3']} |"
        )
    return out


def build_report(icml_root: Path, claim_csv: Path) -> str:
    intro = (
        "# Verification side-by-side — sciagent vs cc-bare\n\n"
        "Per case study, dumps:\n\n"
        "1. **sciagent** — every field of the in-loop verifier's\n"
        "   `verification_result` event (verdict, confidence, reasoning,\n"
        "   supporting facts, fabrication indicators, missing evidence,\n"
        "   issues). Read directly from `provenance.jsonl`.\n"
        "2. **cc-bare** — deterministic reconstruction from Claude Code's\n"
        "   `stdout.txt` stream. Session-level cost / turns / duration,\n"
        "   tool_use histogram, scientific-tool substring hits in Bash\n"
        "   commands, and the T1/T2/T3 audit verdicts. No LLM-generated\n"
        "   commentary — cc-bare emits no `verification_result` event by\n"
        "   construction, so no equivalent structured reasoning exists.\n"
        "3. **narrative** — one paragraph highlighting the audit-grade\n"
        "   differential per case study.\n\n"
        "See `verifier_details.md` for the sciagent-only per-cell dump,\n"
        "and `verification_comparison.md` for the compact cross-adapter\n"
        "T1/T2/T3 table.\n\n"
    )

    summary_rows: list[dict] = []
    sections: list[str] = []
    for cs in _CASE_STUDIES:
        task     = cs["task"]
        sci_ts, sci_id = cs["sci"]
        cc_ts,  cc_id  = cs["cc"]
        sci_dir = _find_cell_dir(icml_root, task, sci_ts, sci_id)
        cc_dir  = _find_cell_dir(icml_root, task, cc_ts, cc_id)
        crit    = _load_criteria(task)
        services = _load_services_needed(task)
        crit_str = _criterion_str(crit)
        claim_val = _cc_bare_claim_value_from_csv(claim_csv, task, cc_id)

        # sciagent block
        sci_ev = _last_verification_result(sci_dir / "provenance.jsonl")

        # cc-bare block (also captures highlight hits for narrative)
        cc_r = _cc_bare_rollup(cc_dir / "stdout.txt") if (cc_dir / "stdout.txt").exists() else {}

        # T1/T2/T3 for the cc-bare summary
        stdout = cc_dir / "stdout.txt"
        t1_v, _ = _cc_bare_t1(stdout, services) if stdout.exists() else ("—", "")
        if claim_val is not None and stdout.exists():
            t2_ok, _ = _cc_bare_t2(stdout, claim_val)
            t2_v = "yes" if t2_ok else "no"
        else:
            t2_v = "—"
        t3_ok = _apply_comparator(claim_val, crit.get("comparator", ""), crit.get("threshold"))
        t3_v = "" if t3_ok is None else ("pass" if t3_ok else "fail")

        summary_rows.append({
            "task":        task,
            "sci_verdict": sci_ev.get("verdict", "—"),
            "sci_conf":    _fmt_confidence(sci_ev.get("confidence")),
            "sci_issues":  len(sci_ev.get("issues", []) or []),
            "sci_fab":     len(((sci_ev.get("evidence") or {}).get("fabrication_indicators") or [])),
            "cc_t1":       t1_v,
            "cc_t2":       t2_v,
            "cc_t3":       t3_v or "—",
        })

        # Case-study section
        block: list[str] = []
        block.append(f"## {task}")
        block.append("")
        block.append(f"- **criterion**: {crit_str}  ·  **paper value**: {crit.get('paper_value', '—')}")
        block.append(f"- **sciagent cell**: `{sci_id}` (ts `{sci_ts}`)")
        block.append(f"- **cc-bare cell**: `{cc_id}` (ts `{cc_ts}`)")
        block.append(f"- **hand-filled claim value** (both sides): "
                     f"`{claim_val if claim_val is not None else '—'}`")
        block.append("")
        block.append("### sciagent — in-loop verifier")
        block.append("")
        block.extend(_render_sciagent_block(sci_dir))

        block.append("### cc-bare — deterministic trajectory record")
        block.append("")
        block.extend(_render_cc_bare_block(cc_dir, task, claim_val, crit_str, services))

        block.append("### Narrative — audit-grade differential")
        block.append("")
        block.append(_narrative_for(task, sci_ev, cc_r, cc_r.get("highlight_hits", {})))
        block.append("")
        sections.append("\n".join(block))

    header = intro + "## Summary\n\n" + "\n".join(_summary_table(summary_rows)) + "\n\n---\n\n"
    return header + "\n---\n\n".join(sections) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML)
    ap.add_argument("--claim-csv", type=Path, default=_THIS.parent / "claim_values.csv")
    ap.add_argument("--out",       type=Path, default=_THIS.parent / "verification_side_by_side.md")
    args = ap.parse_args(argv)

    report = build_report(args.icml_root, args.claim_csv)
    args.out.write_text(report)
    print(f"wrote {args.out}  ({len(report):,} chars, {len(_CASE_STUDIES)} case studies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
