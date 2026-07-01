"""Detailed performance / cost breakdown for two photonics runs:
  - cc-bare           (Claude Code, no SciAgent layer) — parses stdout.txt (JSONL)
  - sciagent-verifier-on (SciAgent CLI with verifier gate) — parses provenance.jsonl

Accounting model matches sciagent-bench/adapters/sciagent.py::parse_provenance —
the parent session's provenance.jsonl is the entry point, and we recurse
into ~/.sciagent/sessions/<child_session_id>/provenance.jsonl for every
subagent_completed event so subagent LLM cost / tokens / tool calls are
counted in the parent's totals. Without that recursion the bench
under-counts subagent spend by ~5x.

Compute cost: sciagent-cli/run_cost.py::RunCostTracker.poll_active_clusters
emits compute_cost_observed events into provenance when sky.cost_report()
returns a row. For this run no such event was emitted (the cluster
manifest entry was never written), so we go straight to the authoritative
source — sky.cost_report() — and look up the cluster by name. That's the
same number the tracker would have written.

Outputs (written next to this script):
  - cc_bare_per_turn.csv             per-assistant-message LLM accounting
  - cc_bare_tools.csv                tool-use histogram
  - cc_bare_model_usage.csv          per-model token / cost split
  - sciagent_per_event.csv           per tool_result LLM accounting (every session)
  - sciagent_tools.csv               tool-call histogram (every session, summed)
  - sciagent_compute_jobs.csv        per compute_job_launched event
  - sciagent_subagents.csv           per subagent_completed summary
  - sciagent_sky_clusters.csv        per-cluster compute cost from sky.cost_report
  - run_summary.csv                  one-row-per-run side-by-side summary
  - run_summary.json                 same data, structured
  - SUMMARY.md                       human-readable comparison report
"""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Only global constant. Everything else is passed in via argparse — one
# analyzer instance corresponds to one (cc, sci) cell pair, and writes
# its outputs under an explicit out_dir.
SESSIONS_ROOT = Path.home() / ".sciagent" / "sessions"


def _read_jsonl(path):
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# --------------------------------------------------------------------------- #
# cc-bare: parse Anthropic-style stdout JSONL                                 #
# --------------------------------------------------------------------------- #

def analyze_cc_bare(run_dir: Path):
    stdout = run_dir / "stdout.txt"
    init = None
    result = None
    rate_limit_events = []
    assistant_rows = []
    tool_uses = Counter()
    tool_results_count = 0
    parents_seen = Counter()  # parent_tool_use_id → child msgs (sub-agent indicator)
    text_blocks = 0
    thinking_blocks = 0

    for evt in _read_jsonl(stdout):
        t = evt.get("type")
        if t == "system" and evt.get("subtype") == "init":
            init = evt
        elif t == "rate_limit_event":
            rate_limit_events.append(evt)
        elif t == "result":
            result = evt
        elif t == "assistant":
            msg = evt.get("message", {}) or {}
            usage = msg.get("usage", {}) or {}
            content = msg.get("content", []) or []
            tools_in_msg = []
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "tool_use":
                    tool_uses[c.get("name", "?")] += 1
                    tools_in_msg.append(c.get("name", "?"))
                elif ctype == "text":
                    text_blocks += 1
                elif ctype == "thinking":
                    thinking_blocks += 1
            ptu = evt.get("parent_tool_use_id")
            if ptu:
                parents_seen[ptu] += 1
            cache_creation = usage.get("cache_creation", {}) or {}
            assistant_rows.append(
                {
                    "uuid": evt.get("uuid"),
                    "parent_tool_use_id": ptu or "",
                    "model": msg.get("model", ""),
                    "stop_reason": msg.get("stop_reason", ""),
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_creation_input_tokens": usage.get(
                        "cache_creation_input_tokens", 0
                    ),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                    "ephemeral_5m_input_tokens": cache_creation.get(
                        "ephemeral_5m_input_tokens", 0
                    ),
                    "ephemeral_1h_input_tokens": cache_creation.get(
                        "ephemeral_1h_input_tokens", 0
                    ),
                    "tools_in_message": ";".join(tools_in_msg),
                }
            )
        elif t == "user":
            msg = evt.get("message", {}) or {}
            for c in msg.get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    tool_results_count += 1

    if not result:
        raise RuntimeError("cc-bare: no result message in stdout")

    usage = result.get("usage", {}) or {}
    model_usage = result.get("modelUsage", {}) or {}
    return {
        "label": "cc-bare",
        "model_init": (init or {}).get("model"),
        "session_id": result.get("session_id"),
        "permission_mode": (init or {}).get("permissionMode"),
        "claude_code_version": (init or {}).get("claude_code_version"),
        "agents_available": (init or {}).get("agents", []),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "stop_reason": result.get("stop_reason"),
        "terminal_reason": result.get("terminal_reason"),
        "is_error": result.get("is_error"),
        "rate_limit_events": len(rate_limit_events),
        "total_cost_usd": result.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "ephemeral_5m_input_tokens": (usage.get("cache_creation") or {}).get(
            "ephemeral_5m_input_tokens", 0
        ),
        "ephemeral_1h_input_tokens": (usage.get("cache_creation") or {}).get(
            "ephemeral_1h_input_tokens", 0
        ),
        "service_tier": usage.get("service_tier"),
        "model_usage": model_usage,
        "tool_uses": dict(tool_uses),
        "tool_results_count": tool_results_count,
        "assistant_messages": len(assistant_rows),
        "text_blocks": text_blocks,
        "thinking_blocks": thinking_blocks,
        "sub_agent_messages": sum(parents_seen.values()),
        "sub_agent_parents": len(parents_seen),
        "_rows": assistant_rows,
    }


