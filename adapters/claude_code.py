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


def _render_transcript_text(path: Optional[pathlib.Path]) -> Optional[str]:
    """Render a Claude Code transcript JSONL to readable markdown for the
    verifier. Returns None if no transcript exists."""
    if path is None or not path.exists():
        return None
    try:
        import sys as _sys
        _root = pathlib.Path(__file__).resolve().parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from tools.render_transcript import _read_jsonl, render_claude_transcript
        events = list(_read_jsonl(path))
        if not events:
            return None
        return render_claude_transcript(events)
    except Exception:
        return None


REGISTRY_SRC = pathlib.Path(
    "/Users/shrutibadhwar/Documents/2026/testpackage/sciagent-cli/src/sciagent/services/registry.yaml"
)

_CLAUDE_PROJECTS = pathlib.Path.home() / ".claude" / "projects"


def _locate_claude_transcript(cwd: pathlib.Path, session_id: Optional[str]) -> Optional[pathlib.Path]:
    """Claude Code persists per-session transcripts at
    ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl where <encoded-cwd>
    is the cwd with '/' replaced by '-'. Returns the path if it exists.
    """
    if not session_id:
        return None
    encoded = str(cwd.resolve()).replace("/", "-")
    candidate = _CLAUDE_PROJECTS / encoded / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None

_REGISTRY_NOTE = (
    "\n\nA service catalog is available at ./services_registry.yaml. "
    "If your task needs a containerized scientific service, you can launch "
    "one via 'sky launch --image ghcr.io/sciagent-ai/<service-name> ...'."
)


def _write_verifier_evidence(workdir: pathlib.Path, v: dict) -> None:
    """Persist the verifier's full output (verdict + confidence + issues +
    reasoning) next to the cell's result.txt so a reviewer can see what
    the verifier saw without re-running it."""
    (workdir / "verifier_evidence.json").write_text(
        json.dumps(v, indent=2), encoding="utf-8"
    )


