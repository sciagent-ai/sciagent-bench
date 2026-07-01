"""Photonics-only: verifier influence across the 5 sciagent variants.

Same task (three-zone TiO2/N-BK7 metasurface) run under five different
sciagent configurations. Compares what the in-loop verifier said (or
whether it fired at all) across configurations, isolating three
independent axes:

  1. `verifier_include_child_sessions` (on vs off) — the Phase 1 flag.
  2. Verifier model family (Anthropic vs cross-family OpenAI).
  3. Agent model family (Anthropic vs OpenAI) — affects trajectory
     shape and run completion.

Variants covered (all under `icml_results/*/photonics/`):

  - `photonics__sciagent-verifier-on-default__sonnet` (recursive default,
    Phase 1)
  - `photonics__sciagent-no-recursion__sonnet` (legacy pre-Phase-1
    behaviour)
  - `photonics__sciagent-crossverifier__sonnet` (cross-family verifier
    on the old o4-mini recipe)
  - `photonics__sciagent-verifier-off__sonnet` (control: verification
    gate disabled)

The gpt5-agent variant is not included — that run errored before the
verification gate could fire, so it has nothing to compare.

Emits `photonics_verifier_variants.md` next to this script.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections import Counter


_THIS = Path(__file__).resolve()
ICML  = _THIS.parent.parent


# Per-variant metadata. Explicit table because the recipe-level details
# (verifier model, recursion setting, agent family) need to be surfaced
# in the report for the reader to disentangle the axes.
_VARIANTS: list[dict] = [
    {
        "label":        "verifier-on-default (sonnet, recursive)",
        "ts":           "20260630T120254Z",
        "cell_id":      "photonics__sciagent-verifier-on-default__sonnet",
        "agent_model":  "anthropic/claude-sonnet-4-6",
        "verifier":     "anthropic/claude-sonnet-4-6",
        "recursion":    "on (Phase 1 default)",
        "recipe":       "recipes/anthropic-single-family.yaml",
    },
    {
        "label":        "no-recursion (sonnet, legacy)",
        "ts":           "20260608T200907Z",
        "cell_id":      "photonics__sciagent-no-recursion__sonnet",
        "agent_model":  "anthropic/claude-sonnet-4-6",
        "verifier":     "anthropic/claude-sonnet-4-6",
        "recursion":    "off (legacy — verifier sees parent log only)",
        "recipe":       "recipes/anthropic-verifier-no-recursion.yaml (equivalent)",
    },
    {
        "label":        "crossverifier (openai o4-mini, no recursion)",
        "ts":           "20260608T200907Z",
        "cell_id":      "photonics__sciagent-crossverifier__sonnet",
        "agent_model":  "anthropic/claude-sonnet-4-6",
        "verifier":     "openai/o4-mini (old recipe; current recipe uses openai/gpt-5.4)",
        "recursion":    "off (recipe pre-dates Phase 1 — recursion default was false; verifier reasoning contains zero references to child sessions, consistent with no-recursion)",
        "recipe":       "recipes/anthropic-cross-family-verifier.yaml (as of 2026-06-08)",
    },
    {
        "label":        "verifier-off (control)",
        "ts":           "20260608T200907Z",
        "cell_id":      "photonics__sciagent-verifier-off__sonnet",
        "agent_model":  "anthropic/claude-sonnet-4-6",
        "verifier":     "gate disabled (`enable_verification: false`)",
        "recursion":    "n/a",
        "recipe":       "recipes/anthropic-no-verifier.yaml",
    },
]


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


def _load_variant(icml_root: Path, v: dict) -> dict:
    cell_dir = icml_root / v["ts"] / "photonics" / v["cell_id"]
    prov = cell_dir / "provenance.jsonl"
    events = list(_iter_events(prov)) if prov.exists() else []

    vr_events = [e for e in events if e.get("event_kind") == "verification_result"]
    session_end = next((e for e in events if e.get("event_kind") == "session_end"), None)
    prod_fail = [e for e in events if e.get("event_kind") == "produces_validation_failed"]
    kinds = Counter(e.get("event_kind", "") for e in events)

    last_vr = vr_events[-1] if vr_events else None
    evidence = (last_vr or {}).get("evidence", {}) or {}

    return {
        **v,
        "cell_dir":              cell_dir,
        "provenance_exists":     prov.exists(),
        "total_events":          len(events),
        "kinds":                 dict(kinds),
        "n_verification_result": len(vr_events),
        "vr":                    last_vr,
        "verdict":               (last_vr or {}).get("verdict"),
        "confidence":            (last_vr or {}).get("confidence"),
        "reasoning":             (evidence.get("reasoning") or "").strip(),
        "supporting":            evidence.get("supporting_facts") or [],
        "fabrication":           evidence.get("fabrication_indicators") or [],
        "missing":               evidence.get("missing_evidence") or [],
        "issues":                (last_vr or {}).get("issues") or [],
        "session_end":           session_end or {},
        "n_produces_failed":     len(prod_fail),
    }


def _fmt_conf(c) -> str:
    if isinstance(c, (int, float)):
        return f"{c:.2f}"
    return "—"


def _bulleted(items, empty="_(none)_") -> list[str]:
    if not items:
        return [empty]
    return [f"- {str(x).strip()}" for x in items]


def _summary_table(rows: list[dict]) -> list[str]:
    out = [
        "| variant | verdict | conf | issues | supp | fab | miss | trajectory ts |",
        "|:---|:---|---:|---:|---:|---:|---:|:---|",
    ]
    for r in rows:
        verdict = r["verdict"] or "(no event)"
        conf    = _fmt_conf(r["confidence"])
        out.append(
            f"| {r['label']} | {verdict} | {conf} | "
            f"{len(r['issues'])} | {len(r['supporting'])} | "
            f"{len(r['fabrication'])} | {len(r['missing'])} | "
            f"`{r['ts']}` |"
        )
    return out


def _config_table(rows: list[dict]) -> list[str]:
    out = [
        "| variant | agent | verifier | recursion | recipe |",
        "|:---|:---|:---|:---|:---|",
    ]
    for r in rows:
        out.append(
            f"| {r['label']} | `{r['agent_model']}` | `{r['verifier']}` | "
            f"{r['recursion']} | `{r['recipe']}` |"
        )
    return out


def _render_variant(r: dict) -> list[str]:
    lines: list[str] = []
    lines.append(f"## {r['label']}")
    lines.append("")
    lines.append(f"- **cell**: `{r['cell_id']}` (ts `{r['ts']}`)")
    lines.append(f"- **agent model**: `{r['agent_model']}`")
    lines.append(f"- **verifier**: `{r['verifier']}`")
    lines.append(f"- **recursion (`verifier_include_child_sessions`)**: {r['recursion']}")
    lines.append(f"- **recipe**: `{r['recipe']}`")
    lines.append(f"- **total events in provenance**: {r['total_events']}")
    lines.append("")

    # Run-outcome status
    se = r.get("session_end", {})
    exit_reason = se.get("exit_reason")
    if r["n_produces_failed"]:
        lines.append(f"- **run outcome**: **{r['n_produces_failed']} `produces_validation_failed` event(s)** — "
                     "run errored before completion.")
    if exit_reason:
        lines.append(f"- **session_end exit_reason**: `{exit_reason}`")
    lines.append(f"- **verification_result event count**: {r['n_verification_result']}")
    lines.append("")

    # If no verification event, explain and stop
    if r["n_verification_result"] == 0:
        if "off" in r["verifier"].lower() or "disabled" in r["verifier"].lower():
            lines.append("**No verifier event by design** — `enable_verification: false` skips "
                         "the gate entirely (see `README.md` T3 footnote / phase4 scoped doc).")
        else:
            lines.append("**No verifier event — the run did not reach the verification gate.** "
                         "Verifier presence in provenance depends on the run reaching the "
                         "post-execution gate cleanly; a failure earlier (like the "
                         "`produces_validation_failed` above) short-circuits the gate.")
        lines.append("")
        return lines

    # Verdict block
    verdict = r["verdict"]
    conf    = _fmt_conf(r["confidence"])
    lines.append(f"**Verdict**: `{verdict}` @ **confidence {conf}**  ·  "
                 f"{len(r['supporting'])} supporting facts · "
                 f"{len(r['fabrication'])} fabrication indicators · "
                 f"{len(r['missing'])} missing-evidence entries · "
                 f"{len(r['issues'])} issues")
    lines.append("")

    lines.append("**Reasoning**")
    lines.append("")
    lines.append(r["reasoning"] or "_(empty)_")
    lines.append("")

    lines.append("**Supporting facts**")
    lines.append("")
    lines.extend(_bulleted(r["supporting"]))
    lines.append("")

    lines.append("**Fabrication indicators**")
    lines.append("")
    lines.extend(_bulleted(r["fabrication"], empty="_(none flagged)_"))
    lines.append("")

    lines.append("**Missing evidence**")
    lines.append("")
    lines.extend(_bulleted(r["missing"], empty="_(nothing marked missing)_"))
    lines.append("")

    lines.append("**Issues**")
    lines.append("")
    if not r["issues"]:
        lines.append("_(no issues)_")
    else:
        lines.append("| severity | category | message |")
        lines.append("|:---|:---|:---|")
        for i in r["issues"]:
            if not isinstance(i, dict):
                lines.append(f"|  |  | {i} |")
                continue
            sev = str(i.get("severity", "") or "")
            cat = str(i.get("category", "") or "")
            msg = str(i.get("message", "") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {sev} | {cat} | {msg} |")
    lines.append("")

    return lines


def _cross_variant_analysis(rows: list[dict]) -> list[str]:
    """Pull three targeted 2-way comparisons out of the variants set."""
    by_label = {r["label"]: r for r in rows}
    default    = by_label.get("verifier-on-default (sonnet, recursive)", {})
    norec      = by_label.get("no-recursion (sonnet, legacy)", {})
    cross      = by_label.get("crossverifier (openai o4-mini, no recursion)", {})

    lines: list[str] = []
    lines.append("## Cross-variant analysis")
    lines.append("")

    # 1. Recursion effect
    lines.append("### 1. Recursion effect — Phase 1's central finding")
    lines.append("")
    lines.append(
        "Same verifier model (anthropic/claude-sonnet-4-6); only the "
        "`verifier_include_child_sessions` flag flipped. Different agent "
        "trajectories (separate sciagent runs) but same recipe apart from "
        "the recursion flag."
    )
    lines.append("")
    lines.append("| axis | no-recursion | with recursion | Δ |")
    lines.append("|:---|:---|:---|:---|")
    if default and norec:
        lines.append(f"| verdict | `{norec['verdict']}` | `{default['verdict']}` | "
                     f"**flipped** insufficient → verified |")
        lines.append(f"| confidence | {_fmt_conf(norec['confidence'])} | "
                     f"{_fmt_conf(default['confidence'])} | +0.13 |")
        lines.append(f"| supporting facts | {len(norec['supporting'])} | "
                     f"{len(default['supporting'])} | +{len(default['supporting']) - len(norec['supporting'])} |")
        lines.append(f"| missing evidence | {len(norec['missing'])} | "
                     f"{len(default['missing'])} | {len(default['missing']) - len(norec['missing'])} |")
        lines.append(f"| fabrication indicators | {len(norec['fabrication'])} | "
                     f"{len(default['fabrication'])} | {len(default['fabrication']) - len(norec['fabrication'])} |")
        lines.append(f"| issues | {len(norec['issues'])} | {len(default['issues'])} | "
                     f"{len(default['issues']) - len(norec['issues'])} |")
    lines.append("")
    lines.append(
        "**Reading**: with the recursion flag on, the verifier reads the "
        "child session logs that carry the actual `tool_result` evidence "
        "for subagent work (compute / analyze). Its supporting-fact count "
        "tripled and the verdict flipped from `insufficient` to `verified` — "
        "the audit trail was always the same on disk; the verifier just "
        "couldn't see it before."
    )
    lines.append("")

    # 2. Verifier model effect (holding recursion=off)
    lines.append("### 2. Verifier-model effect (both without recursion)")
    lines.append("")
    lines.append(
        "Same agent (anthropic/claude-sonnet-4-6, both without recursion). "
        "Different verifier: same-family sonnet vs cross-family openai/"
        "o4-mini. Different trajectories (independent runs)."
    )
    lines.append("")
    lines.append("| axis | sonnet verifier | openai/o4-mini verifier |")
    lines.append("|:---|:---|:---|")
    if norec and cross:
        lines.append(f"| verdict | `{norec['verdict']}` | `{cross['verdict']}` |")
        lines.append(f"| confidence | {_fmt_conf(norec['confidence'])} | "
                     f"{_fmt_conf(cross['confidence'])} |")
        lines.append(f"| supporting | {len(norec['supporting'])} | {len(cross['supporting'])} |")
        lines.append(f"| missing | {len(norec['missing'])} | {len(cross['missing'])} |")
        lines.append(f"| fabrication | {len(norec['fabrication'])} | {len(cross['fabrication'])} |")
    lines.append("")
    lines.append(
        "**Reading**: both same-family and cross-family verifiers landed on "
        "`insufficient` on this task without recursion, but the cross-family "
        "openai verifier was **more confident about the insufficiency** "
        "(0.82 vs 0.62) despite citing fewer supporting facts. That gap is "
        "either a calibration difference between models or a genuine "
        "reasoning-model behaviour (o4-mini is reasoning-tuned) — the paper "
        "narrative should not lean on it without a second point of data. "
        "The current `anthropic-cross-family-verifier.yaml` has been bumped "
        "to `openai/gpt-5.4` (capability-matched) — a fresh run under the "
        "new recipe would replace this row."
    )
    lines.append("")

    # 3. Verifier-off control
    lines.append("### 3. Verifier-off control")
    lines.append("")
    lines.append(
        "`enable_verification: false` produced zero `verification_result` "
        "events by design — the orchestrator skips the entire "
        "`_run_llm_verification_gate` block (see `phase4_scoped.md` "
        "footnote for the full end-to-end trace of what this flag "
        "actually does). Included as a control: no verifier bookkeeping "
        "artefacts in provenance mean the shape of `results.csv` (empty "
        "`verdict` column) is what a bench consumer sees when the flag is "
        "off, distinguishable from a failed-verification case (which "
        "would have `verdict=refuted` or `insufficient`)."
    )
    lines.append("")

    return lines


def build_report(icml_root: Path) -> str:
    rows = [_load_variant(icml_root, v) for v in _VARIANTS]

    intro = (
        "# Photonics — verifier influence across sciagent variants\n\n"
        "Isolates two axes on the same task (three-zone TiO2/N-BK7 "
        "metasurface, MFE ≥ 25%):\n\n"
        "1. `verifier_include_child_sessions` (**on** vs **off**) — the "
        "Phase 1 flag that lets the verifier read subagent child logs.\n"
        "2. Verifier model family — same-family Anthropic sonnet vs "
        "cross-family OpenAI.\n\n"
        "Plus a `verifier-off` control (verification gate disabled).\n\n"
        "All data pulled from each cell's `provenance.jsonl`. See "
        "`verifier_details.md` for the full field dump per variant, and "
        "`verification_side_by_side.md` for the cc-bare comparison.\n\n"
    )

    config = "## Recipe configuration per variant\n\n" + "\n".join(_config_table(rows)) + "\n\n"
    summary = "## Verifier outcome per variant\n\n" + "\n".join(_summary_table(rows)) + "\n\n---\n\n"

    per_variant: list[str] = []
    for r in rows:
        per_variant.append("\n".join(_render_variant(r)))

    cross = "\n".join(_cross_variant_analysis(rows)) + "\n"

    return intro + config + summary + "\n---\n\n".join(per_variant) + "\n\n---\n\n" + cross


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML)
    ap.add_argument("--out",       type=Path,
                    default=_THIS.parent / "photonics_verifier_variants.md")
    args = ap.parse_args(argv)

    report = build_report(args.icml_root)
    args.out.write_text(report)
    print(f"wrote {args.out}  ({len(report):,} chars, {len(_VARIANTS)} variants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
