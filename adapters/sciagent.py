"""Sciagent adapter — shells to the `sciagent run` CLI.

Reads the provenance.jsonl that sciagent emitted under
~/.sciagent/sessions/<sid>/, copies it next to the rest of the cell's
artifacts, and pulls verdict / confidence / token / cost rollups from it.
No `from sciagent.*` imports — the seam is the CLI + the JSONL.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Optional

from .base import AdapterBase, CellResult, score_from_verdict


SESSIONS_ROOT = pathlib.Path.home() / ".sciagent" / "sessions"


def _short_reasoning(reasoning: str, limit: int = 240) -> str:
    """Single-line, CSV-safe snippet of the verifier's reasoning."""
    s = " ".join((reasoning or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _latest_session_log(skip: Optional[pathlib.Path]) -> Optional[pathlib.Path]:
    if not SESSIONS_ROOT.exists():
        return None
    candidates = sorted(
        SESSIONS_ROOT.glob("*/provenance.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for c in candidates:
        if skip and c.resolve() == skip.resolve():
            continue
        return c
    return None


def _iter_events(log_path: pathlib.Path):
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _extract_result_block(stdout_text: str) -> str:
    """Grab everything after the literal line 'Result:' from sciagent stdout."""
    lines = stdout_text.splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if found:
            out.append(line)
        elif line.strip() == "Result:":
            found = True
    return "\n".join(out).strip()


def parse_provenance(
    log_path: pathlib.Path,
    *,
    agent_path: str = "main",
    breakdown: Optional[list] = None,
    visited: Optional[set] = None,
) -> dict:
    """Walk a provenance.jsonl and roll up the fields a CellResult needs.

    Recursively follows subagent_completed → child session logs so subagent
    cost/tokens are correctly counted in the parent's totals. (Sciagent
    writes each subagent's tool_call/tool_result events to its own
    ~/.sciagent/sessions/<child_session_id>/provenance.jsonl, not the
    parent log — without this recursion the bench undercounts subagent
    spend by 5-10x.)

    Set `breakdown` to an output list to also accumulate a per-tool-call
    row model — each row keyed by (agent_path, seq, tool_name) with its
    own token/cost split. Used to write cost_breakdown.csv.

    Returns a dict with: cost_llm_usd, cost_compute_usd, cost_storage_usd,
    tokens_in, tokens_out, iterations, tool_calls, user_asks, wall_seconds,
    verdict, confidence. Verdict/confidence come from the *last*
    verification_result event; if none is present the caller decides whether
    to invoke the bench-side verifier.
    """
    if visited is None:
        visited = set()
    log_path = pathlib.Path(log_path).resolve()
    if log_path in visited:
        # Defend against cycles (shouldn't happen, but safe).
        return _empty_rollup()
    visited.add(log_path)

    cost_llm = 0.0
    cost_compute = 0.0
    cost_storage = 0.0
    tokens_in = 0
    tokens_out = 0
    iterations: Optional[int] = None
    tool_calls = 0
    user_asks = 0
    wall_seconds = 0.0
    session_end_cost: Optional[float] = None
    session_end_tokens_in: Optional[int] = None
    session_end_tokens_out: Optional[int] = None
    verdict: Optional[str] = None
    confidence: float = 0.0
    verifier_reasoning: str = ""
    verifier_issues: list = []
    saw_tool_result_with_cost = False
    # Map subagent spawn_event_id -> subagent_name so we can label the
    # recursive call. (subagent_completed events carry both.)
    spawn_names: dict = {}

    for ev in _iter_events(log_path):
        kind = ev.get("event_kind")
        if kind == "tool_call":
            tool_calls += 1
            if ev.get("tool_name") == "ask_user":
                user_asks += 1
        elif kind == "tool_result":
            ck = ev.get("cost_kind")
            cu = ev.get("cost_usd")
            row_cost = 0.0
            if cu is not None:
                saw_tool_result_with_cost = True
                row_cost = float(cu)
                if ck == "llm":
                    cost_llm += row_cost
                elif ck == "compute":
                    cost_compute += row_cost
                elif ck == "storage":
                    cost_storage += row_cost
                else:
                    cost_llm += row_cost
            row_tin = int(ev.get("tokens_in") or 0)
            row_tout = int(ev.get("tokens_out") or 0)
            tokens_in += row_tin
            tokens_out += row_tout
            if breakdown is not None and (row_cost or row_tin or row_tout):
                breakdown.append({
                    "agent": agent_path,
                    "seq": ev.get("seq"),
                    "tool": ev.get("tool_name", ""),
                    "ts": ev.get("ts", ""),
                    "tokens_in": row_tin,
                    "tokens_out": row_tout,
                    "cost_usd": f"{row_cost:.6f}",
                    "cost_kind": ck or "",
                    "duration_ms": ev.get("duration_ms", ""),
                    "model": ev.get("model", ""),
                    "success": ev.get("success", ""),
                })
        elif kind == "compute_cost_observed":
            source = (ev.get("cost_source") or "").lower()
            cu = ev.get("cost_usd")
            if cu is None:
                continue
            row_cost = float(cu)
            if "storage" in source:
                cost_storage += row_cost
            else:
                cost_compute += row_cost
            if breakdown is not None:
                breakdown.append({
                    "agent": agent_path,
                    "seq": ev.get("seq"),
                    "tool": "compute_cost_observed",
                    "ts": ev.get("ts", ""),
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": f"{row_cost:.6f}",
                    "cost_kind": "storage" if "storage" in source else "compute",
                    "duration_ms": "",
                    "model": "",
                    "success": "",
                })
        elif kind == "subagent_spawned":
            spawn_names[ev.get("event_id")] = ev.get("subagent_name", "?")
        elif kind == "subagent_completed":
            # Recurse into the child session's own log. This is where
            # the subagent's actual cost lives — the parent log only has
            # the summary event with tokens_used.
            child_id = ev.get("child_session_id")
            sub_name = (
                ev.get("subagent_name")
                or spawn_names.get(ev.get("spawn_event_id"))
                or "subagent"
            )
            if child_id:
                child_log = SESSIONS_ROOT / child_id / "provenance.jsonl"
                if child_log.exists():
                    child = parse_provenance(
                        child_log,
                        agent_path=f"{agent_path}/{sub_name}",
                        breakdown=breakdown,
                        visited=visited,
                    )
                    cost_llm += child.get("cost_llm_usd", 0.0)
                    cost_compute += child.get("cost_compute_usd", 0.0)
                    cost_storage += child.get("cost_storage_usd", 0.0)
                    tokens_in += int(child.get("tokens_in") or 0)
                    tokens_out += int(child.get("tokens_out") or 0)
                    tool_calls += int(child.get("tool_calls") or 0)
                    user_asks += int(child.get("user_asks") or 0)
        elif kind == "session_end":
            iterations = ev.get("iterations")
            wall_seconds = float(ev.get("wall_seconds") or 0.0)
            session_end_cost = ev.get("cost_usd")
            session_end_tokens_in = ev.get("tokens_in")
            session_end_tokens_out = ev.get("tokens_out")
        elif kind == "verification_result":
            verdict = ev.get("verdict")
            try:
                confidence = float(ev.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            evidence = ev.get("evidence") or {}
            verifier_reasoning = (
                evidence.get("evidence_summary")
                or ev.get("reasoning")
                or ""
            )
            verifier_issues = list(ev.get("issues") or [])

    if not saw_tool_result_with_cost and session_end_cost is not None:
        cost_llm = float(session_end_cost)
    if tokens_in == 0 and session_end_tokens_in:
        tokens_in = int(session_end_tokens_in)
    if tokens_out == 0 and session_end_tokens_out:
        tokens_out = int(session_end_tokens_out)

    return {
        "cost_llm_usd": cost_llm,
        "cost_compute_usd": cost_compute,
        "cost_storage_usd": cost_storage,
        "tokens_in": tokens_in if tokens_in else None,
        "tokens_out": tokens_out if tokens_out else None,
        "iterations": iterations,
        "tool_calls": tool_calls,
        "user_asks": user_asks,
        "wall_seconds": wall_seconds,
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": verifier_reasoning,
        "issues": verifier_issues,
    }


def _empty_rollup() -> dict:
    return {
        "cost_llm_usd": 0.0, "cost_compute_usd": 0.0, "cost_storage_usd": 0.0,
        "tokens_in": None, "tokens_out": None, "iterations": None,
        "tool_calls": 0, "user_asks": 0, "wall_seconds": 0.0,
        "verdict": None, "confidence": 0.0, "reasoning": "", "issues": [],
    }


COST_BREAKDOWN_FIELDS = [
    "agent", "seq", "tool", "ts",
    "tokens_in", "tokens_out", "cost_usd", "cost_kind",
    "duration_ms", "model", "success",
]


def write_cost_breakdown(rows: list, out_path: pathlib.Path) -> None:
    """Persist a per-tool-call cost breakdown next to the cell artifacts."""
    import csv
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COST_BREAKDOWN_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COST_BREAKDOWN_FIELDS})


class SciagentAdapter(AdapterBase):
    def __init__(self, recipe: str):
        self.recipe = recipe

    def run(
        self,
        task_spec: dict,
        llm: str,
        workdir: pathlib.Path,
        budget: dict,
    ) -> CellResult:
        workdir = pathlib.Path(workdir)
        project_dir = workdir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Recipe path may be relative to the bench repo root or absolute.
        recipe_path = pathlib.Path(self.recipe)
        if not recipe_path.is_absolute():
            bench_root = pathlib.Path(__file__).resolve().parent.parent
            recipe_path = (bench_root / recipe_path).resolve()

        prev_log = _latest_session_log(skip=None)
        cmd = [
            "sciagent", "run",
            "--config", str(recipe_path),
            "--project-dir", str(project_dir),
            "--set", f"orchestrator.max_wall_seconds={budget.get('wall_time_seconds', 1800)}",
            "--set", f"orchestrator.max_cost_usd={budget.get('cost_usd', 2.0)}",
            task_spec["prompt"],
        ]

        t0 = time.monotonic()
        stdout_path = workdir / "stdout.txt"

        # Wrap with macOS `script` so output is BOTH captured to file AND
        # echoed to the terminal — needed because sciagent uses
        # prompt_toolkit's pt_prompt for ask_user / _pause_for_user (DATA
        # gate), which reads from /dev/tty. Without seeing the question
        # text on the terminal, the user would be answering blind.
        # `script` creates a pty for the child, the user sees output
        # normally, and the typescript is written to stdout_path.
        if sys.stdout.isatty() and shutil.which("script"):
            wrapped = ["script", "-q", str(stdout_path), *cmd]
            proc = subprocess.run(wrapped, text=True)
        else:
            # Non-interactive (e.g. running under tmux-detached or piped):
            # capture only, no terminal echo. ask_user will hang in this
            # mode — caller's responsibility to know.
            with stdout_path.open("w", encoding="utf-8") as out:
                proc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, text=True)
        wall = time.monotonic() - t0
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")

        result_block = _extract_result_block(stdout_text)
        (workdir / "result.txt").write_text(result_block + ("\n" if result_block else ""), encoding="utf-8")

        new_log = _latest_session_log(skip=prev_log)
        copied_log: Optional[pathlib.Path] = None
        if new_log is not None and (prev_log is None or new_log.resolve() != prev_log.resolve()):
            copied_log = workdir / "provenance.jsonl"
            shutil.copy2(new_log, copied_log)

        success = (proc.returncode == 0)
        error: Optional[str] = None if success else f"sciagent exited {proc.returncode}"

        if copied_log is None:
            return CellResult(
                success=False,
                error=error or "no provenance log emitted",
                verdict="",
                confidence=0.0,
                score=0.0,
                cost_llm_usd=0.0,
                cost_compute_usd=0.0,
                cost_storage_usd=0.0,
                cost_total_usd=0.0,
                tokens_in=None,
                tokens_out=None,
                iterations=None,
                tool_calls=None,
                user_asks=0,
                wall_seconds=wall,
                notes="",
                verifier_summary="",
                artifacts_dir=workdir,
                raw_provenance_log=None,
                transcript_path=None,
            )

        # Per-tool-call cost breakdown; parse_provenance fills it in-place
        # while it walks parent + recursive subagent logs.
        breakdown_rows: list = []
        rollup = parse_provenance(copied_log, breakdown=breakdown_rows)
        write_cost_breakdown(breakdown_rows, workdir / "cost_breakdown.csv")
        # Verdict/confidence come only from verification_result events the
        # CLI verifier emitted into provenance; the bench never invokes its
        # own verifier. Verifier-OFF cells leave these fields empty.
        verdict = rollup["verdict"] or ""
        confidence = rollup["confidence"]
        verifier_reasoning = rollup.get("reasoning") or ""
        score = score_from_verdict(verdict, confidence) if verdict else 0.0
        cost_total = rollup["cost_llm_usd"] + rollup["cost_compute_usd"] + rollup["cost_storage_usd"]
        verifier_summary = _short_reasoning(verifier_reasoning)

        return CellResult(
            success=success,
            error=error,
            verdict=verdict,
            confidence=confidence,
            score=score,
            cost_llm_usd=rollup["cost_llm_usd"],
            cost_compute_usd=rollup["cost_compute_usd"],
            cost_storage_usd=rollup["cost_storage_usd"],
            cost_total_usd=cost_total,
            tokens_in=rollup["tokens_in"],
            tokens_out=rollup["tokens_out"],
            iterations=rollup["iterations"],
            tool_calls=rollup["tool_calls"],
            user_asks=rollup["user_asks"],
            wall_seconds=rollup["wall_seconds"] or wall,
            notes="",
            verifier_summary=verifier_summary,
            artifacts_dir=workdir,
            raw_provenance_log=copied_log,
            transcript_path=copied_log,
        )
