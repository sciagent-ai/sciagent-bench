# Task vs verification cost — summary

Companion to `task_vs_verification.md`. Paper-ready narrative: what the
split means, what the numbers show, and the three charts under
`charts/`.

## What the split means

For every sciagent cell we separate two disjoint cost bins:

- **task cost** — parent session + every child subagent that isn't the
  verifier (research / compute / analyze / plan / …) + cluster compute
  cost from `sky.cost_report()` + storage.
- **verification cost** — the verifier subagent's own session. Detected
  as the orphan session (not referenced by any parent
  `subagent_completed` event) that ends within 5 min of the parent's
  `verification_result` event and uses `file_ops` to open logs.

cc-bare cells have **$0.00** verification cost by construction — no
in-loop verifier.

## Cross-adapter — 3 tasks × 2 adapters

| task | condition | task LLM $ | task compute $ | verifier LLM $ | total $ | verifier % |
|:---|:---|---:|---:|---:|---:|---:|
| photonics | cc-bare | 6.70 | 0.00 | 0.00 | 6.70 | 0.0% |
| photonics | sciagent-verifier-on-default | 9.83 | 0.26 | **0.45** | 10.53 | **4.2%** |
| brca1 | cc-bare | 0.32 | 0.00 | 0.00 | 0.32 | 0.0% |
| brca1 | sciagent-verifier-on-default | 1.55 | 0.03 | **0.17** | 1.75 | **9.9%** |
| cfd_fig3_kde | cc-bare | 7.31 | 0.00 | 0.00 | 7.31 | 0.0% |
| cfd_fig3_kde | sciagent-verifier-on-default | 4.87 | 0.21 | **0.09** | 5.17 | **1.7%** |

**Reading**: verification is a small fraction of total cost —
**1.7 – 9.9%** across the three case studies. Sciagent is not
uniformly more expensive than cc-bare either: for photonics it's ~1.6×
cc-bare, for brca1 it's ~5.5×, but for cfd_fig3_kde sciagent is
**cheaper** ($5.17 vs $7.31). The cfd cc-bare cell burned $7.31 in a
tight shell-loop pattern (154 Bash calls in 45s wall) — a Claude Code
efficiency anomaly worth noting separately.

## Photonics variants — verification cost is roughly constant

| variant | task LLM $ | task compute $ | verifier LLM $ | total $ | verifier % |
|:---|---:|---:|---:|---:|---:|
| sciagent-verifier-on-default (recursive) | 9.83 | 0.26 | **0.45** | 10.53 | **4.2%** |
| sciagent-no-recursion (legacy) | 4.45 | 0.27 | **0.48** | 5.19 | **9.2%** |
| sciagent-crossverifier (openai o4-mini) | 5.05 | 0.52 | **0.44** | 6.00 | **7.3%** |
| sciagent-verifier-off (control) | 6.97 | 0.77 | 0.00 | 7.74 | 0.0% |
| cc-bare | 6.70 | 0.00 | 0.00 | 6.70 | 0.0% |

**Reading**: three notable things.

1. **Verification cost is stable (~$0.44)** across all three variants
   that have a verifier — regardless of whether recursion is on/off or
   which verifier model was used. Turning recursion ON did NOT
   materially change verifier cost (0.45 vs 0.48), even though it
   flipped the verdict from `insufficient` → `verified`. The verifier
   reads more evidence but doesn't pay meaningfully more for it.
2. **Task cost varies significantly** across variants — the same
   photonics task ran for as little as $4.45 (no-recursion) and as
   much as $9.83 (recursive default). That's trajectory stochasticity,
   not a verifier effect. The recursive-default run's parent + subagent
   trajectory happened to spend twice what the no-recursion run did.
3. **Verifier-off has no ~$0.44 verifier line**, saving that fraction,
   but its compute cost is the highest of the four ($0.77 vs 0.26–0.52)
   — because with no gate at the end, sciagent kept the cluster
   running longer. That's a real trade-off: skip the LLM verifier fee,
   pay it back in cluster time.

## Per-subagent breakdown (sciagent-verifier-on-default only)

**photonics** — task LLM $ 9.83 breaks down as:

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 1.87 | 823 K | 22 K |
| child `research/f8f6fcc4f920` | 0.10 | 36 K | 0 K |
| child `research/ac76c4bd09e6` | 3.22 | 1,017 K | 55 K |
| child `compute/7dade9fe2208` | **4.21** | **2,820 K** | 76 K |
| child `analyze/ffe28342fc1c` | 0.44 | 286 K | 5 K |
| **verifier** `5ca244d29b77` | **0.45** | 149 K | 6 K |

Compute subagent dominates ($4.21 = 43% of task LLM, 44% of task tokens
in). Verifier is 4.5% of task LLM — same order as `research/f8f6fcc4f920`
(which was one of two research sub-calls).

**brca1_fitness_structure** — task LLM $ 1.55:

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 0.39 | 253 K | 4 K |
| child `compute/352545f3ca57` | **1.16** | **1,087 K** | 13 K |
| **verifier** `f7f3ea5e6d20` | **0.17** | 67 K | 2 K |

**cfd_fig3_kde** — task LLM $ 4.87:

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 2.50 | 1,145 K | 19 K |
| child `compute/b48a7be4742c` | **2.37** | **2,827 K** | 16 K |
| **verifier** `00017833b2c9` | **0.09** | 34 K | 0 K |

## Charts

- **`charts/cc_vs_sciagent_by_task.png`** — cc-bare (single grey bar)
  vs sciagent (blue task + orange verification stacked). Shows that
  verification is a small tip on top of task cost across all three
  case studies.
- **`charts/photonics_variants_split.png`** — 5 photonics variants
  side-by-side, each split into task LLM, task compute, task storage,
  verification LLM. Makes the "verifier-off saves $0.44 but pays
  $0.25 more in compute" trade visible.
- **`charts/cost_types_by_cell.png`** — grouped bars per cell (task
  LLM / task compute / task storage / verifier LLM). Best for the
  paper's efficiency table.

## Files in this folder

- `task_vs_verification_summary.md` — this file (paper-ready narrative)
- `task_vs_verification.md` — full per-cell tables + method notes
- `task_vs_verification.csv` — machine-readable numbers
- `analyze_task_vs_verification.py` — the analyzer
- `charts/*.png` — matplotlib output
