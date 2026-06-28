#!/usr/bin/env python3
"""Bench-side post-hoc audit of finished cells.

Splits the audit into two independent reports — both happen on the bench
side, neither modifies sciagent:

  1. HONESTY — does the agent's claim match what the trajectory actually
     shows? Same prompt (`prompts/verification_honesty.md`), same standard,
     applied uniformly to every cell regardless of adapter. Watches for
     fabrication, target degradation, phantom artifacts. The trail format
     (provenance vs. stream-json) is treated as irrelevant — a `tool_use`
     with a non-empty `tool_result` is evidence of external execution
     either way.

  2. EFFICIENCY — pure aggregation from results.csv + per-cell
     cost_breakdown.csv. No LLM calls. Tokens / cost / cache / tools.

These are deliberately separate: a cell can be honest but expensive, or
cheap but fabricates. Conflating the two is exactly why the original
verifier_evidence rows came out non-comparable.

Usage:
  ./tools/reverify_cells.py results/<TS>/<task> \\
      --task tasks/photonics.yaml \\
      --verifier-model anthropic/claude-sonnet-4-6 \\
      [--verifier-model openai/gpt-5] ...

Outputs in <matrix_dir>:
  verification_results.csv       — wide, one row per cell, axes per verifier
  verification_results_long.csv  — long, one row per (cell, verifier)
  efficiency_results.csv         — one row per cell, no LLM judgment

Outputs per cell:
  verification_honesty_<alias>.json     — full parsed axes + verdict
  verification_raw_response_<alias>.txt — exact LLM response
  verification_input_user_msg.txt       — the prompt we sent (debug)
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
from typing import Optional

import litellm
import yaml

_THIS = pathlib.Path(__file__).resolve()
_BENCH = _THIS.parent.parent
sys.path.insert(0, str(_BENCH))

from tools.render_transcript import (  # noqa: E402
    _read_jsonl,
    render_claude_transcript,
    render_sciagent_provenance,
)

_CLAUDE_PROJECTS = pathlib.Path.home() / ".claude" / "projects"
# Mirror of adapters/sciagent.py SESSIONS_ROOT. Each subagent invocation
# writes its full tool_call/tool_result trail here; the parent log only
# carries summary events. The reverify renderer follows the same
# child_session_id pointer the cost-rollup code uses, so the verifier
# sees the actual chain of custody for any numbers computed inside a
# subagent (otherwise it dings the cell for an unauditable claim that
# IS auditable — just one log file over).
_SCIAGENT_SESSIONS_ROOT = pathlib.Path.home() / ".sciagent" / "sessions"
# Sonnet 4.6 and GPT-5 both have 200K+ context. Keeping the rendered
# trajectory at 100K previously chopped sciagent's dense provenance
# right at the load-bearing tool_results. 180K leaves ~20K headroom
# for the prompt + claim + criteria + project listing on a 200K
# context budget.
_MAX_TRAJECTORY_CHARS = 180_000
_HONESTY_PROMPT = _BENCH / "prompts" / "verification_honesty.md"

_DEFAULT_VERIFIERS = [
    "anthropic/claude-sonnet-4-6",
    # Matches sciagent-cli's top-tier OpenAI model (per
    # recipes/openai-single-family.yaml).
    "openai/gpt-5.4",
]

# Fixed seed used for OpenAI gpt-5 family models (gpt-5, gpt-5.1,
# gpt-5.4, ...). They reject temperature != 1, so we lean on OpenAI's
# `seed` parameter for best-effort determinism — documented to produce
# the same output for the same (prompt, seed) pair on the same backend
# model version. Anthropic models pin temperature=0 instead.
_OPENAI_SEED = 7

_AXES = [
    "external_execution",
    "claim_consistency",
    "honest_failure_reporting",
    "no_phantom_artifacts",
]
_VALID_VERDICTS = {"supported", "partial", "refuted", "insufficient"}


# ---------------------------------------------------------------------------
# Aliases + path encoding
# ---------------------------------------------------------------------------


def _model_alias(model: str) -> str:
    """Filesystem-safe tag including provider AND model name so two models
    from the same provider don't collide.

      'anthropic/claude-sonnet-4-6' → 'anthropic_claude_sonnet_4_6'
      'openai/gpt-5'                → 'openai_gpt_5'
    """
    return model.replace("/", "_").replace("-", "_").replace(".", "_")


def _encoded_cwd(cwd: pathlib.Path) -> str:
    """Match Claude Code's own dir encoding: '/' AND '_' → '-'."""
    return str(cwd.resolve()).replace("/", "-").replace("_", "-")


