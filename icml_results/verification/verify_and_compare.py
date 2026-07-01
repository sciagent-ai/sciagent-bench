"""Deterministic T1/T2/T3 verification comparison, cc-bare vs sciagent.

Joins four sources:
  1. Task YAMLs (`sciagent-bench/tasks/<task>.yaml`) — the objective bar:
     verification_criteria = {key_value, comparator, threshold, paper_value};
     services_needed drives the T1 (Computed?) tool-invocation check.
  2. Hand-filled `claim_values.csv` — the agent's stated numeric result,
     pulled by a human from each cell's result.txt / project/_outputs/.
     One row per (task, condition) pair.
  3. Sciagent provenance.jsonl — for the sciagent cells only:
        - `compute_job_launched` events answer T1 (was the required
          service actually invoked?).
        - `tool_result` output text across parent + child sessions
          answers T2 (does the claimed number appear in a tool output?).
        - `verification_result` events carry the in-loop LLM verdict.
  4. Child session logs at `~/.sciagent/sessions/<id>/provenance.jsonl` —
     recursed into for both T1 and T2 (the auditable evidence for any
     numeric computation lives in the child log, not the parent).

Produces `verification_comparison.{md,csv}` under the same folder.

Design-doc mapping: covers T1 / T2 / T3 of the Phase 10 rubric for
sciagent cells (all three axes fully automated from provenance) plus
T3 uniformly for cc-bare (from hand-transcribed claim × task
threshold). cc-bare T1/T2 stay out of scope here — those would require
walking Claude Code's stdout.txt for tool calls, which is a separate
audit surface. See README for the intentional gap.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

import yaml

_THIS   = Path(__file__).resolve()
ICML    = _THIS.parent.parent
BENCH   = ICML.parent
TASKS   = BENCH / "tasks"
SCIAGENT_SESSIONS_ROOT = Path.home() / ".sciagent" / "sessions"

# T2 float-match tolerance. Two loose enough that a claim of "0.2509" hits
# a tool_result "0.25091" as trace evidence, but tight enough that
# unrelated floats in the same trajectory don't spuriously match.
_T2_REL_TOL = 1e-3
_T2_ABS_TOL = 1e-6
_FLOAT_RE   = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


# cc-bare T1 signature map: services_needed (from the task YAML) → substrings
# to grep in Bash tool_use commands. cc-bare has no "service" concept — the
# agent just runs Bash — so this is the closest proxy for "did the agent
# invoke the required scientific tool". Case-insensitive substring match.
#
# When a new task ships with a new service, add its bash-command signature
# here. If a task's service isn't in the map, T1 for cc-bare reports
# "unknown" instead of yes/no — honest about the gap rather than reporting
# a false negative.
_CC_BARE_T1_SIGNATURES: dict[str, list[str]] = {
    "rcwa":              ["S4", "rcwa"],
    "biopython":         ["biopython", "Bio.PDB", "from Bio ", "from Bio\t", "import Bio"],
    "openfoam-swak4foam": [
        "openfoam", "swak4foam",
        "buoyantBoussinesqSimpleFoam", "simpleFoam", "blockMesh",
        "snappyHexMesh", "foamRun", "checkMesh",
    ],
    # Aliases so pinned-image variants (openfoam-swak4foam-2012, etc.)
    # resolve to the same signatures as their base service.
    "openfoam-swak4foam-2012": None,   # resolved at lookup time to the base
    "pytorch":           ["torch", "import torch", "pytorch"],
}


def _cc_bare_signatures_for(services_needed: list[str]) -> tuple[list[str], list[str]]:
    """Look up cc-bare signatures for every required service. Returns
    (signatures_all, services_without_signature) so we can distinguish
    "the required service is in our map and we didn't see it" from "we
    don't know what to look for."""
    sigs: list[str] = []
    unmapped: list[str] = []
    for s in services_needed:
        sn = (s or "").strip()
        if not sn:
            continue
        entry = _CC_BARE_T1_SIGNATURES.get(sn)
        if entry is None:
            # Try walking suffix chain — e.g. openfoam-swak4foam-2012 →
            # openfoam-swak4foam (defined) → its signature.
            parts = sn.split("-")
            found = None
            while len(parts) > 1:
                parts = parts[:-1]
                cand = "-".join(parts)
                if cand in _CC_BARE_T1_SIGNATURES and _CC_BARE_T1_SIGNATURES[cand]:
                    found = _CC_BARE_T1_SIGNATURES[cand]
                    break
            if found:
                sigs.extend(found)
            else:
                unmapped.append(sn)
        else:
            sigs.extend(entry)
    return sigs, unmapped


def _load_task_yaml(task: str) -> dict:
    p = TASKS / f"{task}.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _load_criteria(task: str) -> dict:
    """Pull verification_criteria out of tasks/<task>.yaml."""
    return _load_task_yaml(task).get("verification_criteria") or {}


