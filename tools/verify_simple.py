#!/usr/bin/env python3
"""Simple categorical audit of finished cells.

A lighter-weight cousin of `reverify_cells.py`. The honesty prompt asks
for four 0.0–1.0 axes plus verdict + confidence, and the three verifier
models disagree wildly on the same trajectory (sometimes `supported`,
sometimes `partial`, sometimes `refuted`). This driver runs a much
simpler prompt that asks six categorical questions and demands one-line
notes — no scores, no confidence — and additionally attaches the paper
PDF so the verifier can independently check physics + solver match.

Cost / tokens / tools are NOT touched here — `reverify_cells.py
--efficiency-only` still owns that report.

Usage:
  ./tools/verify_simple.py results/<TS>/<task> \\
      --task tasks/photonics.yaml \\
      --verifier-model anthropic/claude-sonnet-4-6 \\
      [--verifier-model anthropic/claude-opus-4-7] ...

Outputs in <matrix_dir>:
  verification_simple.csv        — one row per (cell, verifier)
  verification_simple_summary.md — side-by-side table for the writeup

Outputs per cell:
  verification_simple_<alias>.json     — parsed categorical answers
  verification_simple_raw_<alias>.txt  — exact LLM response
"""
from __future__ import annotations

import argparse
import base64
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

from tools.reverify_cells import (  # noqa: E402
    _list_project_files,
    _model_alias,
    _render_project_data_files,
    _render_trajectory,
)

_MAX_TRAJECTORY_CHARS = 180_000
_SIMPLE_PROMPT = _BENCH / "prompts" / "verification_simple.md"

_DEFAULT_VERIFIERS = ["anthropic/claude-sonnet-4-6"]

# Fixed seed used for OpenAI gpt-5 family models (they reject temperature
# != 1, so we lean on the seed parameter for best-effort determinism).
_OPENAI_SEED = 7

_CATEGORICAL_FIELDS = [
    ("physics", {"correct", "approximated", "degraded"}),
    ("solver_matches_paper", {"yes", "partial", "no"}),
    ("data_fabricated_or_hardcoded", {"no", "partial", "yes"}),
    ("claim_supported_by_work", {"yes", "partial", "no"}),
]

_FREE_TEXT_FIELDS = [
    "final_result",
    "expected_result",
    "physics_notes",
    "solver_notes",
    "fabrication_notes",
    "claim_notes",
    "summary",
]


def _adapter_of(cell_id: str) -> str:
    return "sciagent" if "__sciagent" in cell_id else "claude_code"


# ---------------------------------------------------------------------------
# Paper PDF attachment (Anthropic native, via litellm "document" block)
# ---------------------------------------------------------------------------


def _paper_pdf_path(task_spec: dict) -> Optional[pathlib.Path]:
    """The task spec lists the paper under `inputs: [{path:..., source:...}]`.
    We prefer the source path (the canonical copy on disk) so every cell's
    audit sees the same bytes."""
    inputs = task_spec.get("inputs") or []
    for entry in inputs:
        src = entry.get("source") if isinstance(entry, dict) else None
        if src and pathlib.Path(src).suffix.lower() == ".pdf":
            p = pathlib.Path(src)
            if p.exists():
                return p
    return None


def _encode_pdf(pdf_path: pathlib.Path) -> dict:
    data = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    return {
        "type": "file",
        "file": {
            "file_data": f"data:application/pdf;base64,{data}",
            "filename": pdf_path.name,
        },
    }


# ---------------------------------------------------------------------------
# JSON extraction (same shape as reverify_cells._extract_json)
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


def _norm_categorical(value, allowed: set[str]) -> str:
    if not isinstance(value, str):
        return "?"
    v = value.strip().lower()
    return v if v in allowed else "?"


def _norm_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Build the verifier user message
# ---------------------------------------------------------------------------


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
        f"The paper is attached as a PDF above. Read it before answering.\n\n"
        f"## Original task\n\n{task_prompt}\n\n"
        f"## Verification criteria\n\n```json\n{criteria_block}\n```\n\n"
        f"## Agent's final claim\n\n{claim_text}\n\n"
        f"## Files produced in ./project/\n\n{project_listing}\n\n"
        f"## Data files (contents) — agent's curated final outputs\n\n"
        f"{project_data_files}\n\n"
        f"{trail_block}"
    )