# ---------------------------------------------------------------------------
# Trajectory rendering
# ---------------------------------------------------------------------------


def _find_session_id_in_stream(stdout_path: pathlib.Path) -> Optional[str]:
    if not stdout_path.exists():
        return None
    for ev in _read_jsonl(stdout_path):
        sid = ev.get("session_id") if isinstance(ev, dict) else None
        if sid:
            return sid
    return None


def _locate_cc_transcript(cell_dir: pathlib.Path) -> Optional[pathlib.Path]:
    """Best-available Claude Code trajectory for a CC cell."""
    local = cell_dir / "claude_transcript.jsonl"
    if local.exists():
        return local
    stdout = cell_dir / "stdout.txt"
    sid = _find_session_id_in_stream(stdout)
    if sid:
        project_dir = cell_dir / "project"
        cand = _CLAUDE_PROJECTS / _encoded_cwd(project_dir) / f"{sid}.jsonl"
        if cand.exists():
            return cand
    return stdout if stdout.exists() else None


def _render_sciagent_full(parent_log: pathlib.Path) -> tuple[str, int]:
    """Render the parent provenance plus every subagent log it references,
    recursively. Returns (rendered_text, n_subagent_logs_inlined).

    The parent log only carries summary events for subagent invocations
    (`subagent_completed` with a `child_session_id`). The actual
    `tool_call`/`tool_result` chain — the auditable evidence — lives in
    ~/.sciagent/sessions/<child_session_id>/provenance.jsonl. Without
    inlining those, the verifier cannot trace any number computed inside
    a subagent and (correctly) flags it as an audit gap. That gap is
    fixable on the bench side; sciagent already wrote the data."""
    out_parts: list[str] = []
    visited: set[pathlib.Path] = set()
    n_subagents = 0

    def walk(log_path: pathlib.Path, depth: int, label: str) -> None:
        nonlocal n_subagents
        resolved = log_path.resolve()
        if resolved in visited:
            return
        visited.add(resolved)
        events = list(_read_jsonl(log_path))
        if not events:
            return
        header = (
            f"\n\n---\n\n## {label} (depth={depth}, "
            f"path={log_path})\n\n"
        )
        out_parts.append(header)
        out_parts.append(render_sciagent_provenance(events))
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("event_kind") != "subagent_completed":
                continue
            child_id = ev.get("child_session_id")
            if not child_id:
                continue
            child_log = _SCIAGENT_SESSIONS_ROOT / child_id / "provenance.jsonl"
            if not child_log.exists():
                out_parts.append(
                    f"\n_(referenced subagent log {child_id} not found "
                    f"on disk — audit gap remains)_\n"
                )
                continue
            n_subagents += 1
            sub_label = f"SUBAGENT {ev.get('subagent_name') or 'subagent'} "
            sub_label += f"(child_session_id={child_id})"
            walk(child_log, depth + 1, sub_label)

    walk(parent_log, depth=0, label="PARENT SESSION")
    return "".join(out_parts), n_subagents


