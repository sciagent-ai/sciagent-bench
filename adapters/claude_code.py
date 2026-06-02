"""Claude Code adapter — shells to the `claude` CLI in print mode.

Cloud-incapable system (no SkyPilot integration), so cost_compute_usd and
cost_storage_usd are explicitly 0.0 — not None — per DESIGN_BENCH.md §5.5.

Two adapter knobs let us isolate which pieces of sciagent's harness matter:
  - with_sky: assert `sky` is on PATH (so the agent could in principle launch
    a cluster); does not change the prompt
  - with_registry: symlink sciagent-cli's services/registry.yaml into the
    workdir and append a line to the prompt pointing at it
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import time
from typing import Optional

from .base import AdapterBase, CellResult, score_from_verdict
from . import verifier_invoker


REGISTRY_SRC = pathlib.Path(
    "/Users/shrutibadhwar/Documents/2026/testpackage/sciagent-cli/src/sciagent/services/registry.yaml"
)

_REGISTRY_NOTE = (
    "\n\nA service catalog is available at ./services_registry.yaml. "
    "If your task needs a containerized scientific service, you can launch "
    "one via 'sky launch --image ghcr.io/sciagent-ai/<service-name> ...'."
)


def _extract_result_block(text: str) -> str:
    """If the agent's final text contains a 'Result:' block, return what
    follows. Otherwise return the whole text — Claude Code's `--print` mode
    just returns the final assistant message verbatim.
    """
    lines = text.splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        if found:
            out.append(line)
        elif line.strip() == "Result:":
            found = True
    if found:
        return "\n".join(out).strip()
    return text.strip()


def parse_claude_session_summary(stdout_text: str) -> dict:
    """Pull cost/tokens/duration/turns from Claude Code's JSON summary.

    `claude --print --output-format json` emits a single JSON object with
    keys like cost_usd / total_cost_usd, usage.input_tokens /
    usage.output_tokens, num_turns, duration_ms. Older / variant builds
    sometimes print the same fields as a 'Total cost: $X' line in text mode;
    we fall back to that pattern so a text-mode capture isn't useless.
    """
    cost_usd: Optional[float] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    num_turns: Optional[int] = None
    result_text: Optional[str] = None

    stripped = stdout_text.strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            cost_usd = payload.get("total_cost_usd") or payload.get("cost_usd")
            usage = payload.get("usage") or {}
            tokens_in = usage.get("input_tokens") or payload.get("input_tokens")
            tokens_out = usage.get("output_tokens") or payload.get("output_tokens")
            num_turns = payload.get("num_turns")
            result_text = payload.get("result")
    except json.JSONDecodeError:
        pass

    if cost_usd is None:
        m = re.search(r"Total cost:\s*\$?([0-9.]+)", stdout_text)
        if m:
            cost_usd = float(m.group(1))
    if tokens_in is None:
        m = re.search(r"input[_ ]tokens?[:\s]+([0-9]+)", stdout_text, re.IGNORECASE)
        if m:
            tokens_in = int(m.group(1))
    if tokens_out is None:
        m = re.search(r"output[_ ]tokens?[:\s]+([0-9]+)", stdout_text, re.IGNORECASE)
        if m:
            tokens_out = int(m.group(1))
    if num_turns is None:
        m = re.search(r"num[_ ]turns?[:\s]+([0-9]+)", stdout_text, re.IGNORECASE)
        if m:
            num_turns = int(m.group(1))

    return {
        "cost_usd": float(cost_usd) if cost_usd is not None else 0.0,
        "tokens_in": int(tokens_in) if tokens_in is not None else None,
        "tokens_out": int(tokens_out) if tokens_out is not None else None,
        "num_turns": int(num_turns) if num_turns is not None else None,
        "result_text": result_text,
    }


class ClaudeCodeAdapter(AdapterBase):
    def __init__(self, with_sky: bool = False, with_registry: bool = False, verifier_model: Optional[str] = None):
        self.with_sky = with_sky
        self.with_registry = with_registry
        # Same family as the agent by default — set explicitly when running
        # a cross-family verifier study.
        self.verifier_model = verifier_model

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

        if self.with_sky and shutil.which("sky") is None:
            return CellResult(
                success=False,
                error="with_sky=True but 'sky' not on PATH (activate venvtest)",
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
                wall_seconds=0.0,
                notes="",
                artifacts_dir=workdir,
                raw_provenance_log=None,
            )

        prompt = task_spec["prompt"]
        if self.with_registry:
            link = project_dir / "services_registry.yaml"
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(REGISTRY_SRC)
            prompt = prompt + _REGISTRY_NOTE

        # Strip provider prefix — `claude --model` takes the bare model id.
        model_id = llm.split("/", 1)[1] if "/" in llm else llm
        cmd = [
            "claude",
            "--print",
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--model", model_id,
            prompt,
        ]

        stdout_path = workdir / "stdout.txt"
        t0 = time.monotonic()
        with stdout_path.open("w", encoding="utf-8") as out:
            proc = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                cwd=str(project_dir),
                text=True,
            )
        wall = time.monotonic() - t0
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")

        summary = parse_claude_session_summary(stdout_text)
        result_text = summary["result_text"] or _extract_result_block(stdout_text)
        (workdir / "result.txt").write_text(
            (result_text or "") + ("\n" if result_text else ""),
            encoding="utf-8",
        )

        success = (proc.returncode == 0)
        error: Optional[str] = None if success else f"claude exited {proc.returncode}"

        verifier_model = self.verifier_model or llm
        verdict = "none"
        confidence = 0.0
        if result_text:
            v = verifier_invoker.verify(
                task_prompt=task_spec["prompt"],
                claim_text=result_text,
                workdir=workdir,
                session_log_path=None,
                verifier_model=verifier_model,
                verification_criteria=task_spec.get("verification_criteria") or {},
            )
            verdict = v["verdict"]
            confidence = v["confidence"]

        score = score_from_verdict(verdict, confidence)
        cost_llm = summary["cost_usd"]

        return CellResult(
            success=success,
            error=error,
            verdict=verdict,
            confidence=confidence,
            score=score,
            cost_llm_usd=cost_llm,
            cost_compute_usd=0.0,
            cost_storage_usd=0.0,
            cost_total_usd=cost_llm,
            tokens_in=summary["tokens_in"],
            tokens_out=summary["tokens_out"],
            iterations=summary["num_turns"],
            tool_calls=None,
            user_asks=0,
            wall_seconds=wall,
            notes="",
            artifacts_dir=workdir,
            raw_provenance_log=None,
        )