# ---------------------------------------------------------------------------
# One LLM call per (cell, verifier)
# ---------------------------------------------------------------------------


def _audit(
    *,
    verifier_model: str,
    system_prompt: str,
    user_msg: str,
    pdf_attachment: Optional[dict],
) -> tuple[dict, str]:
    user_content: list[dict] = []
    if pdf_attachment is not None:
        user_content.append(pdf_attachment)
    user_content.append({"type": "text", "text": user_msg})

    kwargs: dict = {
        "model": verifier_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 3072,
    }
    if "gpt-5" in verifier_model:
        kwargs["seed"] = _OPENAI_SEED
    elif "claude-opus-4" in verifier_model:
        # Opus 4 reasoning models manage their own sampling; pass neither.
        pass
    else:
        kwargs["temperature"] = 0.0

    response = litellm.completion(**kwargs)
    try:
        raw = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raw = ""

    parsed = _extract_json(raw)
    answers: dict = {}
    for field, allowed in _CATEGORICAL_FIELDS:
        answers[field] = _norm_categorical(parsed.get(field), allowed)
    for field in _FREE_TEXT_FIELDS:
        answers[field] = _norm_text(parsed.get(field))

    return answers, raw


# ---------------------------------------------------------------------------
# Per-cell audit
# ---------------------------------------------------------------------------


def audit_cell(
    cell_dir: pathlib.Path,
    *,
    task_spec: dict,
    verifier_models: list[str],
    pdf_attachment: Optional[dict],
    system_prompt: str,
) -> list[dict]:
    cell_id = cell_dir.name
    adapter = _adapter_of(cell_id)
    rendered, src_path, src_kind = _render_trajectory(cell_dir)
    project_listing, n_files = _list_project_files(cell_dir / "project")
    project_data_files, _ = _render_project_data_files(cell_dir / "project")
    claim_path = cell_dir / "result.txt"
    claim = claim_path.read_text(encoding="utf-8") if claim_path.exists() else ""

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
    (cell_dir / "verification_simple_input.txt").write_text(user_msg, encoding="utf-8")

    rows: list[dict] = []
    for model in verifier_models:
        alias = _model_alias(model)
        try:
            answers, raw = _audit(
                verifier_model=model,
                system_prompt=system_prompt,
                user_msg=user_msg,
                pdf_attachment=pdf_attachment,
            )
        except Exception as e:
            print(f"  !! {alias}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            row = {
                "cell_id": cell_id,
                "adapter": adapter,
                "verifier": alias,
                "verifier_model": model,
                "trajectory_source": src_kind,
                "trajectory_chars": len(rendered) if rendered else 0,
                "n_project_files": n_files,
                "final_result": f"ERROR: {type(e).__name__}: {e}",
                "expected_result": "",
                "physics": "error",
                "physics_notes": "",
                "solver_matches_paper": "error",
                "solver_notes": "",
                "data_fabricated_or_hardcoded": "error",
                "fabrication_notes": "",
                "claim_supported_by_work": "error",
                "claim_notes": "",
                "summary": "",
            }
            rows.append(row)
            continue

        (cell_dir / f"verification_simple_{alias}.json").write_text(
            json.dumps(answers, indent=2), encoding="utf-8"
        )
        (cell_dir / f"verification_simple_raw_{alias}.txt").write_text(raw, encoding="utf-8")

        row = {
            "cell_id": cell_id,
            "adapter": adapter,
            "verifier": alias,
            "verifier_model": model,
            "trajectory_source": src_kind,
            "trajectory_chars": len(rendered) if rendered else 0,
            "n_project_files": n_files,
            **answers,
        }
        rows.append(row)
        print(
            f"  ✓ {alias}: phys={answers['physics']} "
            f"solver={answers['solver_matches_paper']} "
            f"fab={answers['data_fabricated_or_hardcoded']} "
            f"claim={answers['claim_supported_by_work']}",
            flush=True,
        )
    return rows


# ---------------------------------------------------------------------------
# CSV / markdown writers
# ---------------------------------------------------------------------------


_FIELDS = [
    "cell_id", "adapter", "verifier", "verifier_model",
    "trajectory_source", "trajectory_chars", "n_project_files",
    "final_result", "expected_result",
    "physics", "physics_notes",
    "solver_matches_paper", "solver_notes",
    "data_fabricated_or_hardcoded", "fabrication_notes",
    "claim_supported_by_work", "claim_notes",
    "summary",
]