# --------------------------------------------------------------------------- #
# sciagent: parse provenance.jsonl                                            #
# --------------------------------------------------------------------------- #

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _parse_ts(ts):
    if not ts or not ISO_RE.match(ts):
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _walk_session(
    log_path: Path,
    agent_path: str,
    visited: set,
    tool_call_rows: list,
    tool_result_rows: list,
    tool_calls: Counter,
    cost_kinds: Counter,
    models: Counter,
    actors: Counter,
    compute_jobs: list,
    cluster_downs: list,
    subagents: list,
    subagent_obs: list,
    produces_passed: list,
    verification: list,
    session_ends: dict,
    bounds: list,
):
    """Recursive walker matching adapters/sciagent.py::parse_provenance.

    Reads ``log_path``, then recurses into ``~/.sciagent/sessions/<child>/
    provenance.jsonl`` for every ``subagent_completed`` event. Mutates the
    passed-in collectors so the caller can build per-session and aggregate
    views from one pass.
    """
    log_path = log_path.resolve()
    if log_path in visited or not log_path.exists():
        return
    visited.add(log_path)
    spawn_names: dict = {}
    for e in _read_jsonl(log_path):
        ts = _parse_ts(e.get("ts"))
        if ts:
            if not bounds:
                bounds.extend([ts, ts])
            else:
                if ts < bounds[0]:
                    bounds[0] = ts
                if ts > bounds[1]:
                    bounds[1] = ts
        actors[e.get("actor", "?")] += 1
        kind = e.get("event_kind")
        if kind == "tool_call":
            tn = e.get("tool_name", "?")
            tool_calls[tn] += 1
            tool_call_rows.append(
                {
                    "agent_path": agent_path,
                    "seq": e.get("seq"),
                    "ts": e.get("ts"),
                    "tool_name": tn,
                    "actor": e.get("actor"),
                    "tool_call_id": e.get("tool_call_id"),
                }
            )
        elif kind == "tool_result":
            cost_kinds[e.get("cost_kind", "?")] += 1
            models[e.get("model", "?")] += 1
            tool_result_rows.append(
                {
                    "agent_path": agent_path,
                    "seq": e.get("seq"),
                    "ts": e.get("ts"),
                    "tool_name": e.get("tool_name"),
                    "model": e.get("model"),
                    "cost_kind": e.get("cost_kind"),
                    "cost_usd": float(e.get("cost_usd") or 0),
                    "tokens_in": int(e.get("tokens_in") or 0),
                    "tokens_out": int(e.get("tokens_out") or 0),
                    "duration_ms": e.get("duration_ms") or 0,
                    "success": e.get("success"),
                }
            )
        elif kind == "compute_job_launched":
            compute_jobs.append({"agent_path": agent_path, **e})
        elif kind == "compute_cluster_down":
            cluster_downs.append(e)
        elif kind == "subagent_spawned":
            spawn_names[e.get("event_id")] = e.get("subagent_name", "?")
            subagents.append({"agent_path": agent_path, "event_kind": kind, **e})
        elif kind == "subagent_completed":
            subagents.append({"agent_path": agent_path, "event_kind": kind, **e})
            child_id = e.get("child_session_id")
            sub_name = (
                e.get("subagent_name")
                or spawn_names.get(e.get("spawn_event_id"))
                or "subagent"
            )
            if child_id:
                child_log = SESSIONS_ROOT / child_id / "provenance.jsonl"
                _walk_session(
                    child_log,
                    f"{agent_path}/{sub_name}",
                    visited,
                    tool_call_rows,
                    tool_result_rows,
                    tool_calls,
                    cost_kinds,
                    models,
                    actors,
                    compute_jobs,
                    cluster_downs,
                    subagents,
                    subagent_obs,
                    produces_passed,
                    verification,
                    session_ends,
                    bounds,
                )
        elif kind == "subagent_observation":
            subagent_obs.append(e)
        elif kind == "produces_validation_passed":
            produces_passed.append(e)
        elif kind == "verification_result":
            verification.append(e)
        elif kind == "session_end":
            session_ends[agent_path] = e


