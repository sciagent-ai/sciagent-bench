"""Task vs verification cost separation, per cell, with histograms.

Splits every sciagent cell's total spend into two disjoint bins:
  - **task cost**  — parent session + every subagent child session that
    isn't the verifier (research / compute / analyze / plan / …). Also
    includes compute + storage costs surfaced in either the parent or
    child logs.
  - **verification cost** — the verifier subagent's own session cost.
    This is the "orphan" session (not referenced by any parent-level
    `subagent_completed` event) that gets spawned by
    `TaskOrchestrator._run_llm_verification_gate` at the end of the run.

cc-bare cells have no in-loop verifier by construction, so verification
cost is $0 for those cells. Their total = task cost.

Emits under `icml_results/efficiency/`:
  - `task_vs_verification.md`   — per-cell cost tables + narrative
  - `task_vs_verification.csv`  — same numbers, machine-readable
  - `charts/cc_vs_sciagent_by_task.png`
  - `charts/photonics_variants_split.png`
  - `charts/cost_types_by_cell.png`
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


_THIS  = Path(__file__).resolve()
ICML   = _THIS.parent.parent
SCIAGENT_SESSIONS_ROOT = Path.home() / ".sciagent" / "sessions"


# ---------------------------------------------------------------------------
# Cell inventory — mirror of the other reports so numbers stay consistent
# ---------------------------------------------------------------------------


# For the cross-adapter cost comparison (3 tasks × 2 adapters).
_TASK_CELLS = [
    ("photonics", "cc-bare",  "20260608T200907Z", "photonics__cc-bare__sonnet"),
    ("photonics", "sciagent-verifier-on-default",
                              "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet"),
    ("brca1_fitness_structure", "cc-bare",
                              "20260630T135609Z", "brca1_fitness_structure__cc-bare__sonnet"),
    ("brca1_fitness_structure", "sciagent-verifier-on-default",
                              "20260630T135609Z", "brca1_fitness_structure__sciagent-verifier-on-default__sonnet"),
    ("cfd_fig3_kde", "cc-bare",
                              "20260630T184838Z", "cfd_fig3_kde__cc-bare__sonnet"),
    ("cfd_fig3_kde", "sciagent-verifier-on-default",
                              "20260630T184838Z", "cfd_fig3_kde__sciagent-verifier-on-default__sonnet"),
]


# For the photonics-only variants comparison.
_PHOTONICS_VARIANTS = [
    ("photonics", "sciagent-verifier-on-default",
                    "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet"),
    ("photonics", "sciagent-no-recursion",
                    "20260608T200907Z", "photonics__sciagent-no-recursion__sonnet"),
    ("photonics", "sciagent-crossverifier",
                    "20260608T200907Z", "photonics__sciagent-crossverifier__sonnet"),
    ("photonics", "sciagent-verifier-off",
                    "20260608T200907Z", "photonics__sciagent-verifier-off__sonnet"),
    ("photonics", "cc-bare",
                    "20260608T200907Z", "photonics__cc-bare__sonnet"),
]


# ---------------------------------------------------------------------------
# Provenance walkers
# ---------------------------------------------------------------------------


def _iter_events(path: Path):
    if not path.exists():
        return
    for line in path.open("r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _dt(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _session_costs(prov: Path) -> dict:
    """Sum LLM / compute / storage cost across one session log.

    Compute + storage from `tool_result.cost_usd` (cost_kind=compute/storage)
    and `compute_cost_observed` events. In practice sciagent emits very
    few of these for cluster runs — the authoritative compute cost lives
    in `sky.cost_report()`, so `_sky_cluster_cost` fills that in at the
    cell level (not per-session)."""
    llm = compute = storage = 0.0
    tokens_in = tokens_out = 0
    for ev in _iter_events(prov):
        if ev.get("event_kind") == "tool_result":
            c = ev.get("cost_usd")
            if c is not None:
                k = ev.get("cost_kind") or ""
                cf = float(c)
                if k == "compute":  compute += cf
                elif k == "storage": storage += cf
                else:                llm += cf
            tokens_in  += int(ev.get("tokens_in")  or 0)
            tokens_out += int(ev.get("tokens_out") or 0)
        elif ev.get("event_kind") == "compute_cost_observed":
            c = ev.get("cost_usd")
            if c is not None:
                src = (ev.get("cost_source") or "").lower()
                if "storage" in src: storage += float(c)
                else:                compute += float(c)
    return {"llm": llm, "compute": compute, "storage": storage,
            "tokens_in": tokens_in, "tokens_out": tokens_out}


def _sky_cluster_cost(cluster_name: str) -> float:
    """Query `sky.cost_report()` for cluster total_cost. Returns 0.0
    silently if sky isn't installed, the daemon can't be reached, or
    the cluster isn't in the report. Matches the strategy used in
    `analyze_pair.py`."""
    if not cluster_name:
        return 0.0
    try:
        import sky  # type: ignore
        req = sky.cost_report()
        rows = sky.stream_and_get(req)
    except Exception:
        return 0.0
    for r in rows:
        if isinstance(r, dict) and r.get("name") == cluster_name:
            try:
                return float(r.get("total_cost") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _clusters_used(parent_prov: Path) -> list[str]:
    """Every distinct cluster_name that appears in `compute_job_launched`
    events across parent + child sessions."""
    clusters: set[str] = set()
    for ev in _iter_events(parent_prov):
        if ev.get("event_kind") == "compute_job_launched":
            n = ev.get("cluster_name")
            if n: clusters.add(n)
        elif ev.get("event_kind") == "subagent_completed":
            cid = ev.get("child_session_id")
            if not cid: continue
            child_log = SCIAGENT_SESSIONS_ROOT / cid / "provenance.jsonl"
            if child_log.exists():
                for cev in _iter_events(child_log):
                    if cev.get("event_kind") == "compute_job_launched":
                        n = cev.get("cluster_name")
                        if n: clusters.add(n)
    return sorted(clusters)


def _detect_verifier_session(parent_prov: Path) -> Path | None:
    """Find the orphan session spawned by the verification gate.

    Returns the verifier session's `provenance.jsonl` path, or None if
    the cell has no verifier gate event or the session can't be located
    on disk.
    """
    if not parent_prov.exists():
        return None
    events = list(_iter_events(parent_prov))
    parent_sid = events[0].get("session_id") if events else None
    child_ids  = {e.get("child_session_id") for e in events
                  if e.get("event_kind") == "subagent_completed"
                  and e.get("child_session_id")}
    vr_events  = [e for e in events if e.get("event_kind") == "verification_result"]
    if not vr_events:
        return None
    vr_ts = _dt(vr_events[-1].get("ts"))
    if vr_ts is None:
        return None

    best = None
    for sd in SCIAGENT_SESSIONS_ROOT.iterdir():
        if sd.name == parent_sid or sd.name in child_ids:
            continue
        prov = sd / "provenance.jsonl"
        if not prov.exists():
            continue
        try:
            evs = list(_iter_events(prov))
        except Exception:
            continue
        if not evs:
            continue
        last_ts = _dt(evs[-1].get("ts"))
        if last_ts is None or last_ts > vr_ts:
            continue
        # Must have ended within 5 min of the verification_result
        if (vr_ts - last_ts).total_seconds() > 300:
            continue
        # Verifier subagent uses file_ops to open logs
        n_file_ops = sum(1 for e in evs
                         if e.get("event_kind") == "tool_result"
                         and e.get("tool_name") == "file_ops")
        if n_file_ops == 0:
            continue
        if best is None or last_ts > _dt(json.loads(best[1].open().readline())
                                        .get("ts")):
            best = (sd.name, prov)
    return best[1] if best else None


def analyze_sciagent_cell(cell_dir: Path) -> dict:
    """Split a sciagent cell into task cost + verification cost."""
    parent_prov = cell_dir / "provenance.jsonl"
    parent = _session_costs(parent_prov)

    # Walk subagent_completed → child costs (these are TASK costs)
    child_costs: dict[str, dict] = {}
    for ev in _iter_events(parent_prov):
        if ev.get("event_kind") != "subagent_completed":
            continue
        cid = ev.get("child_session_id")
        if not cid:
            continue
        child_log = SCIAGENT_SESSIONS_ROOT / cid / "provenance.jsonl"
        name = ev.get("subagent_name", "subagent")
        if child_log.exists():
            child_costs[f"{name}/{cid}"] = _session_costs(child_log)
        else:
            child_costs[f"{name}/{cid}"] = {"llm": 0.0, "compute": 0.0,
                                            "storage": 0.0,
                                            "tokens_in": 0, "tokens_out": 0,
                                            "missing_log": True}

    # Verifier session (orphan; not in child_ids)
    verifier_prov = _detect_verifier_session(parent_prov)
    if verifier_prov:
        verifier = _session_costs(verifier_prov)
        verifier["session_id"] = verifier_prov.parent.name
        verifier["found"] = True
    else:
        verifier = {"llm": 0.0, "compute": 0.0, "storage": 0.0,
                    "tokens_in": 0, "tokens_out": 0, "found": False}

    # Task = parent + all subagent children (not verifier)
    task_llm     = parent["llm"]      + sum(c["llm"]      for c in child_costs.values())
    task_compute = parent["compute"]  + sum(c["compute"]  for c in child_costs.values())
    task_storage = parent["storage"]  + sum(c["storage"]  for c in child_costs.values())
    task_tin     = parent["tokens_in"]  + sum(c["tokens_in"]  for c in child_costs.values())
    task_tout    = parent["tokens_out"] + sum(c["tokens_out"] for c in child_costs.values())

    # Cluster compute cost from sky.cost_report() — the authoritative
    # source since sciagent-cli's RunCostTracker doesn't always emit
    # `compute_cost_observed` for successful cluster lifecycles.
    clusters = _clusters_used(parent_prov)
    sky_cost = sum(_sky_cluster_cost(c) for c in clusters)
    task_compute += sky_cost

    return {
        "adapter":            "sciagent",
        "parent":             parent,
        "children":           child_costs,
        "verifier":           verifier,
        "task_llm_usd":       task_llm,
        "task_compute_usd":   task_compute,
        "task_storage_usd":   task_storage,
        "task_tokens_in":     task_tin,
        "task_tokens_out":    task_tout,
        "verification_llm_usd": verifier["llm"],
        "verification_tokens_in":  verifier["tokens_in"],
        "verification_tokens_out": verifier["tokens_out"],
        "total_usd":          task_llm + task_compute + task_storage + verifier["llm"],
    }


def analyze_cc_bare_cell(cell_dir: Path) -> dict:
    """cc-bare: pull cost from Claude Code's stdout stream. No in-loop
    verifier — verification cost is $0."""
    stdout = cell_dir / "stdout.txt"
    total_cost = 0.0
    tokens_in = tokens_out = 0
    n_turns = None
    duration_ms = None
    for ev in _iter_events(stdout):
        if ev.get("type") == "result":
            total_cost = float(ev.get("total_cost_usd") or 0.0)
            usage = ev.get("usage") or {}
            tokens_in  = int(usage.get("input_tokens")  or 0) + \
                         int(usage.get("cache_creation_input_tokens") or 0) + \
                         int(usage.get("cache_read_input_tokens") or 0)
            tokens_out = int(usage.get("output_tokens") or 0)
            n_turns = ev.get("num_turns")
            duration_ms = ev.get("duration_ms")
    return {
        "adapter":                 "cc-bare",
        "task_llm_usd":            total_cost,
        "task_compute_usd":        0.0,
        "task_storage_usd":        0.0,
        "task_tokens_in":          tokens_in,
        "task_tokens_out":         tokens_out,
        "verification_llm_usd":    0.0,
        "verification_tokens_in":  0,
        "verification_tokens_out": 0,
        "total_usd":               total_cost,
        "n_turns":                 n_turns,
        "duration_ms":             duration_ms,
    }


def analyze_cell(icml_root: Path, task: str, condition: str, ts: str, cell_id: str) -> dict:
    cell_dir = icml_root / ts / task / cell_id
    if condition == "cc-bare":
        core = analyze_cc_bare_cell(cell_dir)
    else:
        core = analyze_sciagent_cell(cell_dir)
    core.update({
        "task":      task,
        "condition": condition,
        "ts":        ts,
        "cell_id":   cell_id,
    })
    return core


# ---------------------------------------------------------------------------
# Report + chart writers
# ---------------------------------------------------------------------------


def _fmt(v, fmt="{:.4f}"):
    if v is None or v == "":
        return "—"
    if isinstance(v, (int, float)):
        return fmt.format(v)
    return str(v)


def write_csv(rows: list[dict], out_path: Path) -> None:
    fields = [
        "task", "condition", "cell_id", "adapter",
        "task_llm_usd", "task_compute_usd", "task_storage_usd",
        "verification_llm_usd",
        "total_usd",
        "task_tokens_in", "task_tokens_out",
        "verification_tokens_in", "verification_tokens_out",
    ]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_markdown(task_rows: list[dict], variants_rows: list[dict],
                   out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Cost split — task vs verification\n")
    lines.append(
        "Per cell we separate two disjoint cost bins:\n\n"
        "- **task cost** — parent session + every subagent child session\n"
        "  (research / compute / analyze / plan / …) plus compute/storage\n"
        "  costs observed anywhere in the trajectory.\n"
        "- **verification cost** — the verifier subagent's own session.\n"
        "  This is the orphan session (not referenced by any parent\n"
        "  `subagent_completed` event) that\n"
        "  `TaskOrchestrator._run_llm_verification_gate` spawns at the end\n"
        "  of the run. Detected by: not in child_ids, ends within 5 min of\n"
        "  the parent's `verification_result` event, uses `file_ops` to\n"
        "  open logs.\n\n"
        "cc-bare cells have no in-loop verifier, so verification cost is\n"
        "**$0.00** by construction — total = task cost.\n\n"
    )

    # ---- Cross-adapter table (3 tasks × 2 adapters) ----
    lines.append("## Cross-adapter cost split (3 tasks × 2 adapters)\n")
    lines.append("| task | condition | task LLM $ | task compute $ | task storage $ | verifier LLM $ | total $ | verifier % of total |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|")
    for r in task_rows:
        pct = 100.0 * r["verification_llm_usd"] / r["total_usd"] if r["total_usd"] else 0.0
        lines.append(
            f"| {r['task']} | {r['condition']} | "
            f"{_fmt(r['task_llm_usd'])} | "
            f"{_fmt(r['task_compute_usd'])} | "
            f"{_fmt(r['task_storage_usd'])} | "
            f"{_fmt(r['verification_llm_usd'])} | "
            f"{_fmt(r['total_usd'])} | "
            f"{pct:.1f}% |"
        )
    lines.append("")

    # ---- Photonics variants ----
    lines.append("## Photonics variants — cost split\n")
    lines.append(
        "Same task (photonics), five sciagent + cc-bare variants. "
        "Isolates how the verifier configuration affects verification cost.\n"
    )
    lines.append("| variant | task LLM $ | task compute $ | task storage $ | verifier LLM $ | total $ | verifier % of total |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|")
    for r in variants_rows:
        pct = 100.0 * r["verification_llm_usd"] / r["total_usd"] if r["total_usd"] else 0.0
        lines.append(
            f"| {r['condition']} | "
            f"{_fmt(r['task_llm_usd'])} | "
            f"{_fmt(r['task_compute_usd'])} | "
            f"{_fmt(r['task_storage_usd'])} | "
            f"{_fmt(r['verification_llm_usd'])} | "
            f"{_fmt(r['total_usd'])} | "
            f"{pct:.1f}% |"
        )
    lines.append("")

    # ---- Sciagent-only: per-subagent breakdown for the 3 tasks ----
    lines.append("## Sciagent subagent breakdown (per role)\n")
    lines.append(
        "For each sciagent cell, break `task LLM $` into "
        "parent + per-child-subagent contributions. Verifier row is the "
        "detected orphan session.\n"
    )
    for r in task_rows:
        if r["adapter"] != "sciagent":
            continue
        lines.append(f"### {r['task']} — `{r['condition']}`\n")
        lines.append("| role | LLM $ | tokens in | tokens out |")
        lines.append("|:---|---:|---:|---:|")
        parent = r["parent"]
        lines.append(f"| main (parent) | {_fmt(parent['llm'])} | "
                     f"{parent['tokens_in']:,} | {parent['tokens_out']:,} |")
        for name, c in r["children"].items():
            note = "  (log missing)" if c.get("missing_log") else ""
            lines.append(f"| child `{name}`{note} | {_fmt(c['llm'])} | "
                         f"{c['tokens_in']:,} | {c['tokens_out']:,} |")
        v = r["verifier"]
        sid = v.get("session_id", "(none detected)")
        lines.append(f"| **verifier** `{sid}` | **{_fmt(v['llm'])}** | "
                     f"{v['tokens_in']:,} | {v['tokens_out']:,} |")
        lines.append("")

    # ---- Chart references ----
    lines.append("## Charts\n")
    lines.append("- `charts/cc_vs_sciagent_by_task.png` — task vs verification cost, 3 tasks × cc-bare/sciagent.")
    lines.append("- `charts/photonics_variants_split.png` — same split across the 4 photonics sciagent variants + cc-bare.")
    lines.append("- `charts/cost_types_by_cell.png` — LLM vs compute vs storage per cell (all 6 case-study cells).")
    lines.append("")

    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _chart_cc_vs_sciagent(rows: list[dict], out_path: Path) -> None:
    tasks = sorted({r["task"] for r in rows})
    fig, ax = plt.subplots(figsize=(10, 5))
    x = list(range(len(tasks)))
    bar_w = 0.35
    cc_totals   = [next((r for r in rows if r["task"] == t and r["condition"] == "cc-bare"), {}).get("total_usd", 0)                    for t in tasks]
    sci_task    = [next((r for r in rows if r["task"] == t and r["condition"] == "sciagent-verifier-on-default"), {}).get("task_llm_usd", 0)  + next((r for r in rows if r["task"] == t and r["condition"] == "sciagent-verifier-on-default"), {}).get("task_compute_usd", 0) + next((r for r in rows if r["task"] == t and r["condition"] == "sciagent-verifier-on-default"), {}).get("task_storage_usd", 0) for t in tasks]
    sci_verif   = [next((r for r in rows if r["task"] == t and r["condition"] == "sciagent-verifier-on-default"), {}).get("verification_llm_usd", 0) for t in tasks]

    cc_pos  = [xi - bar_w/2 for xi in x]
    sci_pos = [xi + bar_w/2 for xi in x]

    ax.bar(cc_pos, cc_totals, bar_w, label="cc-bare (task, no verification)", color="#8ba6c9")
    ax.bar(sci_pos, sci_task, bar_w, label="sciagent — task cost", color="#3a7bd5")
    ax.bar(sci_pos, sci_verif, bar_w, bottom=sci_task, label="sciagent — verification cost", color="#f2a900")

    ax.set_xticks(x)
    ax.set_xticklabels(tasks)
    ax.set_ylabel("cost (USD)")
    ax.set_title("Total cost per task — cc-bare vs sciagent, with verification cost stacked")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _chart_photonics_variants(rows: list[dict], out_path: Path) -> None:
    # rows are the photonics variants
    labels = [r["condition"] for r in rows]
    task_llm    = [r["task_llm_usd"] for r in rows]
    task_comp   = [r.get("task_compute_usd", 0.0) for r in rows]
    task_stor   = [r.get("task_storage_usd", 0.0) for r in rows]
    verif_llm   = [r["verification_llm_usd"] for r in rows]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = list(range(len(labels)))
    ax.bar(x, task_llm,   label="task — LLM $",     color="#3a7bd5")
    ax.bar(x, task_comp,  bottom=task_llm,          label="task — compute $", color="#00c9a7")
    ax.bar(x, task_stor,  bottom=[a+b for a,b in zip(task_llm, task_comp)],
                          label="task — storage $", color="#8fdfff")
    ax.bar(x, verif_llm,  bottom=[a+b+c for a,b,c in zip(task_llm, task_comp, task_stor)],
                          label="verification — LLM $", color="#f2a900")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("cost (USD)")
    ax.set_title("Photonics: cost split across variants (task vs verification)")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _chart_cost_types(rows: list[dict], out_path: Path) -> None:
    labels = [f"{r['task'][:14]}\n{r['condition'][:16]}" for r in rows]
    task_llm  = [r["task_llm_usd"] for r in rows]
    task_comp = [r.get("task_compute_usd", 0.0) for r in rows]
    task_stor = [r.get("task_storage_usd", 0.0) for r in rows]
    verif_llm = [r["verification_llm_usd"] for r in rows]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = list(range(len(labels)))
    bar_w = 0.2
    ax.bar([xi - 1.5*bar_w for xi in x], task_llm,  bar_w, label="task LLM $",     color="#3a7bd5")
    ax.bar([xi - 0.5*bar_w for xi in x], task_comp, bar_w, label="task compute $", color="#00c9a7")
    ax.bar([xi + 0.5*bar_w for xi in x], task_stor, bar_w, label="task storage $", color="#8fdfff")
    ax.bar([xi + 1.5*bar_w for xi in x], verif_llm, bar_w, label="verifier LLM $", color="#f2a900")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("cost (USD)")
    ax.set_title("Cost by type, per case-study cell")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML)
    ap.add_argument("--out-dir",   type=Path, default=_THIS.parent)
    args = ap.parse_args(argv)

    charts_dir = args.out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    task_rows = [analyze_cell(args.icml_root, task, cond, ts, cid)
                 for task, cond, ts, cid in _TASK_CELLS]
    variants_rows = [analyze_cell(args.icml_root, task, cond, ts, cid)
                     for task, cond, ts, cid in _PHOTONICS_VARIANTS]

    # CSV mirror (both tables merged; task_rows first)
    csv_rows: list[dict] = []
    for r in task_rows: csv_rows.append({**r})
    for r in variants_rows: csv_rows.append({**r})
    write_csv(csv_rows, args.out_dir / "task_vs_verification.csv")

    # Markdown
    md_path = args.out_dir / "task_vs_verification.md"
    write_markdown(task_rows, variants_rows, md_path)

    # Charts
    _chart_cc_vs_sciagent(task_rows,      charts_dir / "cc_vs_sciagent_by_task.png")
    _chart_photonics_variants(variants_rows, charts_dir / "photonics_variants_split.png")
    _chart_cost_types(task_rows,          charts_dir / "cost_types_by_cell.png")

    print(f"wrote {md_path}")
    print(f"wrote {args.out_dir / 'task_vs_verification.csv'}")
    print(f"charts: {charts_dir}")
    for r in task_rows + variants_rows:
        v = r.get("verifier", {})
        ver_sid = v.get("session_id", "(none)") if isinstance(v, dict) else "(none)"
        print(f"  {r['task']:26s} {r['condition']:32s}  "
              f"task ${r['task_llm_usd']+r.get('task_compute_usd',0)+r.get('task_storage_usd',0):.4f}  "
              f"verif ${r['verification_llm_usd']:.4f}  verifier_sid={ver_sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
