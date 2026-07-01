"""
BRCA1 DMS Fitness vs Structure Correlation Analysis
Input data: read from _data/ (relative to CWD = sky_workdir)
Outputs:    written to /workspace/outputs/ (SkyPilot workspace bucket)
"""
import os, re, json, math, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import mannwhitneyu
from Bio.PDB import PDBParser, PPBuilder, NeighborSearch

# ── Paths ─────────────────────────────────────────────────────────────────────
# Inputs are in _data/ relative to CWD (rsynced via workdir=)
CSV_PATH = "_data/BRCA1_HUMAN_Findlay_2018.csv"
PDB_PATH = "_data/AF-P38398-F1-model_v6.pdb"
# Outputs land in the workspace bucket so the validator can find them
OUT_DIR  = "/workspace/outputs"
os.makedirs(OUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Parse the CSV
# ─────────────────────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_PATH)
print(f"CSV rows loaded: {len(df)}")
assert len(df) == 1837, f"Expected 1837 rows, got {len(df)}"

def parse_mutation(mut_str):
    m = re.match(r'^([A-Z*])(\d+)([A-Z*])$', str(mut_str).strip())
    if m:
        return m.group(1), int(m.group(2)), m.group(3)
    return None, None, None

df['wt_aa'], df['position'], df['mut_aa'] = zip(*df['mutant'].apply(parse_mutation))
df = df.dropna(subset=['position'])
df['position'] = df['position'].astype(int)
print(f"Parsed {len(df)} mutations with valid positions.")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Load PDB and extract structural features
# ─────────────────────────────────────────────────────────────────────────────
parser = PDBParser(QUIET=True)
structure = parser.get_structure("BRCA1", PDB_PATH)
model = structure[0]
chain = model['A']

# CA atoms for NeighborSearch
ca_atoms = [res['CA'] for res in chain.get_residues()
            if res.id[0] == ' ' and 'CA' in res]
print(f"Total CA atoms in chain A: {len(ca_atoms)}")
ns = NeighborSearch(ca_atoms)

NEIGHBOR_CUTOFF  = 8.0
BURIED_THRESHOLD = 16   # >= 16 neighbors within 8Å → buried

# Phi/psi via PPBuilder
ppb = PPBuilder()
phi_psi_map = {}
for pp in ppb.build_peptides(chain, aa_only=True):
    for res, (phi, psi) in zip(pp, pp.get_phi_psi_list()):
        phi_psi_map[res.id[1]] = (phi, psi)

def classify_ss(phi, psi):
    if phi is None or psi is None:
        return 'coil'
    pd_ = math.degrees(phi)
    ps_ = math.degrees(psi)
    if -100 <= pd_ <= -40 and -70 <= ps_ <= -10:
        return 'helix'
    if -160 <= pd_ <= -100 and 100 <= ps_ <= 160:
        return 'sheet'
    return 'coil'

def classify_domain(pos):
    if 1 <= pos <= 109:      return 'RING'
    if 1642 <= pos <= 1863:  return 'BRCT'
    return 'Other'

residue_features = {}
for res in chain.get_residues():
    if res.id[0] != ' ' or 'CA' not in res:
        continue
    rid = res.id[1]
    plddt = res['CA'].get_bfactor()
    phi, psi = phi_psi_map.get(rid, (None, None))
    ss = classify_ss(phi, psi)
    neighbors = ns.search(res['CA'].coord, NEIGHBOR_CUTOFF)
    n_nb = len(neighbors) - 1   # exclude self
    accessibility = 'buried' if n_nb >= BURIED_THRESHOLD else 'exposed'
    residue_features[rid] = dict(res_id=rid, plddt=plddt, ss=ss,
                                  n_neighbors=n_nb, accessibility=accessibility,
                                  domain=classify_domain(rid))

print(f"Residues with structural features: {len(residue_features)}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Map fitness scores to structural positions
# ─────────────────────────────────────────────────────────────────────────────
df['has_structure'] = df['position'].apply(lambda p: p in residue_features)
n_mapped      = df['has_structure'].sum()
mapping_rate  = n_mapped / len(df)
print(f"Mapped {n_mapped}/{len(df)} mutations ({mapping_rate:.3f})")
assert mapping_rate >= 0.95, f"Mapping rate {mapping_rate:.3f} < 0.95"

df_mapped = df[df['has_structure']].copy()
feat_df   = pd.DataFrame.from_dict(residue_features, orient='index')
df_mapped = df_mapped.merge(feat_df, left_on='position', right_on='res_id', how='left')

# ─────────────────────────────────────────────────────────────────────────────
# 4. Mean fitness by group
# ─────────────────────────────────────────────────────────────────────────────
mean_by_ss            = df_mapped.groupby('ss')['DMS_score'].mean().to_dict()
mean_by_accessibility = df_mapped.groupby('accessibility')['DMS_score'].mean().to_dict()
mean_by_domain        = df_mapped.groupby('domain')['DMS_score'].mean().to_dict()

print("Mean fitness by SS:",            mean_by_ss)
print("Mean fitness by accessibility:", mean_by_accessibility)
print("Mean fitness by domain:",        mean_by_domain)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Mann-Whitney U: buried vs exposed
# ─────────────────────────────────────────────────────────────────────────────
buried_scores  = df_mapped[df_mapped['accessibility'] == 'buried']['DMS_score'].dropna()
exposed_scores = df_mapped[df_mapped['accessibility'] == 'exposed']['DMS_score'].dropna()
u_stat, p_val  = mannwhitneyu(buried_scores, exposed_scores, alternative='two-sided')
print(f"Mann-Whitney U: {u_stat:.2f}, p-value: {p_val:.6e}")
assert p_val < 0.001, f"p-value {p_val} >= 0.001"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Scatter plot
# ─────────────────────────────────────────────────────────────────────────────
color_map = {'helix': 'red', 'sheet': 'blue', 'coil': 'gray'}
fig, ax = plt.subplots(figsize=(16, 5))
for ss_type, color in color_map.items():
    subset = df_mapped[df_mapped['ss'] == ss_type]
    ax.scatter(subset['position'], subset['DMS_score'],
               c=color, s=5, alpha=0.5, label=ss_type.capitalize(), rasterized=True)
ax.axvspan(1,    109,  alpha=0.12, color='gold',  label='RING (1-109)')
ax.axvspan(1642, 1863, alpha=0.12, color='green', label='BRCT (1642-1863)')
ax.set_xlabel("Residue Position", fontsize=12)
ax.set_ylabel("DMS Fitness Score", fontsize=12)
ax.set_title("BRCA1 DMS Fitness vs Position", fontsize=14)
ax.legend(loc='upper right', fontsize=9, markerscale=2)
ax.set_xlim(0, df_mapped['position'].max() + 20)
plt.tight_layout()
plot_path = os.path.join(OUT_DIR, "fitness_vs_position.png")
plt.savefig(plot_path, dpi=300)
plt.close()
print(f"Saved plot: {plot_path}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Summary JSON
# ─────────────────────────────────────────────────────────────────────────────
summary = {
    "n_mutations": int(len(df_mapped)),
    "mapping_rate": float(mapping_rate),
    "mean_fitness_by_ss":            {k: float(v) for k, v in mean_by_ss.items()},
    "mean_fitness_by_accessibility": {k: float(v) for k, v in mean_by_accessibility.items()},
    "mean_fitness_by_domain":        {k: float(v) for k, v in mean_by_domain.items()},
    "buried_vs_exposed_pvalue": float(p_val),
    "buried_vs_exposed_U":      float(u_stat),
}
json_path = os.path.join(OUT_DIR, "summary.json")
with open(json_path, 'w') as f:
    json.dump(summary, f, indent=2)
print(f"Saved summary: {json_path}")
print(json.dumps(summary, indent=2))

# ─────────────────────────────────────────────────────────────────────────────
# 8. Mapped CSV
# ─────────────────────────────────────────────────────────────────────────────
out_cols = ['mutant', 'wt_aa', 'position', 'mut_aa', 'DMS_score', 'DMS_score_bin',
            'plddt', 'ss', 'n_neighbors', 'accessibility', 'domain']
out_cols = [c for c in out_cols if c in df_mapped.columns]
csv_path = os.path.join(OUT_DIR, "fitness_structure_mapped.csv")
df_mapped[out_cols].to_csv(csv_path, index=False)
print(f"Saved mapped CSV: {csv_path}")

print("\n=== BRCA1 Analysis Complete ===")
