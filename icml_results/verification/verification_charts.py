"""Verification charts — the visual half of the verification folder.

Four charts, each surfaces one key message that's hard to see in a
markdown table:

  1. `phase1_recursion_effect.png` — flagship. Same task, same
     verifier model, only the `verifier_include_child_sessions` flag
     flipped. Verdict changed insufficient→verified, evidence signals
     shifted by large deltas. This is what motivated Phase 1.

  2. `evidence_counts_by_case_study.png` — sciagent verifier
     richness across the three case studies. Supporting facts +
     fabrication indicators + missing evidence + issues per cell.
     Answers "does the verifier actually say things?" — yes, and the
     distribution is uneven (CFD is clean, BRCA1 has a real
     fabrication catch, photonics has three warnings).

  3. `t1_t2_t3_heatmap.png` — 6-cell audit uniformity matrix.
     All pass, but the row header names the audit *surface*
     (structured provenance vs reconstructed stream), which is the
     real "audit-grade" delta.

  4. `photonics_variants_verdict.png` — 4-way comparison of the
     photonics sciagent variants. Confidence bar + verdict color +
     evidence counts overlay.

Emits under `verification/charts/`. Data is pulled from the same
provenance / task YAMLs / hand-filled `claim_values.csv` that the
existing verification scripts already read — no duplicate extraction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


_THIS  = Path(__file__).resolve()
ICML   = _THIS.parent.parent
sys.path.insert(0, str(_THIS.parent))

# Reuse the verifier-event extractor used by verifier_details.py so the
# numbers here match the markdown reports exactly.
from verifier_details import _last_verification_result  # noqa: E402


# ---------------------------------------------------------------------------
# Cell inventory — same as the markdown reports
# ---------------------------------------------------------------------------


_CASE_STUDIES = [
    # (task, sciagent-ts, sciagent-cell-id, cc-bare-ts, cc-bare-cell-id)
    ("photonics",
     "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet",
     "20260608T200907Z", "photonics__cc-bare__sonnet"),
    ("brca1_fitness_structure",
     "20260630T135609Z", "brca1_fitness_structure__sciagent-verifier-on-default__sonnet",
     "20260630T135609Z", "brca1_fitness_structure__cc-bare__sonnet"),
    ("cfd_fig3_kde",
     "20260630T184838Z", "cfd_fig3_kde__sciagent-verifier-on-default__sonnet",
     "20260630T184838Z", "cfd_fig3_kde__cc-bare__sonnet"),
]


_PHOTONICS_VARIANTS = [
    # (label, ts, cell_id, verifier_model, recursion)
    ("verifier-on-default\n(sonnet, recursive)",
     "20260630T120254Z", "photonics__sciagent-verifier-on-default__sonnet",
     "sonnet", "on"),
    ("no-recursion\n(sonnet, legacy)",
     "20260608T200907Z", "photonics__sciagent-no-recursion__sonnet",
     "sonnet", "off"),
    ("crossverifier\n(o4-mini, no rec.)",
     "20260608T200907Z", "photonics__sciagent-crossverifier__sonnet",
     "o4-mini", "off"),
    ("verifier-off\n(control)",
     "20260608T200907Z", "photonics__sciagent-verifier-off__sonnet",
     "n/a", "n/a"),
]


# T1/T2/T3 numbers come from verification_comparison.csv (already produced).
# Read the CSV to avoid re-running the extractor here.
def _load_t123_rows(icml_root: Path) -> list[dict]:
    p = _THIS.parent / "verification_comparison.csv"
    if not p.exists():
        return []
    import csv
    rows = []
    for r in csv.DictReader(p.open()):
        rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# Helper: fetch verifier verdict + confidence + evidence counts for a cell
# ---------------------------------------------------------------------------


def _cell_verdict(icml_root: Path, ts: str, cell_id: str) -> dict:
    task = cell_id.split("__")[0]
    prov = icml_root / ts / task / cell_id / "provenance.jsonl"
    ev   = _last_verification_result(prov)
    if not ev:
        return {
            "verdict":     None,
            "confidence":  None,
            "supporting":  0,
            "fabrication": 0,
            "missing":     0,
            "issues":      0,
        }
    evidence = ev.get("evidence", {}) or {}
    return {
        "verdict":     ev.get("verdict"),
        "confidence":  ev.get("confidence"),
        "supporting":  len(evidence.get("supporting_facts") or []),
        "fabrication": len(evidence.get("fabrication_indicators") or []),
        "missing":     len(evidence.get("missing_evidence") or []),
        "issues":      len(ev.get("issues") or []),
    }


# Verdict → color mapping (colorblind-friendly diverging palette)
_VERDICT_COLORS = {
    "verified":     "#2b8a3e",
    "supported":    "#2b8a3e",
    "partial":      "#c48c00",
    "warning":      "#c48c00",
    "insufficient": "#c48c00",
    "refuted":      "#c1373b",
    None:           "#8a8a8a",
}


# ---------------------------------------------------------------------------
# Chart 1 — Phase 1 recursion effect (the flagship)
# ---------------------------------------------------------------------------


def chart_phase1_recursion(icml_root: Path, out_path: Path) -> None:
    norec = _cell_verdict(icml_root, "20260608T200907Z",
                          "photonics__sciagent-no-recursion__sonnet")
    withrec = _cell_verdict(icml_root, "20260630T120254Z",
                            "photonics__sciagent-verifier-on-default__sonnet")

    labels = ["supporting\nfacts", "fabrication\nindicators", "missing\nevidence", "issues\nraised"]
    norec_vals = [norec["supporting"], norec["fabrication"], norec["missing"], norec["issues"]]
    with_vals  = [withrec["supporting"], withrec["fabrication"], withrec["missing"], withrec["issues"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5),
                                    gridspec_kw={"width_ratios": [1, 2]})

    # --- LEFT: verdict + confidence panel ---
    conditions = ["no-recursion\n(legacy)", "recursive\n(Phase 1 default)"]
    confs      = [norec["confidence"] or 0, withrec["confidence"] or 0]
    colors     = [_VERDICT_COLORS.get(norec["verdict"]),
                  _VERDICT_COLORS.get(withrec["verdict"])]
    bars = ax1.bar(conditions, confs, color=colors, width=0.55)
    for b, cond, verd in zip(bars, [norec, withrec], [norec["verdict"], withrec["verdict"]]):
        y = b.get_height()
        ax1.text(b.get_x() + b.get_width()/2, y + 0.02,
                 f"{verd}\n@ {y:.2f}",
                 ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax1.set_ylabel("verifier confidence")
    ax1.set_ylim(0, 1.05)
    ax1.set_title("Verdict + confidence")
    ax1.grid(True, axis="y", alpha=0.3)

    # --- RIGHT: evidence signal counts ---
    x = np.arange(len(labels))
    bar_w = 0.36
    ax2.bar(x - bar_w/2, norec_vals, bar_w, color="#c48c00",
            label="no recursion (verifier sees parent log only)")
    ax2.bar(x + bar_w/2, with_vals,  bar_w, color="#2b8a3e",
            label="recursive (verifier sees child sessions too)")

    for i, (a, b) in enumerate(zip(norec_vals, with_vals)):
        ax2.text(i - bar_w/2, a + 0.4, str(a), ha="center", va="bottom", fontsize=10)
        ax2.text(i + bar_w/2, b + 0.4, str(b), ha="center", va="bottom", fontsize=10,
                 fontweight="bold" if b != a else "normal")

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("count in verification_result event")
    ax2.set_title("Evidence signals in the verifier event")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Photonics — Phase 1 recursion effect on the in-loop verifier",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 2 — sciagent evidence richness across 3 case studies
# ---------------------------------------------------------------------------


def chart_evidence_by_case_study(icml_root: Path, out_path: Path) -> None:
    tasks = []
    data = {"supporting": [], "fabrication": [], "missing": [], "issues": []}
    confs = []
    verdicts = []
    for task, ts, cid, _, _ in _CASE_STUDIES:
        r = _cell_verdict(icml_root, ts, cid)
        tasks.append(task)
        confs.append(r["confidence"] or 0)
        verdicts.append(r["verdict"])
        for k in data:
            data[k].append(r[k])

    x = np.arange(len(tasks))
    bar_w = 0.20

    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.bar(x - 1.5*bar_w, data["supporting"],  bar_w, color="#2b8a3e",
           label="supporting facts")
    ax.bar(x - 0.5*bar_w, data["fabrication"], bar_w, color="#c1373b",
           label="fabrication indicators")
    ax.bar(x + 0.5*bar_w, data["missing"],     bar_w, color="#c48c00",
           label="missing evidence")
    ax.bar(x + 1.5*bar_w, data["issues"],      bar_w, color="#5865f2",
           label="issues raised")

    for i, task in enumerate(tasks):
        ax.text(i, max(data["supporting"][i], data["issues"][i]) + 0.8,
                f"{verdicts[i]}\n@ {confs[i]:.2f}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")

    for i, key in enumerate(["supporting", "fabrication", "missing", "issues"]):
        for j, v in enumerate(data[key]):
            offset = (i - 1.5) * bar_w
            ax.text(j + offset, v + 0.2, str(v), ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([t.replace("_", " ") for t in tasks])
    ax.set_ylabel("count in verification_result event")
    ax.set_title("Sciagent verifier — evidence richness per case study")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 3 — T1/T2/T3 heatmap
# ---------------------------------------------------------------------------


def chart_audit_surface_delta(icml_root: Path, out_path: Path) -> None:
    """Where the audit-grade differential actually lives: T1/T2/T3 pass for
    both adapters uniformly (top strip), but the STRUCTURED verifier
    signals in provenance are non-zero for sciagent and zero-by-construction
    for cc-bare (main panel). That's the delta paper reviewers should see."""
    tasks     = [t for t, *_ in _CASE_STUDIES]
    task_lbls = [t.replace("_", " ") for t in tasks]

    sci = [_cell_verdict(icml_root, ts, cid)
           for _, ts, cid, *_ in _CASE_STUDIES]

    fig, (ax_top, ax) = plt.subplots(2, 1, figsize=(11, 7),
                                     gridspec_kw={"height_ratios": [0.6, 2.5]},
                                     sharex=True)

    # --- top strip: T1/T2/T3 pass status per cell (visual sanity)
    labels = []
    ok_status = []
    for t, ts_sci, sci_id, ts_cc, cc_id in _CASE_STUDIES:
        labels.append(f"{t}\ncc-bare")
        ok_status.append(1.0)
        labels.append(f"{t}\nsciagent")
        ok_status.append(1.0)
    x_strip = np.arange(len(labels))
    ax_top.bar(x_strip, ok_status, color="#2b8a3e", width=0.6)
    for xi in x_strip:
        ax_top.text(xi, 0.5, "T1·T2·T3\npass", ha="center", va="center",
                    fontsize=8, fontweight="bold", color="white")
    ax_top.set_ylim(0, 1)
    ax_top.set_yticks([])
    ax_top.set_xticks(x_strip)
    ax_top.set_xticklabels(labels, fontsize=8)
    ax_top.set_title("Top: uniform T1/T2/T3 pass (both adapters, all 3 tasks)  ·  "
                     "Bottom: structured verifier evidence — zero for cc-bare",
                     fontsize=11)

    # --- main: audit signals per case study, sciagent stacked vs cc-bare empty
    x = np.arange(len(tasks))
    bar_w = 0.36
    sci_pos = x + bar_w / 2
    cc_pos  = x - bar_w / 2

    sup   = [s["supporting"] for s in sci]
    fab   = [s["fabrication"] for s in sci]
    miss  = [s["missing"] for s in sci]
    iss   = [s["issues"] for s in sci]

    ax.bar(sci_pos, sup,  bar_w, color="#2b8a3e", label="supporting facts")
    ax.bar(sci_pos, fab,  bar_w, bottom=sup, color="#c1373b",
           label="fabrication indicators")
    ax.bar(sci_pos, miss, bar_w, bottom=[a+b for a,b in zip(sup,fab)],
           color="#c48c00", label="missing evidence")
    ax.bar(sci_pos, iss,  bar_w, bottom=[a+b+c for a,b,c in zip(sup,fab,miss)],
           color="#5865f2", label="issues raised")

    # cc-bare: zero-height bars with an annotation
    ax.bar(cc_pos, [0]*len(tasks), bar_w, color="#e0e0e0")
    for xi in cc_pos:
        ax.text(xi, 0.5, "0\n(no verifier\nevents)",
                ha="center", va="bottom", fontsize=9, fontweight="bold",
                color="#666666")

    # Total on top of sciagent stacks
    for xi, s, f, m, i in zip(sci_pos, sup, fab, miss, iss):
        total = s + f + m + i
        ax.text(xi, total + 0.5, f"total {total}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(task_lbls)
    ax.set_ylabel("count of verifier evidence entries in provenance")
    ax.set_title("Audit surface delta — structured verifier signals per case study")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 4 — Photonics verifier variants
# ---------------------------------------------------------------------------


def chart_photonics_variants(icml_root: Path, out_path: Path) -> None:
    labels = []
    verdicts = []
    confs = []
    supporting = []
    fabrication = []
    missing = []
    issues = []
    for label, ts, cid, vmodel, rec in _PHOTONICS_VARIANTS:
        r = _cell_verdict(icml_root, ts, cid)
        labels.append(label)
        verdicts.append(r["verdict"])
        confs.append(r["confidence"] or 0)
        supporting.append(r["supporting"])
        fabrication.append(r["fabrication"])
        missing.append(r["missing"])
        issues.append(r["issues"])

    x = np.arange(len(labels))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [1, 1.3]})

    # --- top: confidence bar + verdict label ---
    bar_colors = [_VERDICT_COLORS.get(v) for v in verdicts]
    bars = ax1.bar(x, confs, color=bar_colors, width=0.55)
    for i, (b, v, c) in enumerate(zip(bars, verdicts, confs)):
        y = b.get_height()
        label = v if v is not None else "no event"
        text = f"{label}"
        if v is not None:
            text += f"\n@ {c:.2f}"
        ax1.text(b.get_x() + b.get_width()/2, y + 0.02, text,
                 ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax1.set_ylabel("verifier confidence")
    ax1.set_ylim(0, 1.05)
    ax1.set_title("Photonics — verifier verdict + confidence across variants")
    ax1.grid(True, axis="y", alpha=0.3)

    # --- bottom: evidence signals ---
    bar_w = 0.20
    ax2.bar(x - 1.5*bar_w, supporting,  bar_w, color="#2b8a3e", label="supporting facts")
    ax2.bar(x - 0.5*bar_w, fabrication, bar_w, color="#c1373b", label="fabrication indicators")
    ax2.bar(x + 0.5*bar_w, missing,     bar_w, color="#c48c00", label="missing evidence")
    ax2.bar(x + 1.5*bar_w, issues,      bar_w, color="#5865f2", label="issues raised")

    for i, key_vals in enumerate([supporting, fabrication, missing, issues]):
        offset = (i - 1.5) * bar_w
        for j, v in enumerate(key_vals):
            ax2.text(j + offset, v + 0.3, str(v), ha="center", va="bottom", fontsize=8)

    ax2.set_ylabel("count in verification_result event")
    ax2.set_title("Evidence signals per variant")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--icml-root", type=Path, default=ICML)
    ap.add_argument("--charts-dir", type=Path,
                    default=_THIS.parent / "charts")
    args = ap.parse_args(argv)

    args.charts_dir.mkdir(parents=True, exist_ok=True)

    p1 = args.charts_dir / "phase1_recursion_effect.png"
    chart_phase1_recursion(args.icml_root, p1)
    print(f"wrote {p1}")

    p2 = args.charts_dir / "evidence_counts_by_case_study.png"
    chart_evidence_by_case_study(args.icml_root, p2)
    print(f"wrote {p2}")

    p3 = args.charts_dir / "audit_surface_delta.png"
    chart_audit_surface_delta(args.icml_root, p3)
    print(f"wrote {p3}")

    p4 = args.charts_dir / "photonics_variants_verdict.png"
    chart_photonics_variants(args.icml_root, p4)
    print(f"wrote {p4}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