def _render_trajectory(cell_dir: pathlib.Path) -> tuple[Optional[str], Optional[pathlib.Path], str]:
    prov = cell_dir / "provenance.jsonl"
    if prov.exists():
        events = list(_read_jsonl(prov))
        if not events:
            return None, prov, "sciagent_provenance_empty"
        rendered, n_sub = _render_sciagent_full(prov)
        kind = (
            f"sciagent_provenance+{n_sub}sub" if n_sub
            else "sciagent_provenance"
        )
        return rendered, prov, kind

    cc_log = _locate_cc_transcript(cell_dir)
    if cc_log is None:
        return None, None, "none"
    events = list(_read_jsonl(cc_log))
    if not events:
        return None, cc_log, "cc_empty"
    return render_claude_transcript(events), cc_log, "cc_transcript"


# ---------------------------------------------------------------------------
# Project listing for the artifact-existence axis
# ---------------------------------------------------------------------------


def _list_project_files(project_dir: pathlib.Path, limit: int = 200) -> tuple[str, int]:
    """Render a markdown listing of files the agent wrote into ./project/.
    Used by the verifier to check phantom artifacts (Axis 4)."""
    if not project_dir.exists():
        return "_(no ./project/ directory found)_", 0
    rows: list[tuple[str, int]] = []
    for p in sorted(project_dir.rglob("*")):
        if p.is_dir():
            continue
        try:
            sz = p.stat().st_size
        except OSError:
            sz = -1
        rel = p.relative_to(project_dir)
        rows.append((str(rel), sz))
        if len(rows) >= limit:
            break
    if not rows:
        return "_(empty ./project/ — no artifacts)_", 0
    lines = [f"- `{rel}` ({sz:,} bytes)" for rel, sz in rows]
    if len(rows) >= limit:
        lines.append(f"_(listing truncated at {limit} entries)_")
    return "\n".join(lines), len(rows)


# Text-ish file types we inline so the verifier can check the agent's
# prose against the actual file contents (not just truncated tool_result
# previews). Binary formats (.png, .pdf, .h5, .npz, .parquet, …) are
# acknowledged in the listing but their bytes are not inlined.
_INLINE_SUFFIXES = {
    ".json", ".csv", ".tsv", ".md", ".txt", ".yaml", ".yml",
    ".log", ".out", ".jsonl",
    # Code: the agent's own scripts are evidence of what it did.
    ".py", ".sh", ".r", ".R", ".jl", ".m", ".ipynb",
}

_PER_FILE_CHARS = 6_000     # head+tail budget per file
_DATA_BLOCK_CHARS = 70_000  # total budget across all inlined files


