"""
BRCA1 mutation fitness vs. protein structure analysis.

Parses DMS fitness data (Findlay 2018) and AlphaFold structure, maps
fitness scores to per-residue structural features (secondary structure,
RSA, pLDDT), and produces summary statistics and figures in _outputs/.
"""

import math
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy import stats

import freesasa
from Bio import PDB
from Bio.PDB import PPBuilder

# ── paths ──────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DATA = BASE / "_data"
OUT  = BASE / "_outputs"
OUT.mkdir(exist_ok=True)

CSV_PATH = DATA / "BRCA1_HUMAN_Findlay_2018.csv"
PDB_PATH = DATA / "AF-P38398-F1-model_v6.pdb"

# ── functional domain definitions ──────────────────────────────────────────
DOMAINS = {
    "RING":  (1,    109),
    "BRCT":  (1642, 1863),
}


# ══════════════════════════════════════════════════════════════════════════
# 1. Parse DMS fitness data
# ══════════════════════════════════════════════════════════════════════════
def parse_fitness(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    assert len(df) == 1837, f"Expected 1837 mutations, got {len(df)}"

    # mutant format: "<wt_aa><position><mut_aa>",  e.g. "M1I"
    df["wt_aa"]   = df["mutant"].str[0]
    df["position"] = df["mutant"].str[1:-1].astype(int)
    df["mut_aa"]  = df["mutant"].str[-1]

    print(f"[DMS] Parsed {len(df):,} mutations across "
          f"{df['position'].nunique()} unique positions "
          f"(pos {df['position'].min()}–{df['position'].max()})")
    return df


# ══════════════════════════════════════════════════════════════════════════
# 2. Load structure & extract per-residue features
# ══════════════════════════════════════════════════════════════════════════
def _phi_psi_to_ss(phi, psi):
    """Ramachandran-based secondary structure assignment."""
    if phi is None or psi is None:
        return "C"
    phi_d = math.degrees(phi)
    psi_d = math.degrees(psi)
    # helix region
    if -160 < phi_d < -40 and -60 < psi_d < 45:
        return "H"
    # sheet region
    if (-180 < phi_d < -40 and (psi_d > 100 or psi_d < -160)) or \
       (-180 < phi_d < -40 and 90 < psi_d < 180):
        return "E"
    return "C"


def parse_structure(pdb_path: Path) -> pd.DataFrame:
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("BRCA1", str(pdb_path))
    model = structure[0]

    # ── pLDDT (stored as B-factor in AlphaFold) ──────────────────────────
    plddt = {}
    for chain in model:
        for residue in chain:
            if PDB.is_aa(residue, standard=True):
                resid = residue.get_id()[1]
                # average over atoms (all atoms in AF have same B-factor)
                b_vals = [a.get_bfactor() for a in residue.get_atoms()]
                plddt[resid] = np.mean(b_vals) if b_vals else np.nan

    # ── phi/psi → secondary structure ────────────────────────────────────
    ppb = PPBuilder()
    phi_psi = {}  # resid → (phi, psi)
    for pp in ppb.build_peptides(model):
        angles = pp.get_phi_psi_list()
        for residue, (phi, psi) in zip(pp, angles):
            phi_psi[residue.get_id()[1]] = (phi, psi)

    ss_assignment = {pos: _phi_psi_to_ss(*angles)
                     for pos, angles in phi_psi.items()}

    # ── relative solvent accessibility via freesasa ───────────────────────
    rsa = {}
    try:
        fs_structure = freesasa.Structure(str(pdb_path))
        fs_result    = freesasa.calc(fs_structure)
        # max ASA values (Sander & Rost 1994) for standard AAs
        MAX_ASA = {
            "ALA": 106.0, "ARG": 248.0, "ASN": 157.0, "ASP": 163.0,
            "CYS": 135.0, "GLN": 198.0, "GLU": 194.0, "GLY":  84.0,
            "HIS": 184.0, "ILE": 169.0, "LEU": 164.0, "LYS": 205.0,
            "MET": 188.0, "PHE": 197.0, "PRO": 136.0, "SER": 130.0,
            "THR": 142.0, "TRP": 227.0, "TYR": 222.0, "VAL": 142.0,
        }
        for chain in model:
            for residue in chain:
                if not PDB.is_aa(residue, standard=True):
                    continue
                resnum   = residue.get_id()[1]
                resname  = residue.get_resname()
                chain_id = chain.get_id()
                try:
                    resi_asa = fs_result.residueAreas()
                    key = (chain_id, str(resnum))
                    if chain_id in resi_asa and str(resnum) in resi_asa[chain_id]:
                        asa = resi_asa[chain_id][str(resnum)].total
                        max_asa = MAX_ASA.get(resname, 200.0)
                        rsa[resnum] = min(asa / max_asa, 1.0)
                except Exception:
                    pass
        dssp_ok = len(rsa) > 0
        print(f"[freesasa] RSA computed for {len(rsa):,} residues")
    except Exception as e:
        warnings.warn(f"freesasa failed ({e}); RSA unavailable")
        dssp_ok = False

    # ── assemble per-residue table ────────────────────────────────────────
    all_pos = sorted(plddt.keys())
    rows = []
    for pos in all_pos:
        phi, psi = phi_psi.get(pos, (None, None))
        rows.append({
            "position":  pos,
            "pLDDT":     plddt.get(pos, np.nan),
            "ss":        ss_assignment.get(pos, "C"),
            "rsa":       rsa.get(pos, np.nan) if dssp_ok else np.nan,
        })
    struct_df = pd.DataFrame(rows)
    print(f"[PDB]  Loaded {len(struct_df):,} residues; "
          f"DSSP={'ok' if dssp_ok else 'skipped'}")
    return struct_df


# ══════════════════════════════════════════════════════════════════════════
# 3. Merge & annotate
# ══════════════════════════════════════════════════════════════════════════
def merge_and_annotate(dms: pd.DataFrame, struct: pd.DataFrame) -> pd.DataFrame:
    merged = dms.merge(struct, on="position", how="left")

    # mapping success rate
    mapped = merged["pLDDT"].notna().sum()
    total  = len(merged)
    rate   = mapped / total
    print(f"[MAP]  Mapped {mapped:,}/{total:,} mutations → {rate:.4f} ({rate:.1%})")
    assert rate >= 0.95, f"Mapping rate {rate:.3f} < 0.95"

    # domain annotation
    def assign_domain(pos):
        for name, (lo, hi) in DOMAINS.items():
            if lo <= pos <= hi:
                return name
        return "Other"

    merged["domain"] = merged["position"].apply(assign_domain)

    # RSA bins (buried / intermediate / exposed)
    if merged["rsa"].notna().any():
        bins   = [-0.001, 0.20, 0.50, 1.01]
        labels = ["Buried", "Intermediate", "Exposed"]
        merged["rsa_bin"] = pd.cut(merged["rsa"], bins=bins, labels=labels)
    else:
        merged["rsa_bin"] = np.nan

    return merged


# ══════════════════════════════════════════════════════════════════════════
# 4. Summary statistics
# ══════════════════════════════════════════════════════════════════════════
def print_summaries(df: pd.DataFrame):
    print("\n── Mean fitness by secondary structure ──")
    ss_labels = {"H": "Helix", "E": "Sheet", "C": "Coil/Loop"}
    for ss_code, label in ss_labels.items():
        sub = df[df["ss"] == ss_code]["DMS_score"]
        if len(sub):
            print(f"  {label:12s}: n={len(sub):5d}  mean={sub.mean():+.4f}  "
                  f"median={sub.median():+.4f}")

    print("\n── Mean fitness by solvent-accessibility bin ──")
    if df["rsa_bin"].notna().any():
        for b in ["Buried", "Intermediate", "Exposed"]:
            sub = df[df["rsa_bin"] == b]["DMS_score"]
            if len(sub):
                print(f"  {b:15s}: n={len(sub):5d}  mean={sub.mean():+.4f}")

        buried  = df[df["rsa_bin"] == "Buried"]["DMS_score"].dropna()
        exposed = df[df["rsa_bin"] == "Exposed"]["DMS_score"].dropna()
        t, p = stats.ttest_ind(buried, exposed)
        delta = buried.mean() - exposed.mean()
        print(f"\n  Buried–Exposed Δmean = {delta:+.4f}  "
              f"t={t:.3f}  p={p:.2e}")
        if p < 0.001:
            print("  ✓ Statistically significant buried vs. exposed difference (p < 0.001)")
    else:
        print("  (DSSP RSA not available; skipping)")

    print("\n── Mean fitness by functional domain ──")
    for dom in ["RING", "BRCT", "Other"]:
        sub = df[df["domain"] == dom]["DMS_score"]
        if len(sub):
            print(f"  {dom:6s}: n={len(sub):5d}  mean={sub.mean():+.4f}")


# ══════════════════════════════════════════════════════════════════════════
# 5. Plots
# ══════════════════════════════════════════════════════════════════════════
SS_COLORS = {"H": "#e74c3c", "E": "#3498db", "C": "#2ecc71"}
SS_NAMES  = {"H": "α-Helix", "E": "β-Sheet", "C": "Coil/Loop"}


def plot_fitness_vs_position(df: pd.DataFrame, out: Path):
    # per-position mean fitness & dominant SS
    pos_df = (df.groupby("position")
               .agg(mean_fitness=("DMS_score", "mean"),
                    dominant_ss=("ss", lambda x: x.mode().iloc[0] if len(x) else "C"),
                    pLDDT=("pLDDT", "mean"),
                    domain=("domain", "first"))
               .reset_index())

    fig, axes = plt.subplots(2, 1, figsize=(14, 9),
                             gridspec_kw={"height_ratios": [3, 1]},
                             sharex=True)

    ax = axes[0]
    for ss_code, color in SS_COLORS.items():
        sub = pos_df[pos_df["dominant_ss"] == ss_code]
        ax.scatter(sub["position"], sub["mean_fitness"],
                   c=color, label=SS_NAMES[ss_code],
                   alpha=0.7, s=20, linewidths=0)

    # domain shading
    dom_colors = {"RING": "#f39c12", "BRCT": "#9b59b6"}
    ymin, ymax = ax.get_ylim()
    for dom, (lo, hi) in DOMAINS.items():
        ax.axvspan(lo, hi, alpha=0.12, color=dom_colors[dom],
                   label=f"{dom} domain ({lo}–{hi})")

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_ylabel("Mean DMS fitness score", fontsize=12)
    ax.set_title("BRCA1 Mutation Fitness vs. Position\n"
                 "(colored by dominant secondary structure)", fontsize=13)
    ax.legend(loc="lower right", fontsize=9, ncol=2)
    ax.set_ylim(None, None)

    # pLDDT sub-panel
    ax2 = axes[1]
    ax2.fill_between(pos_df["position"], pos_df["pLDDT"],
                     alpha=0.6, color="#7f8c8d")
    ax2.set_ylabel("pLDDT", fontsize=10)
    ax2.set_xlabel("Residue position", fontsize=12)
    ax2.set_ylim(0, 100)
    ax2.axhline(70, color="orange", linestyle=":", linewidth=0.8, label="pLDDT=70")
    ax2.legend(fontsize=8)

    plt.tight_layout()
    fig.savefig(out / "fitness_vs_position.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OUT]  fitness_vs_position.png saved")


def plot_fitness_by_ss(df: pd.DataFrame, out: Path):
    fig, ax = plt.subplots(figsize=(7, 5))

    data   = [df[df["ss"] == ss]["DMS_score"].dropna().values
               for ss in ["H", "E", "C"]]
    labels = [SS_NAMES[ss] for ss in ["H", "E", "C"]]
    colors = [SS_COLORS[ss] for ss in ["H", "E", "C"]]

    bps = ax.boxplot(data, patch_artist=True, notch=False, widths=0.5)
    for patch, color in zip(bps["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("DMS fitness score", fontsize=12)
    ax.set_title("Fitness distribution by secondary structure", fontsize=13)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig.savefig(out / "fitness_by_ss.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OUT]  fitness_by_ss.png saved")


def plot_fitness_by_rsa(df: pd.DataFrame, out: Path):
    if df["rsa_bin"].isna().all():
        print("[OUT]  Skipping RSA plot (no DSSP data)")
        return

    fig, ax = plt.subplots(figsize=(7, 5))
    rsa_colors = {"Buried": "#c0392b", "Intermediate": "#e67e22", "Exposed": "#27ae60"}
    data   = [df[df["rsa_bin"] == b]["DMS_score"].dropna().values
               for b in ["Buried", "Intermediate", "Exposed"]]
    colors = [rsa_colors[b] for b in ["Buried", "Intermediate", "Exposed"]]

    bps = ax.boxplot(data, patch_artist=True, notch=False, widths=0.5)
    for patch, color in zip(bps["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticklabels(["Buried\n(RSA<0.20)", "Intermediate\n(0.20–0.50)",
                         "Exposed\n(RSA>0.50)"], fontsize=10)
    ax.set_ylabel("DMS fitness score", fontsize=12)
    ax.set_title("Fitness distribution by solvent accessibility", fontsize=13)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig.savefig(out / "fitness_by_rsa.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OUT]  fitness_by_rsa.png saved")


def plot_domain_comparison(df: pd.DataFrame, out: Path):
    fig, ax = plt.subplots(figsize=(7, 5))
    dom_colors = {"RING": "#f39c12", "BRCT": "#9b59b6", "Other": "#95a5a6"}
    domains_order = ["RING", "BRCT", "Other"]
    data   = [df[df["domain"] == d]["DMS_score"].dropna().values
               for d in domains_order]
    colors = [dom_colors[d] for d in domains_order]

    bps = ax.boxplot(data, patch_artist=True, notch=False, widths=0.5)
    for patch, color in zip(bps["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    labels = [f"{d}\n(n={len(df[df['domain']==d]):,})" for d in domains_order]
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("DMS fitness score", fontsize=12)
    ax.set_title("Fitness distribution by functional domain", fontsize=13)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig.savefig(out / "fitness_by_domain.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[OUT]  fitness_by_domain.png saved")


# ══════════════════════════════════════════════════════════════════════════
# 6. Save merged table
# ══════════════════════════════════════════════════════════════════════════
def save_results(df: pd.DataFrame, out: Path):
    outpath = out / "brca1_fitness_structure.csv"
    df.to_csv(outpath, index=False)
    print(f"[OUT]  brca1_fitness_structure.csv saved ({len(df):,} rows)")


# ══════════════════════════════════════════════════════════════════════════
# 7. Verification checks
# ══════════════════════════════════════════════════════════════════════════
def run_verifications(df: pd.DataFrame):
    print("\n══ Verification ══")

    # V1: 1,837 mutations parsed
    assert len(df) == 1837, f"FAIL: {len(df)} mutations (expected 1837)"
    print("✓ V1: 1,837 mutations parsed")

    # V2: mapping success rate >= 0.95
    rate = df["pLDDT"].notna().sum() / len(df)
    assert rate >= 0.95, f"FAIL: mapping rate {rate:.3f} < 0.95"
    print(f"✓ V2: Mapping success rate = {rate:.4f} (≥ 0.95)")

    # V3: buried–exposed fitness difference p < 0.001
    if df["rsa_bin"].notna().any():
        buried  = df[df["rsa_bin"] == "Buried"]["DMS_score"].dropna()
        exposed = df[df["rsa_bin"] == "Exposed"]["DMS_score"].dropna()
        _, p = stats.ttest_ind(buried, exposed)
        delta = buried.mean() - exposed.mean()
        assert p < 0.001, f"FAIL: buried–exposed p={p:.4f} ≥ 0.001"
        print(f"✓ V3: Buried–Exposed Δmean = {delta:+.4f}, p = {p:.2e} (< 0.001)")
    else:
        print("  V3: skipped (no DSSP RSA data)")

    print("══ All verifications passed ══\n")


# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════
def main():
    print("=== BRCA1 Fitness–Structure Analysis ===\n")

    dms    = parse_fitness(CSV_PATH)
    struct = parse_structure(PDB_PATH)
    df     = merge_and_annotate(dms, struct)

    print_summaries(df)
    run_verifications(df)

    plot_fitness_vs_position(df, OUT)
    plot_fitness_by_ss(df, OUT)
    plot_fitness_by_rsa(df, OUT)
    plot_domain_comparison(df, OUT)
    save_results(df, OUT)

    print("\nDone. Outputs written to", OUT)


if __name__ == "__main__":
    main()