def _load_services_needed(task: str) -> list[str]:
    """Pull services_needed out of tasks/<task>.yaml. Used to build the T1
    check — did the agent invoke any of these services?"""
    return list(_load_task_yaml(task).get("services_needed") or [])


def _iter_events(path: Path):
    if not path.exists():
        return
    for line in path.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _iter_all_provenance_events(parent_log: Path):
    """Yield events from parent_log + every child session referenced via
    subagent_completed.child_session_id (matching the audit-trajectory rule
    from the design doc). Cycles are guarded against."""
    visited: set[Path] = set()
    def walk(p: Path):
        p = p.resolve()
        if p in visited or not p.exists():
            return
        visited.add(p)
        child_ids: list[str] = []
        for ev in _iter_events(p):
            yield ev
            if ev.get("event_kind") == "subagent_completed":
                cid = ev.get("child_session_id")
                if cid:
                    child_ids.append(cid)
        for cid in child_ids:
            yield from walk(SCIAGENT_SESSIONS_ROOT / cid / "provenance.jsonl")
    yield from walk(parent_log)


def _t1_service_match(services_needed: list[str], service_seen: str) -> bool:
    """True if the observed service satisfies any required service.

    Prefix match — the CFD task lists `openfoam-swak4foam` while the
    actually-launched service is `openfoam-swak4foam-2012` (the pinned
    image). Prefix is strict enough that unrelated services never
    accidentally satisfy, and permissive enough for image-suffix
    variants."""
    s = (service_seen or "").strip().lower()
    if not s:
        return False
    for needed in services_needed:
        n = (needed or "").strip().lower()
        if not n:
            continue
        if s == n or s.startswith(n + "-") or s.startswith(n):
            return True
    return False


def _t1_computed(parent_log: Path, services_needed: list[str]) -> tuple[bool, list[str]]:
    """T1 = Computed?  Return (satisfied, [services actually observed])."""
    seen: set[str] = set()
    matched = False
    for ev in _iter_all_provenance_events(parent_log):
        if ev.get("event_kind") != "compute_job_launched":
            continue
        s = ev.get("service") or ""
        if s:
            seen.add(s)
        if not matched and _t1_service_match(services_needed, s):
            matched = True
    return matched, sorted(seen)


def _extract_tool_result_text(ev: dict) -> str:
    """Best-effort extraction of tool_result output text. Sciagent's
    provenance stores the payload in `output_summary` (which is often the
    full raw output for bash-like tools — a JSON blob or stdout capture —
    despite the "summary" name). Other adapters or tool kinds may use
    different keys, so we look at several and concatenate."""
    parts: list[str] = []
    for key in ("output_summary", "output", "result", "content",
                "stdout", "stderr", "value"):
        v = ev.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif v is not None:
            try:
                parts.append(json.dumps(v, default=str))
            except (TypeError, ValueError):
                parts.append(str(v))
    return "\n".join(parts)


def _numbers_in(text: str) -> list[tuple[float, str]]:
    """Yield (parsed_value, raw_substring) for every numeric literal.

    Returns the RAW string too so downstream code can reject bare-integer
    matches for real-valued claims — e.g. claim=1.0 (a probability) should
    NOT match a bare "1" (a count or "F1" domain label). Only substrings
    containing "." or "e/E" survive that filter."""
    out: list[tuple[float, str]] = []
    for m in _FLOAT_RE.finditer(text or ""):
        raw = m.group()
        try:
            out.append((float(raw), raw))
        except ValueError:
            continue
    return out


def _claim_variants(claim: float) -> list[tuple[float, str]]:
    """Yield the numeric forms a claim might appear as. `frac ↔ percent`
    pairs are the common failure mode — the criterion is expressed as a
    fraction (0.25) while the trajectory quotes a percent (25.04)."""
    out = [(claim, "as-stated")]
    if abs(claim) < 1.0 and abs(claim) > 1e-6:
        out.append((claim * 100.0, "×100 (percent form)"))
    elif abs(claim) > 1.0 and abs(claim) < 1000.0:
        out.append((claim / 100.0, "÷100 (fraction form)"))
    return out


def _matches_claim(raw: str, value: float, claim: float) -> bool:
    """Numeric close AND source string is "float-shaped" (has "." or "e/E").
    The float-shape gate is what prevents "1" from matching claim=1.0 when
    "1" is just a count or the "1" in "F1" domain name."""
    if not math.isclose(value, claim, rel_tol=_T2_REL_TOL, abs_tol=_T2_ABS_TOL):
        return False
    return ("." in raw) or ("e" in raw) or ("E" in raw)


