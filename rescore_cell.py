#!/usr/bin/env python3
"""Re-run the bench-side verifier on a single cell post-hoc.

Useful when:
  - The verifier crashed (e.g. missing ANTHROPIC_API_KEY) during the
    original run; the agent's artifacts are intact, just need scoring.
  - You want to re-score with a different verifier_model.
  - You want to update verifier_summary / verifier_evidence.json
    without burning compute on the agent again.

Requires ANTHROPIC_API_KEY in env (litellm reads it directly).

Usage:
  ./rescore_cell.py \\
      --results results/<TS>/<task>/results.csv \\
      --cell-id photonics__cc-bare__sonnet \\
      --task photonics \\
      [--verifier-model anthropic/claude-sonnet-4-6]
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402
from adapters import verifier_invoker  # noqa: E402
from adapters.base import CSV_FIELDS, score_from_verdict  # noqa: E402


def _short(s: str, n: int = 240) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True, type=pathlib.Path)
    p.add_argument("--cell-id", required=True)
    p.add_argument("--task", required=True, help="Task id (matches tasks/<id>.yaml)")
    p.add_argument("--verifier-model", default="anthropic/claude-sonnet-4-6")
    args = p.parse_args(argv)

    # Fail fast on missing API key — we'd otherwise crash after rendering
    # the trajectory (which can take a few seconds for big runs).
    import os
    if args.verifier_model.startswith("anthropic/") and not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY not in env — verifier call will fail.", file=sys.stderr)
        print("  fix: export ANTHROPIC_API_KEY=sk-ant-... in THIS shell, then re-run.", file=sys.stderr)
        return 2
    if args.verifier_model.startswith("openai/") and not os.environ.get("OPENAI_API_KEY"):
        print("error: OPENAI_API_KEY not in env — verifier call will fail.", file=sys.stderr)
        return 2

    task_yaml = REPO_ROOT / "tasks" / f"{args.task}.yaml"
    task_spec = yaml.safe_load(task_yaml.read_text(encoding="utf-8"))

    if not args.results.exists():
        print(f"error: {args.results} not found", file=sys.stderr)
        return 2

    with args.results.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    target = next((r for r in rows if r.get("cell_id") == args.cell_id), None)
    if target is None:
        print(f"error: cell_id '{args.cell_id}' not found in {args.results}", file=sys.stderr)
        return 2

    workdir = pathlib.Path(target.get("artifacts_dir") or "")
    if not workdir.exists():
        print(f"error: artifacts_dir does not exist: {workdir}", file=sys.stderr)
        return 2

    result_text_path = workdir / "result.txt"
    if not result_text_path.exists() or not result_text_path.read_text(encoding="utf-8").strip():
        print(f"error: result.txt is missing or empty at {result_text_path}", file=sys.stderr)
        return 2
    claim_text = result_text_path.read_text(encoding="utf-8")

    # Hand the verifier the same trajectory file the original adapter would
    # have used. For Claude Code cells transcript_path points at the copied
    # claude_transcript.jsonl; for sciagent cells it's the provenance.jsonl.
    log_field = target.get("transcript_path") or target.get("raw_provenance_log") or ""
    session_log = pathlib.Path(log_field) if log_field else None
    if session_log is not None and not session_log.exists():
        session_log = None

    # Render the trajectory inline so the verifier (one-shot litellm call,
    # no file tools) can audit what the agent actually did.
    trajectory_text = None
    if session_log is not None:
        from tools.render_transcript import (
            _read_jsonl,
            render_claude_transcript,
            render_sciagent_provenance,
        )
        events = list(_read_jsonl(session_log))
        if events:
            if "event_kind" in events[0]:
                trajectory_text = render_sciagent_provenance(events)
            else:
                trajectory_text = render_claude_transcript(events)

    print(f"Re-scoring {args.cell_id}")
    print(f"  workdir: {workdir}")
    print(f"  claim_text: {len(claim_text)} chars")
    print(f"  session_log: {session_log or '(none)'}")
    print(f"  trajectory: {len(trajectory_text) if trajectory_text else 0} chars rendered")
    print(f"  verifier_model: {args.verifier_model}")
    print()

    v = verifier_invoker.verify(
        task_prompt=task_spec["prompt"],
        claim_text=claim_text,
        workdir=workdir,
        session_log_path=session_log,
        verifier_model=args.verifier_model,
        verification_criteria=task_spec.get("verification_criteria") or {},
        trajectory_text=trajectory_text,
    )

    verdict = v["verdict"]
    confidence = v["confidence"]
    score = score_from_verdict(verdict, confidence)
    summary = _short(v.get("reasoning") or "")
    print(f"  verdict: {verdict}")
    print(f"  confidence: {confidence:.3f}")
    print(f"  score: {score:.3f}")
    print(f"  reasoning (short): {summary}")
    print()

    (workdir / "verifier_evidence.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    print(f"  wrote {workdir / 'verifier_evidence.json'}")

    # Update the row in-place, clear the previous error.
    target["verdict"] = verdict
    target["confidence"] = f"{confidence:.3f}"
    target["score"] = f"{score:.3f}"
    target["verifier_summary"] = summary
    target["error"] = ""
    target["success"] = "True"

    with args.results.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    print(f"  updated row in {args.results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
