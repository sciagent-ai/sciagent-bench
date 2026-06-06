#!/usr/bin/env python3
"""Render a Claude Code session transcript or sciagent provenance.jsonl as
a readable markdown timeline.

Usage:
  ./tools/render_transcript.py <transcript.jsonl> [--out summary.md]
  ./tools/render_transcript.py <transcript.jsonl> --tool-output-chars 800

What you get:
  - user prompts (full)
  - assistant thinking (truncated)
  - assistant text (full)
  - assistant tool calls (name + argument summary)
  - tool results (truncated content + error flag)

What's dropped:
  - UUIDs / promptIds / sessionIds (linking metadata, not content)
  - thinking-block signatures (Anthropic verification hashes — opaque
    on purpose; not human-readable content)
  - queue-operation events (Claude Code internal plumbing)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional


def _read_jsonl(path: pathlib.Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _truncate(text: str, n: int) -> str:
    text = text or ""
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _fmt_args(args, n: int = 240) -> str:
    if isinstance(args, str):
        return _truncate(args, n)
    try:
        s = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(args)
    return _truncate(s, n)


def render_claude_transcript(events: list, tool_output_chars: int = 800,
                             thinking_chars: int = 400) -> str:
    out: list[str] = []
    turn = 0
    for ev in events:
        kind = ev.get("type")
        if kind not in ("user", "assistant"):
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        role = msg.get("role") or kind
        ts = ev.get("timestamp", "")

        if isinstance(content, str):
            turn += 1
            out.append(f"### turn {turn} — **{role}** _{ts}_\n")
            out.append(content.strip())
            out.append("")
            continue

        if not isinstance(content, list):
            continue

        for blk in content:
            if not isinstance(blk, dict):
                continue
            btype = blk.get("type")
            if btype == "text":
                turn += 1
                out.append(f"### turn {turn} — **{role}** (text) _{ts}_\n")
                out.append((blk.get("text") or "").strip())
                out.append("")
            elif btype == "thinking":
                turn += 1
                out.append(f"### turn {turn} — **{role}** (thinking) _{ts}_\n")
                out.append(f"> {_truncate(blk.get('thinking') or '', thinking_chars)}")
                out.append("")
            elif btype == "tool_use":
                turn += 1
                tool = blk.get("name", "?")
                out.append(f"### turn {turn} — **{role}** tool_use → `{tool}` _{ts}_\n")
                out.append("```json")
                out.append(_fmt_args(blk.get("input"), n=800))
                out.append("```")
                out.append("")
            elif btype == "tool_result":
                turn += 1
                is_err = blk.get("is_error")
                marker = " ❌" if is_err else ""
                tc = blk.get("content")
                if isinstance(tc, list):
                    parts = []
                    for c in tc:
                        if isinstance(c, dict):
                            if c.get("type") == "text":
                                parts.append(c.get("text") or "")
                            elif c.get("type") == "image":
                                parts.append("(image)")
                            else:
                                parts.append(json.dumps(c)[:200])
                        else:
                            parts.append(str(c))
                    tc = "\n".join(parts)
                tc = tc if isinstance(tc, str) else json.dumps(tc)
                out.append(f"### turn {turn} — tool_result{marker} _{ts}_\n")
                out.append("```")
                out.append(_truncate(tc.strip(), tool_output_chars))
                out.append("```")
                out.append("")
    return "\n".join(out) + "\n"


def render_sciagent_provenance(events: list, tool_output_chars: int = 800) -> str:
    """Sciagent provenance: tool_call / tool_result / verification_result /
    session_end / compute_cost_observed events. Render each in order."""
    out: list[str] = []
    seq_seen = 0
    for ev in events:
        kind = ev.get("event_kind")
        seq = ev.get("seq", seq_seen + 1)
        seq_seen = seq
        ts = ev.get("ts", "")
        if kind == "tool_call":
            out.append(f"### seq {seq} — tool_call `{ev.get('tool_name')}` _{ts}_\n")
            out.append("```json")
            out.append(_fmt_args(ev.get("arguments"), n=800))
            out.append("```")
            out.append("")
        elif kind == "tool_result":
            ok = "✓" if ev.get("success") else "✗"
            out.append(
                f"### seq {seq} — tool_result {ok} `{ev.get('tool_name')}` "
                f"({ev.get('duration_ms','?')}ms, ${ev.get('cost_usd') or 0:.4f}) _{ts}_\n"
            )
            out.append("```")
            out.append(_truncate((ev.get("output_summary") or "").strip(), tool_output_chars))
            out.append("```")
            out.append("")
        elif kind == "verification_result":
            out.append(
                f"### seq {seq} — verification_result: "
                f"**{ev.get('verdict')}** @ {ev.get('confidence',0):.2f} _{ts}_\n"
            )
            ev_block = ev.get("evidence") or {}
            es = ev_block.get("evidence_summary") or ev.get("reasoning") or ""
            if es:
                out.append("```")
                out.append(_truncate(es.strip(), tool_output_chars * 2))
                out.append("```")
            out.append("")
        elif kind == "compute_cost_observed":
            out.append(
                f"### seq {seq} — compute_cost_observed: "
                f"${ev.get('cost_usd') or 0:.4f} ({ev.get('cost_source','')}) _{ts}_\n"
            )
            out.append("")
        elif kind == "session_end":
            out.append(
                f"### seq {seq} — **session_end**: {ev.get('iterations','?')} iter, "
                f"{ev.get('tokens_in','?')}/{ev.get('tokens_out','?')} tok, "
                f"${ev.get('cost_usd') or 0:.4f}, {ev.get('wall_seconds',0):.1f}s, "
                f"exit={ev.get('exit_reason','?')} _{ts}_\n"
            )
            out.append("")
    return "\n".join(out) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("transcript", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, default=None,
                   help="Write rendered markdown here (default: stdout)")
    p.add_argument("--tool-output-chars", type=int, default=800,
                   help="Truncate each tool_result body to this many chars (default 800)")
    p.add_argument("--thinking-chars", type=int, default=400,
                   help="Truncate each thinking block to this many chars (default 400)")
    args = p.parse_args(argv)

    if not args.transcript.exists():
        print(f"error: {args.transcript} does not exist", file=sys.stderr)
        return 2

    events = list(_read_jsonl(args.transcript))
    if not events:
        print(f"error: no parseable events in {args.transcript}", file=sys.stderr)
        return 2

    # Format detection: claude transcripts have top-level `type` field with
    # values like "user"/"assistant"; sciagent provenance has `event_kind`.
    sample = events[0]
    if "event_kind" in sample:
        rendered = render_sciagent_provenance(events, args.tool_output_chars)
        header = f"# Sciagent provenance — {args.transcript}\n"
    else:
        rendered = render_claude_transcript(events, args.tool_output_chars, args.thinking_chars)
        header = f"# Claude Code transcript — {args.transcript}\n"

    output = header + "\n" + rendered
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
