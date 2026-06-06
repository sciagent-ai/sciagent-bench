#!/usr/bin/env python3
"""Render a markdown report from a results.csv emitted by run_matrix.py.

Usage:
  ./build_report.py --results results/<TS>/<task>/results.csv --out report/
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
import sys
from collections import defaultdict

REPO_ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from tools.render_transcript import (  # noqa: E402
    _read_jsonl,
    render_claude_transcript,
    render_sciagent_provenance,
)


def _render_trajectory(transcript: pathlib.Path) -> str:
    """Render a JSONL transcript (Claude Code or sciagent) to markdown.
    Format autodetected: sciagent rows have `event_kind`; Claude Code rows
    have top-level `type`."""
    events = list(_read_jsonl(transcript))
    if not events:
        return ""
    if "event_kind" in events[0]:
        body = render_sciagent_provenance(events)
        header = f"# Sciagent provenance — {transcript.name}\n"
    else:
        body = render_claude_transcript(events)
        header = f"# Claude Code transcript — {transcript.name}\n"
    return header + "\n" + body


def _to_float(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _read_rows(path: pathlib.Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_result_block(artifacts_dir: str) -> str:
    if not artifacts_dir:
        return ""
    p = pathlib.Path(artifacts_dir) / "result.txt"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _config_key(row: dict) -> str:
    """A row's adapter+config bucket for aggregate stats."""
    adapter = row.get("adapter", "")
    cell_id = row.get("cell_id", "")
    # cell_ids follow <task>__<config>__<model> by convention; pull the middle.
    parts = cell_id.split("__")
    if len(parts) >= 2:
        return f"{adapter}/{parts[1]}"
    return adapter


def build_summary(rows: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Matrix results")
    lines.append("")
    if not rows:
        lines.append("_(no rows in results.csv)_")
        return "\n".join(lines)

    lines.append("## Metrics")
    lines.append("")
    header = (
        "| Cell | Verdict | Conf | Score | Tokens in | Tokens out | "
        "LLM $ | Compute $ | Storage $ | Total $ | Wall s | Iter | "
        "Tool calls | Ask user | Notes |"
    )
    sep = "|---" * 15 + "|"
    lines.append(header)
    lines.append(sep)
    for r in rows:
        lines.append(
            "| {cell} | {verdict} | {conf} | {score} | {ti} | {to} "
            "| ${llm} | ${cmp} | ${stg} | ${tot} | {wall} | {it} "
            "| {tc} | {ua} | {notes} |".format(
                cell=r.get("cell_id", ""),
                verdict=r.get("verdict", ""),
                conf=r.get("confidence", ""),
                score=r.get("score", ""),
                ti=r.get("tokens_in", ""),
                to=r.get("tokens_out", ""),
                llm=r.get("cost_llm_usd", ""),
                cmp=r.get("cost_compute_usd", ""),
                stg=r.get("cost_storage_usd", ""),
                tot=r.get("cost_total_usd", ""),
                wall=r.get("wall_seconds", ""),
                it=r.get("iterations", ""),
                tc=r.get("tool_calls", ""),
                ua=r.get("user_asks", ""),
                notes=r.get("notes", ""),
            )
        )
    lines.append("")

    lines.append("## Verbatim Result blocks")
    lines.append("")
    for r in rows:
        cell = r.get("cell_id", "(no id)")
        lines.append(f"### {cell}")
        lines.append("")
        artifacts = r.get("artifacts_dir", "")
        transcript = r.get("transcript_path", "")
        verifier_summary = r.get("verifier_summary", "")

        rendered_path = ""
        if transcript:
            t_path = pathlib.Path(transcript)
            if t_path.exists():
                try:
                    rendered = _render_trajectory(t_path)
                    if rendered:
                        out_path = pathlib.Path(artifacts) / "trajectory.md" if artifacts else t_path.with_suffix(".md")
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_text(rendered, encoding="utf-8")
                        rendered_path = str(out_path)
                except Exception as exc:
                    print(f"  warn: failed to render {t_path}: {exc}", file=sys.stderr)

        if artifacts:
            lines.append(f"- artifacts: [`{artifacts}`]({artifacts})")
        if rendered_path:
            lines.append(f"- trajectory (readable): [`{rendered_path}`]({rendered_path})")
        if transcript:
            lines.append(f"- trajectory (raw JSONL): [`{transcript}`]({transcript})")
        if verifier_summary:
            lines.append(f"- verifier said: {verifier_summary}")
        lines.append("")
        block = _read_result_block(artifacts)
        if block:
            lines.append("```")
            lines.append(block)
            lines.append("```")
        else:
            lines.append("_(no Result block on disk for this cell)_")
        lines.append("")

    # Aggregate footer: mean score / cost per config, and the verifier-on/off delta.
    lines.append("## Aggregate")
    lines.append("")
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_config[_config_key(r)].append(r)
    lines.append("| Config | N | Mean score | Mean total $ |")
    lines.append("|---|---|---|---|")
    config_means: dict[str, dict[str, float]] = {}
    for cfg, items in by_config.items():
        scores = [_to_float(x.get("score", "0")) for x in items]
        costs = [_to_float(x.get("cost_total_usd", "0")) for x in items]
        ms = statistics.fmean(scores) if scores else 0.0
        mc = statistics.fmean(costs) if costs else 0.0
        config_means[cfg] = {"score": ms, "cost": mc}
        lines.append(f"| {cfg} | {len(items)} | {ms:.3f} | ${mc:.4f} |")
    lines.append("")

    on_key = next((k for k in config_means if "sciagent" in k and "verifier-on" in k), None)
    off_key = next((k for k in config_means if "sciagent" in k and "verifier-off" in k), None)
    if on_key and off_key:
        d_score = config_means[on_key]["score"] - config_means[off_key]["score"]
        d_cost = config_means[on_key]["cost"] - config_means[off_key]["cost"]
        lines.append("### Verifier-ON vs verifier-OFF")
        lines.append("")
        lines.append(f"- Δ score (on − off): **{d_score:+.3f}**")
        lines.append(f"- Δ total cost (on − off): **${d_cost:+.4f}**")
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    if not args.results.exists():
        print(f"error: results not found: {args.results}", file=sys.stderr)
        return 2
    rows = _read_rows(args.results)
    args.out.mkdir(parents=True, exist_ok=True)
    summary = build_summary(rows)
    summary_path = args.out / "summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