def _iter_cc_bare_stream(stdout_path: Path):
    """Yield parsed events from a Claude Code stream-json stdout.txt."""
    if not stdout_path.exists():
        return
    for line in stdout_path.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _cc_bare_bash_commands(stdout_path: Path):
    """Yield every Bash tool_use `input.command` string in order."""
    for ev in _iter_cc_bare_stream(stdout_path):
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        for blk in (msg.get("content") or []):
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                cmd = (blk.get("input") or {}).get("command", "")
                if cmd:
                    yield cmd


def _cc_bare_tool_result_texts(stdout_path: Path):
    """Yield every tool_result text payload in order. Claude Code stores
    the content either as a bare string or as a list of `{type, text}`
    blocks; handle both."""
    for ev in _iter_cc_bare_stream(stdout_path):
        if ev.get("type") != "user":
            continue
        msg = ev.get("message") or {}
        for blk in (msg.get("content") or []):
            if not isinstance(blk, dict) or blk.get("type") != "tool_result":
                continue
            v = blk.get("content")
            if isinstance(v, str):
                yield v
            elif isinstance(v, list):
                for c in v:
                    if isinstance(c, dict) and c.get("type") == "text":
                        t = c.get("text")
                        if isinstance(t, str):
                            yield t


def _cc_bare_t1(stdout_path: Path, services_needed: list[str]) -> tuple[str, str]:
    """cc-bare T1: did any Bash command mention a required-service signature?

    Returns (verdict, evidence) where verdict is "yes" / "no" / "unknown".
    "unknown" means we don't have a signature entry for at least one
    required service — silently reporting "no" would be dishonest."""
    if not stdout_path.exists():
        return "no", "stdout.txt missing"
    sigs, unmapped = _cc_bare_signatures_for(services_needed)
    if not sigs and unmapped:
        return "unknown", f"no signature mapping for services: {', '.join(unmapped)}"
    sigs_lower = [s.lower() for s in sigs]
    for cmd in _cc_bare_bash_commands(stdout_path):
        low = cmd.lower()
        for pat, orig in zip(sigs_lower, sigs):
            if pat in low:
                snippet = cmd[:120].replace("\n", " ")
                verdict = "yes"
                if unmapped:
                    verdict = "yes*"  # matched at least one, but missed signatures
                return verdict, f"matched '{orig}' in Bash: {snippet}"
    return "no", ""


def _cc_bare_t2(stdout_path: Path, claim: float) -> tuple[bool, str]:
    """cc-bare T2: same rules as sciagent T2 — numeric close + float-shaped
    source + as-stated variant tried before ×100 / ÷100 fallback."""
    if claim is None or not stdout_path.exists():
        return False, ""
    variants = _claim_variants(claim)

    def scan(target: float, label: str) -> tuple[bool, str]:
        for text in _cc_bare_tool_result_texts(stdout_path):
            for cand_val, raw in _numbers_in(text):
                if _matches_claim(raw, cand_val, target):
                    snip = text[:200].replace("\n", " | ")
                    tag  = "" if label == "as-stated" else f" [{label}]"
                    return True, f"matched {raw}{tag} in tool_result: {snip}"
        return False, ""

    for target, label in variants:
        ok, evidence = scan(target, label)
        if ok:
            return ok, evidence
    return False, ""


