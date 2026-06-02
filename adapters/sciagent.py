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
import time
from typing import Optional

from .base import AdapterBase, CellResult, score_from_verdict
from . import verifier_invoker


SESSIONS_ROOT = pathlib.Path.home() / ".sciagent" / "sessions"


def _read_yaml(path: pathlib.Path) -> dict:
    """Minimal YAML reader — uses PyYAML if available, falls back to a
    tiny key:value parser for the flat recipes we ship.
    """
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        out: dict = {}
        current: dict = out
        stack = [(0, out)]
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip())
            key, _, val = raw.strip().partition(":")
            while stack and indent < stack[-1][0]:
                stack.pop()
            current = stack[-1][1]
            val = val.strip()
            if val == "":
                new: dict = {}
                current[key] = new
                stack.append((indent + 2, new))
            else:
                current[key] = val
        return out


def _resolve_verifier_model(recipe: dict, fallback: str) -> str:
    orch = recipe.get("orchestrator") or {}
    return orch.get("verifier_model") or recipe.get("agent", {}).get("model") or fallback


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


def parse_provenance(log_path: pathlib.Path) -> dict:
    """Walk a provenance.jsonl and roll up the fields a CellResult needs.

    Returns a dict with: cost_llm_usd, cost_compute_usd, cost_storage_usd,
    tokens_in, tokens_out, iterations, tool_calls, user_asks, wall_seconds,
    verdict, confidence. Verdict/confidence come from the *last*
    verification_result event; if none is present the caller decides whether
    to invoke the bench-side verifier.
    """
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
    saw_tool_result_with_cost = False

    for ev in _iter_events(log_path):
        kind = ev.get("event_kind")
        if kind == "tool_call":
            tool_calls += 1
            if ev.get("tool_name") == "ask_user":
                user_asks += 1
        elif kind == "tool_result":
            ck = ev.get("cost_kind")
            cu = ev.get("cost_usd")
            if cu is not None:
                saw_tool_result_with_cost = True
                if ck == "llm":
                    cost_llm += float(cu)
                elif ck == "compute":
                    cost_compute += float(cu)
                elif ck == "storage":
                    cost_storage += float(cu)
                else:
                    cost_llm += float(cu)
            if ev.get("tokens_in"):
                tokens_in += int(ev["tokens_in"])
            if ev.get("tokens_out"):
                tokens_out += int(ev["tokens_out"])
        elif kind == "compute_cost_observed":
            source = (ev.get("cost_source") or "").lower()
            cu = ev.get("cost_usd")
            if cu is None:
                continue
            if "storage" in source:
                cost_storage += float(cu)
            else:
                cost_compute += float(cu)
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
    }


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
        recipe_yaml = _read_yaml(recipe_path) if recipe_path.exists() else {}

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
                verdict="none",
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
                artifacts_dir=workdir,
                raw_provenance_log=None,
            )

        rollup = parse_provenance(copied_log)
        verdict = rollup["verdict"]
        confidence = rollup["confidence"]

        # Verifier-OFF cells emit no verification_result event — fall back
        # to the bench-side post-hoc verifier so scoring is uniform across
        # the four matrix cells.
        if verdict is None and result_block:
            verifier_model = _resolve_verifier_model(recipe_yaml, llm)
            v = verifier_invoker.verify(
                task_prompt=task_spec["prompt"],
                claim_text=result_block,
                workdir=workdir,
                session_log_path=copied_log,
                verifier_model=verifier_model,
                verification_criteria=task_spec.get("verification_criteria") or {},
            )
            verdict = v["verdict"]
            confidence = v["confidence"]

        verdict = verdict or "none"
        score = score_from_verdict(verdict, confidence)
        cost_total = rollup["cost_llm_usd"] + rollup["cost_compute_usd"] + rollup["cost_storage_usd"]

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
            artifacts_dir=workdir,
            raw_provenance_log=copied_log,
        )