def _write_csv(rows: list[dict], path: pathlib.Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _FIELDS})


def _write_summary_md(rows: list[dict], path: pathlib.Path) -> None:
    """A compact, eyeballable table per (cell, verifier)."""
    lines: list[str] = []
    lines.append("# Simple verification — categorical summary\n")
    lines.append(
        "Cost / tokens / tools are reported separately in "
        "`efficiency_results.csv`. Each row is one verifier's read of one "
        "cell — no scores, no confidence.\n"
    )
    lines.append(
        "| cell | verifier | physics | solver | fabricated? | claim ok? | final → expected |"
    )
    lines.append(
        "|------|----------|---------|--------|-------------|-----------|------------------|"
    )
    for r in rows:
        cell = r["cell_id"].replace("photonics__", "")
        final = r.get("final_result", "") or "—"
        expected = r.get("expected_result", "") or "—"
        # Trim long quotes so the table stays readable.
        if len(final) > 80:
            final = final[:77] + "…"
        if len(expected) > 80:
            expected = expected[:77] + "…"
        lines.append(
            f"| `{cell}` | {r['verifier']} | {r.get('physics','')} | "
            f"{r.get('solver_matches_paper','')} | "
            f"{r.get('data_fabricated_or_hardcoded','')} | "
            f"{r.get('claim_supported_by_work','')} | "
            f"{final} → {expected} |"
        )

    lines.append("\n## One-sentence summaries\n")
    for r in rows:
        cell = r["cell_id"].replace("photonics__", "")
        lines.append(f"- **`{cell}` / {r['verifier']}** — {r.get('summary','')}")
        for note_key in ("physics_notes", "solver_notes",
                         "fabrication_notes", "claim_notes"):
            note = r.get(note_key) or ""
            if note:
                label = note_key.replace("_notes", "").replace("_", " ")
                lines.append(f"  - _{label}_: {note}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("matrix_dir", type=pathlib.Path,
                    help="Path like results/<TS>/photonics")
    ap.add_argument("--task", type=pathlib.Path, required=True,
                    help="tasks/<task>.yaml — pulls prompt, criteria, paper PDF")
    ap.add_argument("--verifier-model", action="append", default=None,
                    help=f"Repeat to add verifiers. Default: {_DEFAULT_VERIFIERS}")
    ap.add_argument("--cell", action="append", default=[],
                    help="Restrict to one or more cell ids")
    ap.add_argument("--no-paper", action="store_true",
                    help="Skip PDF attachment (cheaper; loses solver/physics check fidelity)")
    args = ap.parse_args(argv)

    task_spec = yaml.safe_load(args.task.read_text(encoding="utf-8"))
    verifier_models = args.verifier_model or list(_DEFAULT_VERIFIERS)
    system_prompt = _SIMPLE_PROMPT.read_text(encoding="utf-8")

    pdf_attachment: Optional[dict] = None
    if not args.no_paper:
        pdf_path = _paper_pdf_path(task_spec)
        if pdf_path is None:
            print("(no paper PDF found in task inputs — running without it)",
                  file=sys.stderr)
        else:
            print(f"Attaching paper: {pdf_path}", file=sys.stderr)
            pdf_attachment = _encode_pdf(pdf_path)

    cells = sorted(p for p in args.matrix_dir.iterdir() if p.is_dir())
    if args.cell:
        cells = [c for c in cells if c.name in set(args.cell)]
    if not cells:
        print(f"No cells found under {args.matrix_dir}", file=sys.stderr)
        return 1

    print(f"\nverifiers: {verifier_models}\n", flush=True)
    all_rows: list[dict] = []
    for cell_dir in cells:
        print(f"→ {cell_dir.name}", flush=True)
        all_rows.extend(audit_cell(
            cell_dir,
            task_spec=task_spec,
            verifier_models=verifier_models,
            pdf_attachment=pdf_attachment,
            system_prompt=system_prompt,
        ))

    csv_path = args.matrix_dir / "verification_simple.csv"
    _write_csv(all_rows, csv_path)
    md_path = args.matrix_dir / "verification_simple_summary.md"
    _write_summary_md(all_rows, md_path)

    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