def _t2_traceable(parent_log: Path, claim: float) -> tuple[bool, str]:
    """T2 = Traceable?  Does `claim` (or its ×100 / ÷100 percent-form
    variant) appear (within tolerance) in any tool_result block across
    parent + child sessions?  Bare-integer sources are rejected — only
    "float-shaped" strings (containing "." or "e/E") count.

    Two-pass: first pass tries the as-stated variant across ALL events,
    only failing over to the percent/fraction variant if no as-stated
    match exists anywhere. This prevents a stray ÷100 match on some
    unrelated small float (like an OpenFOAM residual) from beating a
    legitimate direct-form hit that appears later in the trajectory."""
    if claim is None:
        return False, ""
    variants = _claim_variants(claim)  # first entry is always as-stated

    def scan(target: float, label: str) -> tuple[bool, str]:
        for ev in _iter_all_provenance_events(parent_log):
            if ev.get("event_kind") != "tool_result":
                continue
            text = _extract_tool_result_text(ev)
            if not text:
                continue
            for cand_val, raw in _numbers_in(text):
                if _matches_claim(raw, cand_val, target):
                    seq  = ev.get("seq")
                    tool = ev.get("tool_name", "")
                    tag  = "" if label == "as-stated" else f" [{label}]"
                    return True, f"matched {raw} in tool_result seq={seq} tool={tool}{tag}"
        return False, ""

    for target, label in variants:
        ok, evidence = scan(target, label)
        if ok:
            return ok, evidence
    return False, ""


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
    "T1_computed",            # sciagent: required service invoked?; cc-bare: n/a
    "T1_services_seen",       # what was actually launched (sciagent)
    "T2_traceable",           # sciagent: claim appears in a tool_result?; cc-bare: n/a
    "T2_evidence",             # short evidence pointer for T2
    "T3_passes_threshold",    # deterministic — applies to both adapters
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
        services  = _load_services_needed(task)

        claim_val = _parse_float(row.get("claimed_value", ""))
        passes    = _apply_comparator(claim_val, crit.get("comparator", ""), crit.get("threshold"))

        cell_dir  = _find_cell_dir(icml_root, task, cell_id)
        sci_verdict = ""
        sci_conf    = ""
        sci_model   = ""
        t1_computed: str = ""
        t1_seen: str     = ""
        t2_traceable: str = ""
        t2_evidence: str  = ""

        if cell_dir is not None and "sciagent" in condition:
            prov = cell_dir / "provenance.jsonl"
            # T1: was the required service actually launched?
            t1_ok, seen = _t1_computed(prov, services)
            t1_computed = "yes" if t1_ok else "no"
            t1_seen     = ", ".join(seen) if seen else "(none)"
            # T2: does the claim appear in a tool_result across parent + children?
            if claim_val is not None:
                t2_ok, ev_str = _t2_traceable(prov, claim_val)
                t2_traceable = "yes" if t2_ok else "no"
                t2_evidence  = ev_str
            # In-loop verifier verdict
            ev = _last_verification_result(prov)
            sci_verdict = ev.get("verdict", "")
            sci_conf    = ev.get("confidence", "")
            sci_model   = ev.get("verifier", "")
        elif cell_dir is not None and condition == "cc-bare":
            # cc-bare has no provenance; walk Claude Code's stdout.txt stream.
            stdout = cell_dir / "stdout.txt"
            t1_computed, t1_seen = _cc_bare_t1(stdout, services)
            if claim_val is not None:
                t2_ok, ev_str = _cc_bare_t2(stdout, claim_val)
                t2_traceable = "yes" if t2_ok else "no"
                t2_evidence  = ev_str

        rows.append({
            "task":                task,
            "condition":           condition,
            "cell_id":             cell_id,
            "criterion":           _criterion_str(crit),
            "paper_value":         crit.get("paper_value", ""),
            "claimed_value":       row.get("claimed_value", "") or "",
            "T1_computed":         t1_computed,
            "T1_services_seen":    t1_seen,
            "T2_traceable":        t2_traceable,
            "T2_evidence":         t2_evidence,
            "T3_passes_threshold": "" if passes is None else ("pass" if passes else "fail"),
            "sci_verdict":         sci_verdict,
            "sci_confidence":      f"{sci_conf:.2f}" if isinstance(sci_conf, (int, float)) else sci_conf,
            "sci_verifier_model":  sci_model,
            "agreement":           _sci_agrees(passes, sci_verdict),
            "extraction_notes":    row.get("extraction_notes", "") or "",
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
    lines.append("# Verification comparison — cc-bare vs sciagent (T1 · T2 · T3)")
    lines.append("")
    lines.append(
        "Deterministic audit across the design-doc rubric applied to both "
        "adapters:\n"
        "- **T1 (Computed?)** — did the required tool run?  "
        "sciagent: `compute_job_launched.service` events across parent + "
        "child sessions.  cc-bare: `Bash` tool_use commands in the "
        "Claude Code stream matched against a per-service signature "
        "(see `_CC_BARE_T1_SIGNATURES`).\n"
        "- **T2 (Traceable?)** — does the claimed value appear in some "
        "`tool_result` output within float tolerance?  sciagent: "
        "`tool_result.output_summary` across parent + child sessions.  "
        "cc-bare: `tool_result` blocks in the Claude Code stream.\n"
        "- **T3 (Correct?)** — does the claim satisfy the paper's numeric "
        "threshold? Deterministic; adapter-agnostic.\n"
        "- **sciagent-only**: `sci_verdict` / `sci_confidence` from the "
        "last `verification_result` event; `agreement` compares that "
        "verdict against the deterministic T3 result.\n"
        "\nT1 for cc-bare can report `yes*` when at least one required "
        "service matched but at least one has no signature mapping; "
        "`unknown` when none of the services have signatures. See `README.md`."
    )
    lines.append("")

    # Compact display columns (full data lives in the CSV).
    display = [
        "task", "condition", "criterion",
        "claimed_value", "paper_value",
        "T1_computed", "T2_traceable", "T3_passes_threshold",
        "sci_verdict", "sci_confidence", "agreement",
    ]
    header = "| " + " | ".join(display) + " |"
    align  = "|" + "|".join(
        ":---" if f in ("task","condition","criterion","T1_computed","T2_traceable","T3_passes_threshold","sci_verdict","agreement")
        else "---:"
        for f in display
    ) + "|"
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