def _short_reasoning(reasoning: str, limit: int = 240) -> str:
    """Single-line, CSV-safe snippet of the verifier's reasoning."""
    s = " ".join((reasoning or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _extract_result_block(text: str) -> str:
    """Extract the agent's final claim from claude's stdout.

    Three formats handled:
      1. Plain `--print` text mode: look for a `Result:` sentinel and
         return what follows (legacy).
      2. Stream-json without a `result` event (claude exited mid-stream
         e.g. hit max-turns): walk every line, find the *last* assistant
         text block, return its text. This is what the agent was saying
         when it got cut off, NOT the entire stream.
      3. Neither: empty string. We refuse to dump the whole stdout as
         "claim_text" — that was the bug that sent 3M tokens to the
         verifier and tripped ContextWindowExceededError.
    """
    # Format 1: legacy text-mode `Result:` sentinel.
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

    # Format 2: stream-json without a result event — pick the last
    # assistant text block (the agent's most recent claim) and use that.
    last_assistant_text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                txt = (blk.get("text") or "").strip()
                if txt:
                    last_assistant_text = txt
    return last_assistant_text


def extract_claude_cost_breakdown(transcript_path: Optional[pathlib.Path]) -> list:
    """Per-turn cost breakdown from a Claude Code session transcript.

    The transcript at ~/.claude/projects/<encoded-cwd>/<sid>.jsonl has one
    line per event; assistant message events carry a `usage` dict with
    input_tokens / output_tokens / cache_read_input_tokens /
    cache_creation_input_tokens / service_tier. We emit one row per
    assistant turn (and per tool_use within that turn) so we can see
    which actions cost what.

    Computed cost uses Sonnet 4.6 published pricing per 1M tokens:
      input  $3.00 ; output  $15.00
      cache_read  $0.30 ; cache_create  $3.75

    For other models (Haiku, Opus), the calculator could be extended;
    today we assume Sonnet since that's what every cc-* cell pins.
    """
    PRICING_PER_M = {
        # model_prefix : (input, output, cache_read, cache_create)
        "claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
        "claude-opus-4-7":   (15.00, 75.00, 1.50, 18.75),
        "claude-haiku-4-5":  (1.00,  5.00, 0.10, 1.25),
    }
    def price(model: str, usage: dict) -> float:
        for prefix, (pi, po, pcr, pcc) in PRICING_PER_M.items():
            if prefix in (model or ""):
                return (
                    (usage.get("input_tokens", 0) or 0) * pi / 1e6
                    + (usage.get("output_tokens", 0) or 0) * po / 1e6
                    + (usage.get("cache_read_input_tokens", 0) or 0) * pcr / 1e6
                    + (usage.get("cache_creation_input_tokens", 0) or 0) * pcc / 1e6
                )
        return 0.0

    rows: list = []
    if transcript_path is None or not transcript_path.exists():
        return rows
    turn = 0
    try:
        with transcript_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") != "assistant":
                    continue
                msg = ev.get("message") or {}
                usage = msg.get("usage") or {}
                model = msg.get("model", "")
                ts = ev.get("timestamp", "")
                turn += 1
                # Identify tool_uses in this assistant turn so we can label
                # which tool the cost is attributed to (best-effort: take
                # the first tool_use name; thinking-only turns label as "_thinking").
                tool_label = "_text"
                for blk in (msg.get("content") or []):
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "tool_use":
                        tool_label = blk.get("name", "?")
                        break
                    if bt == "thinking" and tool_label == "_text":
                        tool_label = "_thinking"
                rows.append({
                    "agent": "main",
                    "seq": turn,
                    "tool": tool_label,
                    "ts": ts,
                    "tokens_in": usage.get("input_tokens", 0) or 0,
                    "tokens_out": usage.get("output_tokens", 0) or 0,
                    "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
                    "cache_create": usage.get("cache_creation_input_tokens", 0) or 0,
                    "cost_usd": f"{price(model, usage):.6f}",
                    "cost_kind": "llm",
                    "duration_ms": "",
                    "model": model,
                    "success": "",
                })
    except OSError:
        return rows
    return rows


CC_COST_BREAKDOWN_FIELDS = [
    "agent", "seq", "tool", "ts",
    "tokens_in", "tokens_out", "cache_read", "cache_create",
    "cost_usd", "cost_kind", "duration_ms", "model", "success",
]


def write_claude_cost_breakdown(rows: list, out_path: pathlib.Path) -> None:
    import csv as _csv
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=CC_COST_BREAKDOWN_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CC_COST_BREAKDOWN_FIELDS})


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
    session_id: Optional[str] = None

    stripped = stdout_text.strip()
    # Format 1: single buffered JSON blob (`--output-format json`).
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict) and payload.get("type") == "result":
            cost_usd = payload.get("total_cost_usd") or payload.get("cost_usd")
            usage = payload.get("usage") or {}
            tokens_in = usage.get("input_tokens") or payload.get("input_tokens")
            tokens_out = usage.get("output_tokens") or payload.get("output_tokens")
            num_turns = payload.get("num_turns")
            result_text = payload.get("result")
            session_id = payload.get("session_id")
    except json.JSONDecodeError:
        pass

    # Format 2: line-delimited JSON stream (`--output-format stream-json
    # --verbose`). Each line is one event; the final `result` event
    # carries the same fields as Format 1. Even partial streams (SIGKILL
    # mid-run) yield session_id from any earlier event.
    if cost_usd is None and "\n" in stripped:
        last_result = None
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if session_id is None and ev.get("session_id"):
                session_id = ev["session_id"]
            if ev.get("type") == "result":
                last_result = ev
        if last_result is not None:
            cost_usd = last_result.get("total_cost_usd") or last_result.get("cost_usd")
            usage = last_result.get("usage") or {}
            tokens_in = usage.get("input_tokens") or last_result.get("input_tokens")
            tokens_out = usage.get("output_tokens") or last_result.get("output_tokens")
            num_turns = last_result.get("num_turns")
            result_text = last_result.get("result")
            session_id = last_result.get("session_id") or session_id

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
        "session_id": session_id,
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
                verifier_summary="",
                artifacts_dir=workdir,
                raw_provenance_log=None,
                transcript_path=None,
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
        # Fully autonomous — the cell's per-cell workdir + wall-time cap +
        # subscription-only auth bound the blast radius. Anything more
        # restrictive (acceptEdits + allowedTools) appeared to hang the
        # cell silently in --print mode in our earlier attempt.
        cmd = [
            "claude",
            "--print",
            # stream-json + --verbose: emit one JSON event per line as it
            # happens. The final `result` event carries cost/tokens/result
            # just like the buffered json format. Streaming gives us live
            # progress in stdout.txt and yields usable partial transcripts
            # even when the wall-time cap fires before the agent finishes.
            "--output-format", "stream-json",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", model_id,
        ]
        # Turn budget — Claude Code's --print mode defaults to ~42 turns,
        # which is below what photonics-class reproductions need. Honor
        # the task spec's max_turns if set.
        max_turns = budget.get("max_turns")
        if max_turns:
            cmd += ["--max-turns", str(int(max_turns))]
        cmd.append(prompt)

        # Strip ANTHROPIC_API_KEY from the subprocess env so Claude Code
        # falls back to keychain OAuth (subscription billing) instead of
        # billing the API console. Sciagent cells still see the env var
        # since they call litellm in-process.
        child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        # Wall-time budget — kill the cell at the task spec's budget so
        # one stuck call can't burn the entire smoke allocation.
        wall_budget = float(budget.get("wall_time_seconds", 1800))

        stdout_path = workdir / "stdout.txt"
        t0 = time.monotonic()
        timeout_hit = False
        rc: Optional[int] = None
        with stdout_path.open("w", encoding="utf-8") as out:
            try:
                proc = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    cwd=str(project_dir),
                    text=True,
                    env=child_env,
                    timeout=wall_budget,
                )
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                timeout_hit = True
        wall = time.monotonic() - t0
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")

        summary = parse_claude_session_summary(stdout_text)
        result_text = summary["result_text"] or _extract_result_block(stdout_text)
        (workdir / "result.txt").write_text(
            (result_text or "") + ("\n" if result_text else ""),
            encoding="utf-8",
        )

        # Copy Claude Code's per-session transcript next to the rest of the
        # cell's artifacts so the trajectory is portable + reviewable even if
        # ~/.claude/projects/ is later cleaned.
        transcript_path: Optional[pathlib.Path] = None
        src = _locate_claude_transcript(project_dir, summary.get("session_id"))
        if src is not None:
            transcript_path = workdir / "claude_transcript.jsonl"
            try:
                shutil.copy2(src, transcript_path)
            except OSError:
                transcript_path = src  # fall back to the original path

        # Per-turn cost breakdown from the transcript's assistant message
        # `usage` dicts. Lets the user analyze "what did each tool cost".
        cc_rows = extract_claude_cost_breakdown(transcript_path)
        write_claude_cost_breakdown(cc_rows, workdir / "cost_breakdown.csv")

        if timeout_hit:
            success = False
            error: Optional[str] = f"wall-time budget exceeded ({wall_budget:.0f}s)"
        else:
            success = (rc == 0)
            error = None if success else f"claude exited {rc}"

        verifier_model = self.verifier_model or llm
        verdict = "none"
        confidence = 0.0
        verifier_summary = ""
        if result_text:
            trajectory_text = _render_transcript_text(transcript_path)
            v = verifier_invoker.verify(
                task_prompt=task_spec["prompt"],
                claim_text=result_text,
                workdir=workdir,
                session_log_path=transcript_path,
                verifier_model=verifier_model,
                verification_criteria=task_spec.get("verification_criteria") or {},
                trajectory_text=trajectory_text,
            )
            verdict = v["verdict"]
            confidence = v["confidence"]
            _write_verifier_evidence(workdir, v)
            verifier_summary = _short_reasoning(v.get("reasoning", ""))

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
            verifier_summary=verifier_summary,
            artifacts_dir=workdir,
            raw_provenance_log=None,
            transcript_path=transcript_path,
        )