def _sky_cluster_cost(cluster_name: str) -> dict:
    """Look up authoritative cluster cost from sky.cost_report.

    Returns a dict with the row sciagent-cli/run_cost.py would have ingested
    via ``RunCostTracker.poll_active_clusters``. Returns an empty dict if
    sky isn't installed, the daemon isn't reachable, or the cluster isn't
    in the report.
    """
    try:
        import sky  # type: ignore
        req = sky.cost_report()
        rows = sky.stream_and_get(req)
    except Exception as exc:
        return {"error": str(exc)}
    for r in rows:
        if isinstance(r, dict) and r.get("name") == cluster_name:
            return {
                "name": r.get("name"),
                "cloud": r.get("cloud"),
                "region": r.get("region"),
                "resources_str": r.get("resources_str"),
                "instance_type": (
                    r.get("resources").instance_type
                    if hasattr(r.get("resources"), "instance_type")
                    else None
                ),
                "cpus": r.get("cpus"),
                "memory_gb": r.get("memory"),
                "duration_s": r.get("duration"),
                "num_nodes": r.get("num_nodes"),
                "launched_at": r.get("launched_at"),
                "usage_intervals": r.get("usage_intervals"),
                "total_cost_usd": float(r.get("total_cost") or 0.0),
            }
    return {}


