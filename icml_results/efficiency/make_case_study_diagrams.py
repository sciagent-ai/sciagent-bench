"""Polished per-case-study efficiency diagrams — the make_diagram.py
style, applied uniformly across the 3 case studies with the verifier
subagent broken out as its own segment.

For each of {photonics, brca1_fitness_structure, cfd_fig3_kde} we
produce one 6-panel figure comparing cc-bare vs sciagent-verifier-on-
default on:

  (0,0) Wall-clock time
  (0,1) Cost (LLM + compute + verifier LLM, stacked)
  (0,2) Iterations (sciagent stacked by parent / compute / analyze / verifier)
  (1,0) Tokens (cc-bare stacked by cache read/create/input+output;
                sciagent stacked by role)
  (1,1) Tool calls (both stacked by role for sciagent)
  (1,2) Remote compute jobs

Then one cross-case-study summary:
  `summary_by_task.png` — three-panel row, one per task, cost stacked
  (task LLM + task compute + verifier LLM) side by side.

The verifier session is detected the same way as
`analyze_task_vs_verification.py` (orphan session, `file_ops`-heavy,
ends within 5 min of the parent's `verification_result` event).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


_THIS = Path(__file__).resolve()
ICML  = _THIS.parent.parent
sys.path.insert(0, str(_THIS.parent))

# Reuse extractors: same numbers as task_vs_verification.md.
from analyze_task_vs_verification import (  # noqa: E402
    _iter_events, _detect_verifier_session, _sky_cluster_cost,
    _clusters_used, SCIAGENT_SESSIONS_ROOT,
)


# Cross-case-study inventory (cc-bare + sciagent-verifier-on-default per task)
_CASE_STUDIES = [
    {
        "task":     "photonics",
        "cc_dir":   "20260608T200907Z/photonics/photonics__cc-bare__sonnet",
        "sci_dir":  "20260630T120254Z/photonics/photonics__sciagent-verifier-on-default__sonnet",
    },
    {
        "task":     "brca1_fitness_structure",
        "cc_dir":   "20260630T135609Z/brca1_fitness_structure/brca1_fitness_structure__cc-bare__sonnet",
        "sci_dir":  "20260630T135609Z/brca1_fitness_structure/brca1_fitness_structure__sciagent-verifier-on-default__sonnet",
    },
    {
        "task":     "cfd_fig3_kde",
        "cc_dir":   "20260630T184838Z/cfd_fig3_kde/cfd_fig3_kde__cc-bare__sonnet",
        "sci_dir":  "20260630T184838Z/cfd_fig3_kde/cfd_fig3_kde__sciagent-verifier-on-default__sonnet",
    },
]


# ---------------------------------------------------------------------------
# Palette lifted from make_diagram.py so the diagrams remain visually
# consistent with the paper's earlier photonics figures.
# ---------------------------------------------------------------------------
CC_BASE  = "#3C6E97"
CC_LIGHT = "#9DB7CB"
CC_DARK  = "#1F3A53"
SCI_BASE   = "#D17B2B"
SCI_LIGHT  = "#F0BB87"
SCI_DARK   = "#7D4515"
SCI_ACCENT = "#5DA271"   # analyze / research
VERIFY_C   = "#C13F5E"   # verifier — visually distinct from other roles
COMPUTE_C  = "#8CAA65"   # compute component (AWS/cluster)


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _cc_stats(cell_dir: Path) -> dict:
    stdout = cell_dir / "stdout.txt"
    tool_uses = Counter()
    n_asst = 0
    init = result = None
    for ev in _iter_events(stdout):
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            init = ev
        elif t == "result":
            result = ev
        elif t == "assistant":
            n_asst += 1
            for blk in (ev.get("message") or {}).get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    tool_uses[blk.get("name", "")] += 1
    if not result:
        result = {}
    usage = result.get("usage") or {}
    return {
        "model":               result.get("model") or (init or {}).get("model") or "",
        "total_cost_usd":      float(result.get("total_cost_usd") or 0.0),
        "duration_ms":         int(result.get("duration_ms") or 0),
        "num_turns":           int(result.get("num_turns") or 0),
        "input_tokens":        int(usage.get("input_tokens") or 0),
        "output_tokens":       int(usage.get("output_tokens") or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_tokens":     int(usage.get("cache_read_input_tokens") or 0),
        "tool_uses":           dict(tool_uses),
        "n_tool_calls":        int(sum(tool_uses.values())),
    }


def _session_stats(prov: Path) -> dict:
    """Aggregate per-session: LLM cost + tokens + iterations + tool_calls +
    wall_seconds + compute_job count."""
    if not prov.exists():
        return {"llm": 0.0, "compute": 0.0, "storage": 0.0,
                "tokens_in": 0, "tokens_out": 0,
                "iterations": 0, "tool_calls": 0,
                "wall_seconds": 0.0, "n_compute_jobs": 0}
    llm = compute = storage = 0.0
    tokens_in = tokens_out = 0
    iterations = 0
    tool_calls = 0
    wall = 0.0
    n_compute_jobs = 0
    for ev in _iter_events(prov):
        k = ev.get("event_kind")
        if k == "tool_result":
            c = ev.get("cost_usd")
            if c is not None:
                ck = ev.get("cost_kind") or ""
                cf = float(c)
                if ck == "compute":  compute += cf
                elif ck == "storage": storage += cf
                else:                 llm += cf
            tokens_in  += int(ev.get("tokens_in")  or 0)
            tokens_out += int(ev.get("tokens_out") or 0)
        elif k == "tool_call":
            tool_calls += 1
        elif k == "compute_job_launched":
            n_compute_jobs += 1
        elif k == "session_end":
            iterations = int(ev.get("iterations") or 0)
            wall = float(ev.get("wall_seconds") or 0.0)
    return {"llm": llm, "compute": compute, "storage": storage,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "iterations": iterations, "tool_calls": tool_calls,
            "wall_seconds": wall, "n_compute_jobs": n_compute_jobs}


def _sci_stats(cell_dir: Path) -> dict:
    """Sciagent per-role: parent + each child subagent (grouped by role) +
    verifier. Includes cluster compute cost from sky.cost_report()."""
    prov = cell_dir / "provenance.jsonl"
    parent = _session_stats(prov)

    # Group children by role (compute / analyze / research / …). Some
    # cells (photonics) spawn multiple "research" subagents — sum them.
    role_stats: dict[str, dict] = {}
    for ev in _iter_events(prov):
        if ev.get("event_kind") != "subagent_completed":
            continue
        cid = ev.get("child_session_id")
        if not cid: continue
        name = ev.get("subagent_name", "subagent")
        child_log = SCIAGENT_SESSIONS_ROOT / cid / "provenance.jsonl"
        cs = _session_stats(child_log)
        if name not in role_stats:
            role_stats[name] = {"llm": 0.0, "compute": 0.0, "storage": 0.0,
                                "tokens_in": 0, "tokens_out": 0,
                                "iterations": 0, "tool_calls": 0,
                                "wall_seconds": 0.0, "n_compute_jobs": 0,
                                "n_children": 0}
        for kk in ("llm", "compute", "storage", "tokens_in", "tokens_out",
                    "iterations", "tool_calls", "wall_seconds", "n_compute_jobs"):
            role_stats[name][kk] += cs[kk]
        role_stats[name]["n_children"] += 1

    # Verifier (orphan session)
    ver_prov = _detect_verifier_session(prov)
    verifier = _session_stats(ver_prov) if ver_prov else \
               {"llm": 0.0, "compute": 0.0, "storage": 0.0,
                "tokens_in": 0, "tokens_out": 0,
                "iterations": 0, "tool_calls": 0,
                "wall_seconds": 0.0, "n_compute_jobs": 0}

    # Cluster compute from sky.cost_report(), attributed to task (not verifier).
    clusters = _clusters_used(prov)
    sky_cost = sum(_sky_cluster_cost(c) for c in clusters)

    return {
        "parent":         parent,
        "roles":          role_stats,          # dict of role -> aggregated stats
        "verifier":       verifier,
        "sky_compute":    sky_cost,
        "n_compute_jobs": parent["n_compute_jobs"] + sum(r["n_compute_jobs"] for r in role_stats.values()),
    }


# ---------------------------------------------------------------------------
# Chart 1: 6-panel per case study
# ---------------------------------------------------------------------------


def _bar_stacked(ax, x, layers, labels, colors, edge="black", bar_w=0.55):
    """Draw a stacked bar at position `x` from bottom to top."""
    bottom = 0.0
    for val, lbl, col in zip(layers, labels, colors):
        if val <= 0: continue
        ax.bar(x, val, bar_w, bottom=bottom, color=col, edgecolor=edge,
                linewidth=0.4, label=lbl if bottom == 0.0 or True else None)
        bottom += val
    return bottom


def make_case_study_diagram(task: str, cc_stats: dict, sci: dict,
                             out_path: Path) -> None:
    LABELS = ["cc-bare", "sciagent\n(verifier on)"]
    BAR_W  = 0.55

    fig, axes = plt.subplots(2, 3, figsize=(16, 10.5))
    plt.subplots_adjust(left=0.06, right=0.97, top=0.90, bottom=0.14,
                        wspace=0.32, hspace=0.60)

    fig.suptitle(
        f"{task}  —  cc-bare vs sciagent (verifier on, default)",
        fontsize=13, fontweight="bold", y=0.965,
    )

    # ============ (0,0) Wall-clock time ============
    ax = axes[0, 0]
    cc_wall  = cc_stats["duration_ms"] / 1000.0
    sci_wall = sci["parent"]["wall_seconds"]
    ax.bar([0, 1], [cc_wall, sci_wall], BAR_W, color=[CC_BASE, SCI_BASE],
            edgecolor="black", linewidth=0.4)
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Wall-clock time", fontweight="bold", pad=6)
    ax.set_ylabel("seconds")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    for i, v in enumerate([cc_wall, sci_wall]):
        ax.text(i, v, f"{v:,.0f}s", ha="center", va="bottom",
                fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(cc_wall, sci_wall) * 1.20 or 1.0)

    # ============ (0,1) Cost (LLM + compute + verifier LLM) ============
    ax = axes[0, 1]
    # cc-bare: just LLM
    ax.bar([0], [cc_stats["total_cost_usd"]], BAR_W, color=CC_BASE,
            edgecolor="black", linewidth=0.4, label="cc-bare LLM")
    # sciagent: task LLM (parent + roles) + compute + verifier LLM (stacked)
    task_llm = sci["parent"]["llm"] + sum(r["llm"] for r in sci["roles"].values())
    task_compute = sci["parent"]["compute"] + sum(r["compute"] for r in sci["roles"].values()) + sci["sky_compute"]
    verif_llm = sci["verifier"]["llm"]
    b = 0.0
    ax.bar([1], [task_llm], BAR_W, bottom=b, color=SCI_BASE,
            edgecolor="black", linewidth=0.4, label="sciagent task LLM")
    b += task_llm
    if task_compute > 0:
        ax.bar([1], [task_compute], BAR_W, bottom=b, color=COMPUTE_C,
                edgecolor="black", linewidth=0.4, label="sciagent compute (cluster)")
        b += task_compute
    if verif_llm > 0:
        ax.bar([1], [verif_llm], BAR_W, bottom=b, color=VERIFY_C,
                edgecolor="black", linewidth=0.4, label="sciagent verifier LLM")
        b += verif_llm
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Cost (LLM + compute, USD)", fontweight="bold", pad=6)
    ax.set_ylabel("USD")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.text(0, cc_stats["total_cost_usd"], f"${cc_stats['total_cost_usd']:.2f}",
            ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.text(1, b, f"${b:.2f}", ha="center", va="bottom",
            fontsize=10, fontweight="bold")
    top = max(cc_stats["total_cost_usd"], b) * 1.25 or 1.0
    ax.set_ylim(0, top)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.55), fontsize=8, ncol=2, frameon=False)

    # ============ (0,2) Iterations ============
    ax = axes[0, 2]
    ax.bar([0], [cc_stats["num_turns"]], BAR_W, color=CC_BASE,
            edgecolor="black", linewidth=0.4)
    # sciagent stacked by role (parent + each role + verifier)
    parent_it = sci["parent"]["iterations"]
    role_its = [(name, r["iterations"]) for name, r in sci["roles"].items()]
    ver_it = sci["verifier"]["iterations"]
    b = 0.0
    role_colors = _role_color_map(list(sci["roles"].keys()))
    ax.bar([1], [parent_it], BAR_W, bottom=b, color=SCI_BASE,
            edgecolor="black", linewidth=0.4, label="parent")
    b += parent_it
    for (name, it) in role_its:
        if it == 0: continue
        ax.bar([1], [it], BAR_W, bottom=b, color=role_colors[name],
                edgecolor="black", linewidth=0.4, label=name)
        b += it
    if ver_it > 0:
        ax.bar([1], [ver_it], BAR_W, bottom=b, color=VERIFY_C,
                edgecolor="black", linewidth=0.4, label="verifier")
        b += ver_it
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Iterations", fontweight="bold", pad=6)
    ax.set_ylabel("count")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.text(0, cc_stats["num_turns"], f"top {cc_stats['num_turns']}",
            ha="center", va="bottom", fontsize=9)
    ax.text(1, b, f"total {int(b)}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylim(0, max(cc_stats["num_turns"], b) * 1.25 or 1.0)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.55), fontsize=8, ncol=3, frameon=False)

    # ============ (1,0) Tokens (stacked by source) ============
    ax = axes[1, 0]
    # cc-bare: top-level = input+output; cache create; cache read
    cc_top   = cc_stats["input_tokens"] + cc_stats["output_tokens"]
    cc_ccre  = cc_stats["cache_creation_tokens"]
    cc_cread = cc_stats["cache_read_tokens"]
    b = 0.0
    ax.bar([0], [cc_top],  BAR_W, bottom=b, color=CC_DARK,
            edgecolor="black", linewidth=0.4, label="cc-bare top-level (in+out)")
    b += cc_top
    ax.bar([0], [cc_ccre], BAR_W, bottom=b, color=CC_BASE,
            edgecolor="black", linewidth=0.4, label="cc-bare cache create")
    b += cc_ccre
    ax.bar([0], [cc_cread], BAR_W, bottom=b, color=CC_LIGHT,
            edgecolor="black", linewidth=0.4, label="cc-bare cache read")
    cc_total_tokens = b + cc_cread
    # sciagent: parent + role + verifier (all in+out)
    b = 0.0
    parent_tok = sci["parent"]["tokens_in"] + sci["parent"]["tokens_out"]
    ax.bar([1], [parent_tok], BAR_W, bottom=b, color=SCI_BASE,
            edgecolor="black", linewidth=0.4, label="sciagent parent")
    b += parent_tok
    for (name, r) in sci["roles"].items():
        tok = r["tokens_in"] + r["tokens_out"]
        if tok == 0: continue
        ax.bar([1], [tok], BAR_W, bottom=b, color=role_colors[name],
                edgecolor="black", linewidth=0.4, label=f"sciagent {name}")
        b += tok
    ver_tok = sci["verifier"]["tokens_in"] + sci["verifier"]["tokens_out"]
    if ver_tok > 0:
        ax.bar([1], [ver_tok], BAR_W, bottom=b, color=VERIFY_C,
                edgecolor="black", linewidth=0.4, label="sciagent verifier")
        b += ver_tok
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Tokens (stacked by source)", fontweight="bold", pad=6)
    ax.set_ylabel("tokens")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    def _fmt_tok(v):
        if v >= 1e6: return f"{v/1e6:.2f}M"
        if v >= 1e3: return f"{v/1e3:.0f}K"
        return str(int(v))
    ax.text(0, cc_total_tokens, _fmt_tok(cc_total_tokens),
             ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.text(1, b, _fmt_tok(b), ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(cc_total_tokens, b) * 1.25 or 1.0)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.55), fontsize=7, ncol=2, frameon=False)

    # ============ (1,1) Tool calls (LLM-driven) ============
    ax = axes[1, 1]
    ax.bar([0], [cc_stats["n_tool_calls"]], BAR_W, color=CC_BASE,
            edgecolor="black", linewidth=0.4, label="cc-bare tool_use")
    b = 0.0
    parent_tc = sci["parent"]["tool_calls"]
    ax.bar([1], [parent_tc], BAR_W, bottom=b, color=SCI_BASE,
            edgecolor="black", linewidth=0.4, label="sciagent parent")
    b += parent_tc
    for (name, r) in sci["roles"].items():
        if r["tool_calls"] == 0: continue
        ax.bar([1], [r["tool_calls"]], BAR_W, bottom=b,
                color=role_colors[name], edgecolor="black", linewidth=0.4,
                label=name)
        b += r["tool_calls"]
    ver_tc = sci["verifier"]["tool_calls"]
    if ver_tc > 0:
        ax.bar([1], [ver_tc], BAR_W, bottom=b, color=VERIFY_C,
                edgecolor="black", linewidth=0.4, label="verifier")
        b += ver_tc
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Tool calls (LLM-driven)", fontweight="bold", pad=6)
    ax.set_ylabel("count")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.text(0, cc_stats["n_tool_calls"], str(cc_stats["n_tool_calls"]),
            ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.text(1, b, str(int(b)), ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(cc_stats["n_tool_calls"], b) * 1.25 or 1.0)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.55), fontsize=7, ncol=3, frameon=False)

    # ============ (1,2) Remote compute jobs ============
    ax = axes[1, 2]
    ax.bar([0, 1], [0, sci["n_compute_jobs"]], BAR_W,
            color=[CC_BASE, SCI_BASE], edgecolor="black", linewidth=0.4)
    ax.set_xticks([0, 1]); ax.set_xticklabels(LABELS)
    ax.set_title("Remote compute jobs (SkyPilot)", fontweight="bold", pad=6)
    ax.set_ylabel("count")
    ax.grid(axis="y", linestyle=":", alpha=0.5)
    ax.text(0, 0, "0", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.text(1, sci["n_compute_jobs"], str(sci["n_compute_jobs"]),
            ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(1, sci["n_compute_jobs"]) * 1.30)

    fig.text(0.5, 0.03,
             "sciagent cost = task LLM (parent + subagents) + compute (sky.cost_report) + verifier LLM (orphan session).\n"
             "cc-bare cost = Claude Code's `total_cost_usd`; iteration = num_turns; tokens include cache-hit/miss.",
             ha="center", va="bottom", fontsize=8, style="italic")

    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _role_color_map(role_names: list[str]) -> dict[str, str]:
    """Assign colors to subagent roles from a fixed palette."""
    palette = [SCI_LIGHT, SCI_ACCENT, "#B4A0D6", "#6E9DB5", "#D9A05B"]
    out = {}
    for i, r in enumerate(role_names):
        out[r] = palette[i % len(palette)]
    return out


# ---------------------------------------------------------------------------
# Cross-case-study summary chart
# ---------------------------------------------------------------------------


def make_summary_diagram(case_data: list[dict], out_path: Path) -> None:
    """Three-panel row (one per case study) — cost stacked cc-bare vs
    sciagent. Small readable version for the paper's efficiency table."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
    fig.suptitle("Cost per case study — cc-bare vs sciagent (verifier on, default)",
                 fontsize=13, fontweight="bold", y=1.0)

    for ax, case in zip(axes, case_data):
        cc  = case["cc"]
        sci = case["sci"]
        task = case["task"]

        cc_cost = cc["total_cost_usd"]
        task_llm     = sci["parent"]["llm"] + sum(r["llm"] for r in sci["roles"].values())
        task_compute = sci["parent"]["compute"] + sum(r["compute"] for r in sci["roles"].values()) + sci["sky_compute"]
        verif_llm    = sci["verifier"]["llm"]

        # cc-bare
        ax.bar([0], [cc_cost], 0.55, color=CC_BASE, edgecolor="black", linewidth=0.4)
        ax.text(0, cc_cost, f"${cc_cost:.2f}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")
        # sciagent stacked
        b = 0.0
        ax.bar([1], [task_llm], 0.55, bottom=b, color=SCI_BASE,
                edgecolor="black", linewidth=0.4, label="task LLM")
        b += task_llm
        if task_compute > 0:
            ax.bar([1], [task_compute], 0.55, bottom=b, color=COMPUTE_C,
                    edgecolor="black", linewidth=0.4, label="task compute")
            b += task_compute
        if verif_llm > 0:
            ax.bar([1], [verif_llm], 0.55, bottom=b, color=VERIFY_C,
                    edgecolor="black", linewidth=0.4, label="verifier LLM")
            b += verif_llm
        ax.text(1, b, f"${b:.2f}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")

        ax.set_xticks([0, 1]); ax.set_xticklabels(["cc-bare", "sciagent"])
        ax.set_title(task, fontweight="bold", pad=6)
        ax.set_ylabel("USD")
        ax.grid(axis="y", linestyle=":", alpha=0.5)
        top = max(cc_cost, b) * 1.30 or 1.0
        ax.set_ylim(0, top)

    # single legend
    handles, labels = axes[-1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False,
                   fontsize=10, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root",  type=Path, default=ICML)
    ap.add_argument("--charts-dir", type=Path, default=_THIS.parent / "charts")
    args = ap.parse_args(argv)

    args.charts_dir.mkdir(parents=True, exist_ok=True)

    case_data = []
    for cs in _CASE_STUDIES:
        task    = cs["task"]
        cc_dir  = args.icml_root / cs["cc_dir"]
        sci_dir = args.icml_root / cs["sci_dir"]
        cc_stats  = _cc_stats(cc_dir)
        sci_stats = _sci_stats(sci_dir)
        case_data.append({"task": task, "cc": cc_stats, "sci": sci_stats})

        out_path = args.charts_dir / f"{task}_efficiency.png"
        make_case_study_diagram(task, cc_stats, sci_stats, out_path)
        print(f"wrote {out_path}")

    summary_path = args.charts_dir / "summary_by_task.png"
    make_summary_diagram(case_data, summary_path)
    print(f"wrote {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
