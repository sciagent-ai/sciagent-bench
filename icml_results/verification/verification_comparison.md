# Verification comparison — cc-bare vs sciagent (T3 axis)

Deterministic Correctness check (does the claim satisfy the paper's numeric threshold?) applied uniformly to both adapters, joined with sciagent's own in-loop LLM-verifier verdict (which cc-bare cells lack entirely). See `README.md` for the full method.

| task | condition | criterion | paper_value | claimed_value | passes_threshold | sci_verdict | sci_confidence | agreement |
|:---|:---|:---|---:|---:|---:|:---|---:|:---|
| photonics | cc-bare | ≥ 0.25 | 0.253 | 0.2504 | pass | — | — | — |
| photonics | sciagent-verifier-on-default | ≥ 0.25 | 0.253 | 0.2509 | pass | verified | 0.75 | yes |
| brca1_fitness_structure | cc-bare | ≥ 0.95 | 1.0 | — | — | — | — | — |
| brca1_fitness_structure | sciagent-verifier-on-default | ≥ 0.95 | 1.0 | — | — | verified | 0.78 | — |
| cfd_fig3_kde | cc-bare | in [294.0, 298.0] | 296.2 | 295.333 | pass | — | — | — |
| cfd_fig3_kde | sciagent-verifier-on-default | in [294.0, 298.0] | 296.2 | 296.2092 | pass | verified | 0.91 | yes |

## Rows awaiting hand-filled `claimed_value`

- **brca1_fitness_structure / cc-bare** — HAND-FILL: mapping_success_rate not stated in result.txt directly; check summary.json in ./project/_outputs/ or task's mapping section
- **brca1_fitness_structure / sciagent-verifier-on-default** — HAND-FILL: same — check ./project/_outputs/summary.json for the actual number

Edit `claim_values.csv` in this folder, then rerun `verify_and_compare.py`.