def analyze_sciagent(run_dir: Path):
    parent_log = run_dir / "provenance.jsonl"

    tool_call_rows: list = []
    tool_result_rows: list = []
    tool_calls: Counter = Counter()
    cost_kinds: Counter = Counter()
    models: Counter = Counter()
    actors: Counter = Counter()
    compute_jobs: list = []
    cluster_downs: list = []
    subagents: list = []
    subagent_obs: list = []
    produces_passed: list = []
    verification: list = []
    session_ends: dict = {}
    bounds: list = []

    _walk_session(
        parent_log, "root", set(),
        tool_call_rows, tool_result_rows, tool_calls,
        cost_kinds, models, actors, compute_jobs, cluster_downs,
        subagents, subagent_obs, produces_passed, verification,
        session_ends, bounds,
    )

    parent_session_end = session_ends.get("root")
    first_ts, last_ts = (bounds[0], bounds[1]) if bounds else (None, None)
    wall = parent_session_end.get("wall_seconds") if parent_session_end else None
    if wall is None and first_ts and last_ts:
        wall = (last_ts - first_ts).total_seconds()

    # Per-session rollups
    per_session = defaultdict(
        lambda: {"cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "tool_calls": 0}
    )
    for r in tool_result_rows:
        s = per_session[r["agent_path"]]
        s["cost_usd"] += r["cost_usd"]
        s["tokens_in"] += r["tokens_in"]
        s["tokens_out"] += r["tokens_out"]
    for r in tool_call_rows:
        per_session[r["agent_path"]]["tool_calls"] += 1
    for path, end in session_ends.items():
        s = per_session[path]
        s["iterations"] = end.get("iterations")
        s["wall_seconds"] = end.get("wall_seconds")
        s["session_end_cost_usd"] = end.get("cost_usd")

    # Aggregate LLM totals across parent + all children
    total_llm_cost = sum(r["cost_usd"] for r in tool_result_rows)
    total_tokens_in = sum(r["tokens_in"] for r in tool_result_rows)
    total_tokens_out = sum(r["tokens_out"] for r in tool_result_rows)
    total_iterations = sum(
        (e.get("iterations") or 0) for e in session_ends.values()
    )

    # Compute cost (sky.cost_report → same value RunCostTracker writes).
    # Cluster name discovered from the first compute_job_launched event; for
    # tasks that ran nothing on the cluster (all-local CPU work), sky_row
    # stays empty and downstream reports flag "no cluster used".
    cluster_name = next(
        (j.get("cluster_name") for j in compute_jobs if j.get("cluster_name")),
        None,
    )
    sky_row = _sky_cluster_cost(cluster_name) if cluster_name else {}
    compute_cost = float(sky_row.get("total_cost_usd") or 0.0)

    # Subagent rollups (one row per subagent_completed event)
    subagent_rollups = []
    for s in subagents:
        if s.get("event_kind") == "subagent_completed":
            subagent_rollups.append(
                {
                    "agent_path": s.get("agent_path"),
                    "name": s.get("subagent_name"),
                    "success": s.get("success"),
                    "iterations": s.get("iterations"),
                    "tokens_used": s.get("tokens_used"),
                    "duration_seconds": s.get("duration_seconds"),
                    "child_session_id": s.get("child_session_id"),
                }
            )

    compute_rows = []
    for j in compute_jobs:
        compute_rows.append(
            {
                "agent_path": j.get("agent_path"),
                "seq": j.get("seq"),
                "ts": j.get("ts"),
                "mode": j.get("mode"),
                "cluster_name": j.get("cluster_name"),
                "managed_job_id": j.get("managed_job_id"),
                "service": j.get("service"),
                "image": j.get("image"),
                "cpus": (j.get("requirements") or {}).get("cpus"),
                "memory_gb": (j.get("requirements") or {}).get("memory_gb"),
                "gpus": (j.get("requirements") or {}).get("gpus"),
                "timeout_sec": (j.get("requirements") or {}).get("timeout_sec"),
            }
        )

    parent_session_id = None
    for e in _read_jsonl(parent_log):
        parent_session_id = e.get("session_id")
        if parent_session_id:
            break

    return {
        "label": "sciagent-verifier-on",
        "parent_session_id": parent_session_id,
        "model_main": parent_session_end.get("model") if parent_session_end else None,
        "models_in_tool_results": dict(models),
        "first_ts": first_ts.isoformat() if first_ts else None,
        "last_ts": last_ts.isoformat() if last_ts else None,
        "wall_seconds": wall,
        "parent_session_end": parent_session_end,
        "session_ends": session_ends,
        "per_session_rollup": dict(per_session),
        "total_llm_cost_usd": total_llm_cost,
        "compute_cost_usd": compute_cost,
        "sky_cluster_row": sky_row,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_iterations": total_iterations,
        "parent_iterations": parent_session_end.get("iterations") if parent_session_end else None,
        "parent_tokens_in": parent_session_end.get("tokens_in") if parent_session_end else None,
        "parent_tokens_out": parent_session_end.get("tokens_out") if parent_session_end else None,
        "parent_cost_usd": parent_session_end.get("cost_usd") if parent_session_end else None,
        "exit_reason": parent_session_end.get("exit_reason") if parent_session_end else None,
        "tool_calls": dict(tool_calls),
        "cost_kinds": dict(cost_kinds),
        "actors": dict(actors),
        "compute_jobs": compute_rows,
        "n_compute_jobs": len(compute_rows),
        "n_cluster_downs": len(cluster_downs),
        "subagent_rollups": subagent_rollups,
        "subagent_observations": len(subagent_obs),
        "produces_validations_passed": len(produces_passed),
        "_tool_call_rows": tool_call_rows,
        "_tool_result_rows": tool_result_rows,
    }


# --------------------------------------------------------------------------- #
# Writers                                                                     #
# --------------------------------------------------------------------------- #


def write_csv(path, rows, fieldnames=None):
    if not rows:
        path.write_text("")
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_outputs(cc, sci, out_dir: Path, cc_dir: Path, sci_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    OUT = out_dir
    # Per-message cc-bare
    write_csv(OUT / "cc_bare_per_turn.csv", cc["_rows"])
    # Tools
    write_csv(
        OUT / "cc_bare_tools.csv",
        [{"tool": k, "calls": v} for k, v in sorted(cc["tool_uses"].items(), key=lambda x: -x[1])],
    )
    # Sciagent per-event tool results
    write_csv(OUT / "sciagent_per_event.csv", sci["_tool_result_rows"])
    write_csv(
        OUT / "sciagent_tools.csv",
        [{"tool": k, "calls": v} for k, v in sorted(sci["tool_calls"].items(), key=lambda x: -x[1])],
    )
    write_csv(OUT / "sciagent_compute_jobs.csv", sci["compute_jobs"])
    write_csv(OUT / "sciagent_subagents.csv", sci["subagent_rollups"])
    # Per-session rollup (one row per parent / subagent)
    per_session_rows = []
    for path, r in sci["per_session_rollup"].items():
        per_session_rows.append(
            {
                "session_path": path,
                "iterations": r.get("iterations"),
                "wall_seconds": r.get("wall_seconds"),
                "tool_calls": r.get("tool_calls"),
                "tokens_in": r.get("tokens_in"),
                "tokens_out": r.get("tokens_out"),
                "llm_cost_usd": round(r.get("cost_usd", 0.0), 6),
                "session_end_cost_usd": r.get("session_end_cost_usd"),
            }
        )
    write_csv(OUT / "sciagent_per_session.csv", per_session_rows)
    # Compute cost from sky.cost_report
    if sci["sky_cluster_row"]:
        write_csv(
            OUT / "sciagent_sky_clusters.csv",
            [
                {
                    k: v
                    for k, v in sci["sky_cluster_row"].items()
                    if k != "usage_intervals"
                }
            ],
        )

    # ----------------- Side-by-side summary ----------------- #

    cc_model_main = cc["model_init"]
    sub_models = sorted(
        {
            m
            for m in cc["model_usage"].keys()
            if m != cc_model_main and cc["model_usage"][m].get("inputTokens", 0)
            + cc["model_usage"][m].get("outputTokens", 0) > 0
        }
    )

    sci_subagent_names = sorted({s.get("name") for s in sci["subagent_rollups"] if s.get("name")})

    cc_total_in = cc["input_tokens"] + cc["cache_creation_input_tokens"] + cc["cache_read_input_tokens"]
    sci_subagent_tokens = sum((s.get("tokens_used") or 0) for s in sci["subagent_rollups"])
    sci_subagent_iters = sum((s.get("iterations") or 0) for s in sci["subagent_rollups"])
    sci_total_tokens = (sci["total_tokens_in"] or 0) + (sci["total_tokens_out"] or 0)

    summary_rows = [
        {
            "run": cc["label"],
            "session_id": cc["session_id"],
            "main_model": cc_model_main,
            "subagent_models": ",".join(sub_models) if sub_models else "",
            "iterations_or_turns": cc["num_turns"],
            "wall_seconds": round(cc["duration_ms"] / 1000, 1),
            "api_seconds": round(cc["duration_api_ms"] / 1000, 1),
            "input_tokens_uncached": cc["input_tokens"],
            "output_tokens": cc["output_tokens"],
            "cache_creation_input_tokens": cc["cache_creation_input_tokens"],
            "cache_read_input_tokens": cc["cache_read_input_tokens"],
            "ephemeral_1h_input_tokens": cc["ephemeral_1h_input_tokens"],
            "ephemeral_5m_input_tokens": cc["ephemeral_5m_input_tokens"],
            "total_input_side_tokens": cc_total_in,
            "tool_calls_total": sum(cc["tool_uses"].values()),
            "tool_results_total": cc["tool_results_count"],
            "assistant_messages": cc["assistant_messages"],
            "text_blocks": cc["text_blocks"],
            "thinking_blocks": cc["thinking_blocks"],
            "rate_limit_events": cc["rate_limit_events"],
            "sub_agent_messages": cc["sub_agent_messages"],
            "compute_jobs": 0,
            "subagent_total_iterations": 0,
            "subagent_total_tokens": 0,
            "llm_cost_usd": round(cc["total_cost_usd"], 6),
            "compute_cost_usd": "n/a",
            "stop_reason": cc["stop_reason"],
            "terminal_reason": cc["terminal_reason"],
        },
        {
            "run": sci["label"],
            "session_id": sci["parent_session_id"],
            "main_model": sci["model_main"],
            "subagent_models": ",".join(sci_subagent_names),
            "iterations_or_turns": sci["total_iterations"],
            "wall_seconds": round(sci["wall_seconds"], 1) if sci["wall_seconds"] else None,
            "api_seconds": "n/a",
            "input_tokens_uncached": sci["total_tokens_in"],
            "output_tokens": sci["total_tokens_out"],
            "cache_creation_input_tokens": "n/a",
            "cache_read_input_tokens": "n/a",
            "ephemeral_1h_input_tokens": "n/a",
            "ephemeral_5m_input_tokens": "n/a",
            "total_input_side_tokens": sci["total_tokens_in"],
            "tool_calls_total": sum(sci["tool_calls"].values()),
            "tool_results_total": len(sci["_tool_result_rows"]),
            "assistant_messages": "n/a",
            "text_blocks": "n/a",
            "thinking_blocks": "n/a",
            "rate_limit_events": "n/a",
            "sub_agent_messages": "n/a",
            "compute_jobs": sci["n_compute_jobs"],
            "subagent_total_iterations": sci_subagent_iters,
            "subagent_total_tokens": sci_subagent_tokens,
            "llm_cost_usd": round(sci["total_llm_cost_usd"], 6),
            "compute_cost_usd": round(sci["compute_cost_usd"], 6),
            "stop_reason": sci["exit_reason"],
            "terminal_reason": sci["exit_reason"],
        },
    ]

    write_csv(OUT / "run_summary.csv", summary_rows)

    # Per-model token / cost detail (cc-bare only — sciagent doesn't expose this split)
    write_csv(
        OUT / "cc_bare_model_usage.csv",
        [
            {
                "model": m,
                "input_tokens": v.get("inputTokens", 0),
                "output_tokens": v.get("outputTokens", 0),
                "cache_creation_input_tokens": v.get("cacheCreationInputTokens", 0),
                "cache_read_input_tokens": v.get("cacheReadInputTokens", 0),
                "web_search_requests": v.get("webSearchRequests", 0),
                "cost_usd": v.get("costUSD", 0),
                "context_window": v.get("contextWindow"),
                "max_output_tokens": v.get("maxOutputTokens"),
            }
            for m, v in cc["model_usage"].items()
        ],
    )

    # ----------------- JSON dump ----------------- #
    structured = {
        "cc_bare": {k: v for k, v in cc.items() if not k.startswith("_")},
        "sciagent_verifier_on": {k: v for k, v in sci.items() if not k.startswith("_")},
    }
    (OUT / "run_summary.json").write_text(json.dumps(structured, indent=2, default=str))

    # ----------------- Markdown report ----------------- #
    md = build_markdown(
        cc, sci, summary_rows[0], summary_rows[1],
        out_dir=OUT, cc_dir=cc_dir, sci_dir=sci_dir,
    )
    (OUT / "SUMMARY.md").write_text(md)


def build_markdown(cc, sci, cc_row, sci_row, out_dir: Path, cc_dir: Path, sci_dir: Path):
    OUT = out_dir
    cc_cache_total = cc["cache_creation_input_tokens"] + cc["cache_read_input_tokens"]
    cc_input_side = (
        cc["input_tokens"] + cc["cache_creation_input_tokens"] + cc["cache_read_input_tokens"]
    )
    cc_cache_hit_pct = (
        100.0 * cc["cache_read_input_tokens"] / cc_input_side if cc_input_side else 0
    )

    lines = []
    lines.append(f"# cc-bare vs sciagent — {sci_dir.parent.parent.name}/{sci_dir.name}")
    lines.append("")
    lines.append(f"cc-bare source: `{cc_dir}`")
    lines.append("")
    lines.append(f"sciagent source: `{sci_dir}`")
    lines.append("")
    lines.append("## Top-line side-by-side")
    lines.append("")
    lines.append("| metric | cc-bare | sciagent (verifier on) |")
    lines.append("|---|---:|---:|")
    rows = [
        ("main model", cc_row["main_model"], sci_row["main_model"]),
        ("subagent models", cc_row["subagent_models"] or "(none used)", sci_row["subagent_models"]),
        ("iterations / turns (top level)", cc_row["iterations_or_turns"], sci_row["iterations_or_turns"]),
        ("wall seconds", cc_row["wall_seconds"], sci_row["wall_seconds"]),
        ("API seconds", cc_row["api_seconds"], sci_row["api_seconds"]),
        ("LLM cost (USD)", f"${cc_row['llm_cost_usd']:.4f}", f"${sci_row['llm_cost_usd']:.4f}"),
        ("compute cost (USD)", cc_row["compute_cost_usd"], sci_row["compute_cost_usd"]),
        ("input tokens (uncached prefix)", cc_row["input_tokens_uncached"], sci_row["input_tokens_uncached"]),
        ("output tokens (top level)", cc_row["output_tokens"], sci_row["output_tokens"]),
        ("cache creation input tokens", cc_row["cache_creation_input_tokens"], sci_row["cache_creation_input_tokens"]),
        ("cache read input tokens", cc_row["cache_read_input_tokens"], sci_row["cache_read_input_tokens"]),
        ("tool calls (top level)", cc_row["tool_calls_total"], sci_row["tool_calls_total"]),
        ("compute jobs launched", cc_row["compute_jobs"], sci_row["compute_jobs"]),
        ("sub-agent iterations (sum)", cc_row["subagent_total_iterations"], sci_row["subagent_total_iterations"]),
        ("sub-agent tokens (sum)", cc_row["subagent_total_tokens"], sci_row["subagent_total_tokens"]),
        ("stop reason", cc_row["stop_reason"], sci_row["stop_reason"]),
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} |")
    lines.append("")
    lines.append(
        f"_Cache hit ratio on cc-bare input side: **{cc_cache_hit_pct:.1f}%** "
        f"of {cc_input_side:,} tokens served from cache._"
    )
    lines.append("")

    # cc-bare per-model
    lines.append("## cc-bare — per-model token & cost split")
    lines.append("")
    lines.append("| model | input | output | cache create | cache read | cost USD |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for m, v in cc["model_usage"].items():
        lines.append(
            f"| {m} | {v.get('inputTokens',0):,} | {v.get('outputTokens',0):,} | "
            f"{v.get('cacheCreationInputTokens',0):,} | {v.get('cacheReadInputTokens',0):,} | "
            f"${v.get('costUSD',0):.4f} |"
        )
    lines.append("")

    # cc-bare tools
    lines.append("## cc-bare — tool histogram")
    lines.append("")
    lines.append("| tool | calls |")
    lines.append("|---|---:|")
    for k, v in sorted(cc["tool_uses"].items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append(
        f"Assistant messages: **{cc['assistant_messages']}**, "
        f"text blocks: {cc['text_blocks']}, thinking blocks: {cc['thinking_blocks']}, "
        f"tool_use blocks: {sum(cc['tool_uses'].values())}, "
        f"tool_result blocks (in user msgs): {cc['tool_results_count']}, "
        f"rate-limit events: {cc['rate_limit_events']}, "
        f"sub-agent assistant msgs (via parent_tool_use_id): {cc['sub_agent_messages']}."
    )
    lines.append("")

    # sciagent breakdown
    lines.append("## sciagent — per-session rollup")
    lines.append("")
    lines.append(
        "Following sciagent-bench/adapters/sciagent.py, the analyzer walks the "
        "parent provenance.jsonl and recurses into "
        "`~/.sciagent/sessions/<child_session_id>/provenance.jsonl` for each "
        "`subagent_completed` event. Costs / tokens / tool calls below are summed "
        "from `tool_result` events in every visited session."
    )
    lines.append("")
    lines.append("| session | iterations | wall_s | tool_calls | tokens_in | tokens_out | LLM cost (USD) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for path, r in sci["per_session_rollup"].items():
        lines.append(
            f"| `{path}` | {r.get('iterations')} | "
            f"{(r.get('wall_seconds') or 0):.1f} | {r.get('tool_calls', 0)} | "
            f"{r.get('tokens_in', 0):,} | {r.get('tokens_out', 0):,} | "
            f"${r.get('cost_usd', 0):.4f} |"
        )
    lines.append(
        f"| **TOTAL** | **{sci['total_iterations']}** | "
        f"{sci['wall_seconds']:.1f} (parent wall) | "
        f"**{sum(sci['tool_calls'].values())}** | "
        f"**{sci['total_tokens_in']:,}** | **{sci['total_tokens_out']:,}** | "
        f"**${sci['total_llm_cost_usd']:.4f}** |"
    )
    lines.append("")
    lines.append("### sub-agent summary (from `subagent_completed` events)")
    lines.append("")
    lines.append("| sub-agent | success | iterations | tokens_used* | duration_s | child_session |")
    lines.append("|---|---|---:|---:|---:|---|")
    for s in sci["subagent_rollups"]:
        lines.append(
            f"| {s['name']} | {s['success']} | {s['iterations']} | "
            f"{(s['tokens_used'] or 0):,} | {s['duration_seconds']:.1f} | "
            f"`{s['child_session_id']}` |"
        )
    lines.append("")
    lines.append(
        "_*`tokens_used` in `subagent_completed` is the child's own self-reported "
        "single-number total (in + out + cache). The per-session table above uses "
        "the authoritative `tool_result.tokens_in/out` sums from the child log._"
    )
    lines.append("")

    # Compute cost
    if sci.get("sky_cluster_row"):
        cl = sci["sky_cluster_row"]
        lines.append("## sciagent — compute cost (from `sky.cost_report`)")
        lines.append("")
        lines.append(
            "sciagent-cli's `RunCostTracker.poll_active_clusters` is designed to "
            "ingest exactly this row and emit `compute_cost_observed` into "
            "provenance. For this run no such event was written (cluster manifest "
            "missing), so we query `sky.cost_report()` directly — same number."
        )
        lines.append("")
        lines.append("| field | value |")
        lines.append("|---|---|")
        lines.append(f"| cluster | `{cl.get('name')}` |")
        lines.append(f"| cloud / region | {cl.get('cloud')} / {cl.get('region')} |")
        lines.append(f"| instance | {cl.get('resources_str')} |")
        lines.append(f"| cpus | {cl.get('cpus')} |")
        lines.append(f"| memory (GB) | {cl.get('memory_gb')} |")
        lines.append(f"| nodes | {cl.get('num_nodes')} |")
        lines.append(f"| duration (s) | {cl.get('duration_s')} |")
        lines.append(f"| **total_cost (USD)** | **${cl.get('total_cost_usd'):.4f}** |")
        lines.append("")
    else:
        lines.append("## sciagent — compute cost")
        lines.append("")
        lines.append(
            "_Cluster `sciagent-rcwa-xiong` not found in `sky.cost_report()` — "
            "set compute cost to $0._"
        )
        lines.append("")

    # sciagent tools
    lines.append("## sciagent — orchestrator tool histogram (provenance)")
    lines.append("")
    lines.append("| tool | calls |")
    lines.append("|---|---:|")
    for k, v in sorted(sci["tool_calls"].items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # sciagent compute
    lines.append("## sciagent — compute jobs (managed via SkyPilot)")
    lines.append("")
    lines.append(
        f"`{sci['n_compute_jobs']}` `compute_job_launched` events, "
        f"`{sci['n_cluster_downs']}` `compute_cluster_down` events. "
        f"All jobs hit the `sciagent-rcwa-xiong` cluster. The provenance file "
        f"contains no `compute_cost_observed` event for this run (the cluster "
        f"manifest entry was never written), so the compute cost number above "
        f"is read directly from `sky.cost_report()` — the same row "
        f"`RunCostTracker.poll_active_clusters` would have ingested."
    )
    lines.append("")
    lines.append("| seq | ts | managed_job_id | mode | service |")
    lines.append("|---:|---|---:|---|---|")
    for j in sci["compute_jobs"]:
        lines.append(
            f"| {j['seq']} | {j['ts']} | {j['managed_job_id']} | {j['mode']} | {j['service']} |"
        )
    lines.append("")

    # --------------- Why the per-token vs per-iteration ratios disagree ----
    cc_total = cc["total_cost_usd"]
    sci_total_llm = sci["total_llm_cost_usd"]
    cc_iters = cc["num_turns"]
    sci_iters = sci["total_iterations"]
    cc_tools_total = sum(cc["tool_uses"].values())
    sci_tools_total = sum(sci["tool_calls"].values())
    cc_out = cc["output_tokens"]
    sci_out = sci["total_tokens_out"]

    lines.append("## Why `$ / output token` flips while `$ / iteration` does not")
    lines.append("")
    lines.append(
        "Efficiency ratios point in opposite directions because they share a "
        "numerator but use different denominators. Math:"
    )
    lines.append("")
    lines.append("| metric | cc-bare | sciagent | who's lower |")
    lines.append("|---|---:|---:|---|")
    lines.append(
        f"| total LLM cost | ${cc_total:.2f} | ${sci_total_llm:.2f} | sciagent |"
    )
    lines.append(f"| iterations | {cc_iters} | {sci_iters} | sciagent |")
    lines.append(
        f"| tool calls | {cc_tools_total} | {sci_tools_total} | sciagent |"
    )
    cc_per_iter = cc_total / cc_iters
    sci_per_iter = sci_total_llm / sci_iters
    cc_per_tool = cc_total / cc_tools_total
    sci_per_tool = sci_total_llm / sci_tools_total
    cc_per_out_k = 1000.0 * cc_total / cc_out
    sci_per_out_k = 1000.0 * sci_total_llm / sci_out
    lines.append(
        f"| **output tokens** | **{cc_out:,}** | **{sci_out:,}** | "
        f"**sciagent ({cc_out / sci_out:.1f}× fewer)** |"
    )
    lines.append(
        f"| $/iteration | ${cc_per_iter:.4f} | ${sci_per_iter:.4f} | sciagent |"
    )
    lines.append(
        f"| $/tool call | ${cc_per_tool:.4f} | ${sci_per_tool:.4f} | sciagent |"
    )
    lines.append(
        f"| $/1 k output tokens | **${cc_per_out_k:.4f}** | "
        f"**${sci_per_out_k:.4f}** | **cc-bare** |"
    )
    lines.append("")
    lines.append(
        f"sciagent finishes with {cc_out / sci_out:.1f}× fewer output tokens "
        f"for only {cc_total / sci_total_llm:.1f}× lower total cost, so each "
        f"of its output tokens \"carries\" a much larger input context (the "
        f"compute sub-agent reads big bash outputs and prior turns on every "
        f"call). cc-bare is chatty: many short cached turns producing prose "
        f"(thinking + text blocks) — high output volume per dollar, low "
        f"context per call."
    )
    lines.append("")
    lines.append("It's a profile signature, not a contradiction:")
    lines.append("")
    lines.append(
        "- **per call / per turn** → sciagent wins (does more useful work per LLM round-trip)."
    )
    lines.append(
        "- **per output token** → cc-bare wins "
        f"(its output is \"cheap\" because it rides on top of a "
        f"{cc_cache_hit_pct:.1f} %-cached prefix)."
    )
    lines.append("")
    lines.append("Rule of thumb:")
    lines.append("")
    lines.append("- If you care about **$ to finish the task** → sciagent.")
    lines.append("- If you care about **$ to generate prose / explanation** → cc-bare.")
    lines.append("")

    lines.append("## Files written")
    lines.append("")
    for f in sorted(OUT.iterdir()):
        if f.name in {"analyze_performance.py"}:
            continue
        lines.append(f"- `{f.name}` ({f.stat().st_size:,} B)")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc-dir",  type=Path, required=True,
                    help="Cell dir for the cc-bare run (contains stdout.txt).")
    ap.add_argument("--sci-dir", type=Path, required=True,
                    help="Cell dir for the sciagent run (contains provenance.jsonl).")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Where to write SUMMARY.md + supporting CSVs.")
    args = ap.parse_args(argv)

    if not args.cc_dir.exists():
        raise SystemExit(f"cc-dir not found: {args.cc_dir}")
    if not args.sci_dir.exists():
        raise SystemExit(f"sci-dir not found: {args.sci_dir}")

    cc = analyze_cc_bare(args.cc_dir)
    sci = analyze_sciagent(args.sci_dir)
    write_outputs(cc, sci, args.out_dir, cc_dir=args.cc_dir, sci_dir=args.sci_dir)
    print(f"Wrote performance breakdown to {args.out_dir}")


if __name__ == "__main__":
    main()