def _read_text_capped(path: pathlib.Path, cap: int) -> str:
    """Read up to `cap` chars; if longer, head + tail split with a marker."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"_(read error: {e})_"
    if len(text) <= cap:
        return text
    half = cap // 2
    return (
        text[:half]
        + f"\n\n... [FILE TRUNCATED — middle {len(text) - cap} chars dropped] ...\n\n"
        + text[-half:]
    )


def _render_project_data_files(project_dir: pathlib.Path) -> tuple[str, int]:
    """Inline the contents of text-ish files the agent wrote into
    `./project/`. Returns (markdown_block, n_files_inlined).

    Rationale: a verifier that only sees tool_result previews cannot
    distinguish honest prose summarization of a JSON/CSV the agent
    actually wrote from a fabricated claim. With the file content in
    the audit packet, *"Zone 1 drops to 10% at +10°"* can be checked
    against the actual array in `mfe_analysis.json` instead of against
    a stale, truncated tool_result snippet.

    Note: `./project/` typically holds only the agent's curated final
    outputs. Intermediate computation legitimately lives only in
    tool_results — absence-from-./project/ is NOT by itself fabrication."""
    if not project_dir.exists():
        return "_(no ./project/ directory; data files unavailable)_", 0
    parts: list[str] = []
    total = 0
    n_inlined = 0
    for p in sorted(project_dir.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix.lower() not in _INLINE_SUFFIXES:
            continue
        if total >= _DATA_BLOCK_CHARS:
            break
        remaining = _DATA_BLOCK_CHARS - total
        per_file = min(_PER_FILE_CHARS, remaining)
        body = _read_text_capped(p, per_file)
        rel = p.relative_to(project_dir)
        header = f"\n### `./project/{rel}` ({p.stat().st_size:,} bytes)\n\n```\n"
        chunk = header + body + "\n```\n"
        parts.append(chunk)
        total += len(chunk)
        n_inlined += 1
    if not parts:
        return "_(no text-format files in ./project/ to inline)_", 0
    return "".join(parts), n_inlined


# ---------------------------------------------------------------------------
# Honesty audit (one LLM call per cell per verifier)
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _clamp01(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _build_user_msg(
    *,
    task_prompt: str,
    verification_criteria: dict,
    claim_text: str,
    project_listing: str,
    project_data_files: str,
    trajectory_text: Optional[str],
    session_log_path: Optional[pathlib.Path],
    workdir: pathlib.Path,
) -> str:
    criteria_block = json.dumps(verification_criteria, indent=2)

    if trajectory_text:
        if len(trajectory_text) > _MAX_TRAJECTORY_CHARS:
            head = trajectory_text[: _MAX_TRAJECTORY_CHARS // 2]
            tail = trajectory_text[-_MAX_TRAJECTORY_CHARS // 2 :]
            trajectory_text = (
                head
                + f"\n\n... [TRAJECTORY TRUNCATED — middle "
                f"{len(trajectory_text) - _MAX_TRAJECTORY_CHARS} chars dropped] ...\n\n"
                + tail
            )
        trail_block = (
            f"## Trajectory (rendered inline)\n\n"
            f"Path: {session_log_path or '(rendered from transcript)'}\n\n"
            f"{trajectory_text}\n"
        )
    elif session_log_path is not None:
        trail_block = (
            f"## Trajectory\n\nPath: {session_log_path}\n"
            f"_(content not provided inline; treat the absence as evidence)_\n"
        )
    else:
        trail_block = (
            f"## Trajectory\n\n_(none — this cell produced no audit trail)_\n"
        )

    return (
        f"Workdir: {workdir}\n\n"
        f"## Original task\n\n{task_prompt}\n\n"
        f"## Verification criteria\n\n```json\n{criteria_block}\n```\n\n"
        f"## Agent's final claim\n\n{claim_text}\n\n"
        f"## Files produced in ./project/\n\n{project_listing}\n\n"
        f"## Data files (contents) — agent's curated final outputs\n\n"
        f"{project_data_files}\n\n"
        f"{trail_block}"
    )


def _audit_honesty(
    *,
    verifier_model: str,
    user_msg: str,
) -> tuple[dict, str]:
    """One LLM call. Returns (parsed_evidence, raw_response_text).

    Determinism strategy:
      * gpt-4*, claude-sonnet-4*, claude-haiku-*: pin temperature=0.0.
      * OpenAI gpt-5 family: temperature=0 is rejected. Use
        `seed=_OPENAI_SEED` — OpenAI's documented best-effort
        determinism (same (prompt, seed) → same output on a fixed
        backend model version).
      * Anthropic claude-opus-4 family: temperature is deprecated;
        the model manages its own sampling internally. Pass neither
        temperature nor seed — Opus reasoning models are near-
        deterministic by default."""
    template = _HONESTY_PROMPT.read_text(encoding="utf-8")
    kwargs: dict = {
        "model": verifier_model,
        "messages": [
            {"role": "system", "content": template},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 4096,
    }
    if "gpt-5" in verifier_model:
        kwargs["seed"] = _OPENAI_SEED
    elif "claude-opus-4" in verifier_model:
        # No temperature, no seed — model manages its own sampling.
        pass
    else:
        kwargs["temperature"] = 0.0
    response = litellm.completion(**kwargs)
    try:
        raw = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raw = ""

    parsed = _extract_json(raw)
    verdict = parsed.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = "insufficient"
    axes = {axis: _clamp01(parsed.get(axis, 0.0)) for axis in _AXES}
    confidence = _clamp01(parsed.get("confidence", 0.0))

    reasoning = parsed.get("reasoning") or ""
    if not isinstance(reasoning, str):
        try:
            reasoning = json.dumps(reasoning, ensure_ascii=False)
        except (TypeError, ValueError):
            reasoning = str(reasoning)

    evidence = {
        "verdict": verdict,
        "confidence": confidence,
        **axes,
        "fabrication_flags": parsed.get("fabrication_flags") or [],
        "degradation_flags": parsed.get("degradation_flags") or [],
        "phantom_artifact_flags": parsed.get("phantom_artifact_flags") or [],
        "reasoning": reasoning,
    }
    return evidence, raw


# ---------------------------------------------------------------------------
# Efficiency report (no LLM)
# ---------------------------------------------------------------------------


_RESULTS_COLS = [
    "cost_total_usd", "cost_llm_usd", "cost_compute_usd",
    "tokens_in", "tokens_out", "iterations", "tool_calls",
    "wall_seconds", "success", "error",
]


def _load_results_csv(matrix_dir: pathlib.Path) -> dict[str, dict]:
    p = matrix_dir / "results.csv"
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8", newline="") as f:
        return {r["cell_id"]: r for r in csv.DictReader(f)}


def _summarize_cost_breakdown(cell_dir: pathlib.Path) -> dict:
    out = {
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "tools_used_top6": "",
        "n_breakdown_rows": 0,
    }
    p = cell_dir / "cost_breakdown.csv"
    if not p.exists():
        return out
    tool_counts: dict[str, int] = {}
    with p.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            out["n_breakdown_rows"] += 1
            for k_in, k_out in (
                ("cache_read", "cache_read_tokens"),
                ("cache_create", "cache_create_tokens"),
            ):
                try:
                    out[k_out] += int(r.get(k_in) or 0)
                except (TypeError, ValueError):
                    pass
            tool = (r.get("tool") or "").strip()
            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
    if tool_counts:
        top = sorted(tool_counts.items(), key=lambda kv: -kv[1])[:6]
        out["tools_used_top6"] = " ".join(f"{t}:{n}" for t, n in top)
    return out


def _adapter_of(cell_id: str) -> str:
    return "sciagent" if "__sciagent" in cell_id else "claude_code"


# ---------------------------------------------------------------------------
# Per-cell audit
# ---------------------------------------------------------------------------


def audit_cell(
    cell_dir: pathlib.Path,
    *,
    task_spec: dict,
    verifier_models: list[str],
) -> list[dict]:
    cell_id = cell_dir.name
    adapter = _adapter_of(cell_id)
    rendered, src_path, src_kind = _render_trajectory(cell_dir)
    project_listing, n_files = _list_project_files(cell_dir / "project")
    project_data_files, n_inlined = _render_project_data_files(cell_dir / "project")
    claim = (cell_dir / "result.txt").read_text(encoding="utf-8") if (cell_dir / "result.txt").exists() else ""

    user_msg = _build_user_msg(
        task_prompt=task_spec["prompt"],
        verification_criteria=task_spec.get("verification_criteria") or {},
        claim_text=claim,
        project_listing=project_listing,
        project_data_files=project_data_files,
        trajectory_text=rendered,
        session_log_path=src_path,
        workdir=cell_dir,
    )
    (cell_dir / "verification_input_user_msg.txt").write_text(user_msg, encoding="utf-8")

    rows: list[dict] = []
    for model in verifier_models:
        alias = _model_alias(model)
        try:
            evidence, raw = _audit_honesty(verifier_model=model, user_msg=user_msg)
        except Exception as e:
            print(f"  !! {alias}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            rows.append({
                "cell_id": cell_id,
                "adapter": adapter,
                "verifier": alias,
                "verifier_model": model,
                "trajectory_source": src_kind,
                "trajectory_chars": len(rendered) if rendered else 0,
                "n_project_files": n_files,
                "verdict": "error",
                "confidence": "0.000",
                **{a: "0.000" for a in _AXES},
                "n_fabrication_flags": 0,
                "n_degradation_flags": 0,
                "n_phantom_artifact_flags": 0,
                "raw_response_chars": 0,
                "reasoning_snippet": f"{type(e).__name__}: {e}",
            })
            continue

        (cell_dir / f"verification_honesty_{alias}.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        (cell_dir / f"verification_raw_response_{alias}.txt").write_text(raw, encoding="utf-8")

        reasoning = evidence["reasoning"].strip().replace("\n", " ")
        rows.append({
            "cell_id": cell_id,
            "adapter": adapter,
            "verifier": alias,
            "verifier_model": model,
            "trajectory_source": src_kind,
            "trajectory_chars": len(rendered) if rendered else 0,
            "n_project_files": n_files,
            "verdict": evidence["verdict"],
            "confidence": f"{evidence['confidence']:.3f}",
            **{a: f"{evidence[a]:.3f}" for a in _AXES},
            "n_fabrication_flags": len(evidence["fabrication_flags"]),
            "n_degradation_flags": len(evidence["degradation_flags"]),
            "n_phantom_artifact_flags": len(evidence["phantom_artifact_flags"]),
            "raw_response_chars": len(raw),
            "reasoning_snippet": reasoning[:240] + ("…" if len(reasoning) > 240 else ""),
        })
        flags = (
            f"{len(evidence['fabrication_flags'])}f/"
            f"{len(evidence['degradation_flags'])}d/"
            f"{len(evidence['phantom_artifact_flags'])}p"
        )
        axes_str = " ".join(f"{a[:4]}={evidence[a]:.2f}" for a in _AXES)
        print(
            f"  ✓ {alias}: {evidence['verdict']} (conf {evidence['confidence']:.2f}, "
            f"{axes_str}, flags {flags})",
            flush=True,
        )
    return rows


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------


_LONG_FIELDS = [
    "cell_id", "adapter", "verifier", "verifier_model",
    "trajectory_source", "trajectory_chars", "n_project_files",
    "verdict", "confidence",
    *_AXES,
    "n_fabrication_flags", "n_degradation_flags", "n_phantom_artifact_flags",
    "raw_response_chars", "reasoning_snippet",
]


def _read_existing_long(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _merge_long_rows(prior: list[dict], new: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for r in prior:
        by_key[(r["cell_id"], r["verifier_model"])] = r
    for r in new:
        by_key[(r["cell_id"], r["verifier_model"])] = r
    return [by_key[k] for k in sorted(by_key)]


def _write_wide_verification(rows: list[dict], path: pathlib.Path) -> None:
    """One row per cell, per-verifier verdict + axes columns side by side."""
    by_cell: dict[str, dict] = {}
    base = ["cell_id", "adapter", "trajectory_source", "trajectory_chars", "n_project_files"]
    aliases: list[str] = []
    for r in rows:
        cid = r["cell_id"]
        if cid not in by_cell:
            by_cell[cid] = {k: r[k] for k in base}
        alias = r["verifier"]
        if alias not in aliases:
            aliases.append(alias)
        by_cell[cid][f"verdict_{alias}"] = r["verdict"]
        by_cell[cid][f"confidence_{alias}"] = r["confidence"]
        for a in _AXES:
            by_cell[cid][f"{a}_{alias}"] = r[a]
        for k in ("n_fabrication_flags", "n_degradation_flags", "n_phantom_artifact_flags"):
            by_cell[cid][f"{k}_{alias}"] = r[k]

    aliases.sort()
    fields = list(base)
    for a in aliases:
        fields.append(f"verdict_{a}")
        fields.append(f"confidence_{a}")
        for ax in _AXES:
            fields.append(f"{ax}_{a}")
        fields += [
            f"n_fabrication_flags_{a}",
            f"n_degradation_flags_{a}",
            f"n_phantom_artifact_flags_{a}",
        ]

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for cid in sorted(by_cell):
            w.writerow(by_cell[cid])


def _write_efficiency(matrix_dir: pathlib.Path, path: pathlib.Path) -> None:
    """No LLM. Rolls up per-cell economics from results.csv + cost_breakdown.csv."""
    results = _load_results_csv(matrix_dir)
    cells = sorted(p for p in matrix_dir.iterdir() if p.is_dir())

    fields = [
        "cell_id", "adapter",
        *_RESULTS_COLS,
        "cache_read_tokens", "cache_create_tokens", "tools_used_top6", "n_breakdown_rows",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for cell_dir in cells:
            cid = cell_dir.name
            row: dict = {"cell_id": cid, "adapter": _adapter_of(cid)}
            src = results.get(cid, {})
            for col in _RESULTS_COLS:
                row[col] = src.get(col, "")
            row.update(_summarize_cost_breakdown(cell_dir))
            w.writerow(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("matrix_dir", type=pathlib.Path,
                    help="Path like results/<TS>/photonics")
    ap.add_argument("--task", type=pathlib.Path, required=True,
                    help="tasks/<task>.yaml — pulls prompt + verification_criteria")
    ap.add_argument("--verifier-model", action="append", default=None,
                    help=f"Repeat to add verifiers. Default: {_DEFAULT_VERIFIERS}")
    ap.add_argument("--cell", action="append", default=[],
                    help="Restrict to one or more cell ids (default: all)")
    ap.add_argument("--efficiency-only", action="store_true",
                    help="Skip the LLM audit; just rebuild efficiency_results.csv")
    args = ap.parse_args(argv)

    task_spec = yaml.safe_load(args.task.read_text(encoding="utf-8"))
    verifier_models = args.verifier_model or list(_DEFAULT_VERIFIERS)

    # Efficiency report is cheap, always (re)generate it.
    eff_csv = args.matrix_dir / "efficiency_results.csv"
    _write_efficiency(args.matrix_dir, eff_csv)
    print(f"Wrote {eff_csv}")

    if args.efficiency_only:
        return 0

    cells = sorted(p for p in args.matrix_dir.iterdir() if p.is_dir())
    if args.cell:
        cells = [c for c in cells if c.name in set(args.cell)]
    if not cells:
        print(f"No cells found under {args.matrix_dir}", file=sys.stderr)
        return 1

    print(f"\nverifiers: {verifier_models}\n")
    long_rows: list[dict] = []
    for cell_dir in cells:
        print(f"→ {cell_dir.name}", flush=True)
        try:
            long_rows.extend(audit_cell(
                cell_dir,
                task_spec=task_spec,
                verifier_models=verifier_models,
            ))
        except Exception as e:
            print(f"  !! {type(e).__name__}: {e}", file=sys.stderr)
            for model in verifier_models:
                alias = _model_alias(model)
                long_rows.append({
                    "cell_id": cell_dir.name,
                    "adapter": _adapter_of(cell_dir.name),
                    "verifier": alias,
                    "verifier_model": model,
                    "trajectory_source": "error",
                    "trajectory_chars": 0,
                    "n_project_files": 0,
                    "verdict": "error",
                    "confidence": "0.000",
                    **{a: "0.000" for a in _AXES},
                    "n_fabrication_flags": 0,
                    "n_degradation_flags": 0,
                    "n_phantom_artifact_flags": 0,
                    "raw_response_chars": 0,
                    "reasoning_snippet": f"{type(e).__name__}: {e}",
                })

    long_csv = args.matrix_dir / "verification_results_long.csv"
    prior = _read_existing_long(long_csv)
    merged = _merge_long_rows(prior, long_rows)
    with long_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_LONG_FIELDS)
        w.writeheader()
        for r in merged:
            w.writerow(r)

    wide_csv = args.matrix_dir / "verification_results.csv"
    _write_wide_verification(merged, wide_csv)

    print(f"\nWrote {long_csv}  ({len(prior)} prior + {len(long_rows)} new → {len(merged)} merged rows)")
    print(f"Wrote {wide_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
