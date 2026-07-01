# Task vs verification cost — synthesis

Tight, paper-ready synthesis of the three findings from the cost split.
For the longer paper-ready narrative see `task_vs_verification_summary.md`;
for full tables see `task_vs_verification.md`.

## Folder layout

```
efficiency/
├── analyze_task_vs_verification.py   ← data extractor (25 KB)
├── make_case_study_diagrams.py       ← 6-panel diagram maker
├── task_vs_verification.md           ← full per-cell tables
├── task_vs_verification.csv          ← machine-readable
├── task_vs_verification_summary.md   ← paper-ready narrative (5.7 KB)
├── task_vs_verification_synthesis.md ← this file
└── charts/
    ├── photonics_efficiency.png                 ← per-case-study 6-panel
    ├── brca1_fitness_structure_efficiency.png   ← per-case-study 6-panel
    ├── cfd_fig3_kde_efficiency.png              ← per-case-study 6-panel
    ├── summary_by_task.png                      ← compact 3-task cost row
    └── photonics_variants_split.png             ← photonics variants (verifier configs)
```

Each per-case-study 6-panel figure shows: wall-clock time, cost
(LLM + compute + verifier LLM stacked), iterations (with subagent
breakdown), tokens (stacked by source), tool calls, and remote compute
jobs. Same layout as the earlier `results/…/performance/comparison.png`
photonics diagram, generalized across the three case studies with the
verifier called out as its own segment.

## Three findings from the split

### 1. Verifier is a small tip on total cost

1.7% (cfd_fig3_kde) to 9.9% (brca1) across the three case studies.
Sciagent's audit-grade property isn't paid for with a fat verification
bill.

### 2. Photonics variants: verification cost is stable (~$0.44) regardless of recursion or verifier model

| variant | task LLM | task compute | verifier LLM | total | verif % |
|:---|---:|---:|---:|---:|---:|
| verifier-on-default (recursive) | 9.83 | 0.26 | 0.45 | 10.53 | 4.2% |
| no-recursion (legacy)           | 4.45 | 0.27 | 0.48 |  5.19 | 9.2% |
| crossverifier (o4-mini)         | 5.05 | 0.52 | 0.44 |  6.00 | 7.3% |
| verifier-off (control)          | 6.97 | 0.77 | 0.00 |  7.74 | 0.0% |
| cc-bare                         | 6.70 | 0.00 | 0.00 |  6.70 | 0.0% |

Recursion flipped the verdict but did **NOT** flip the verifier cost —
same ~$0.44. So the Phase 1 recursion fix is essentially free from a
verifier-cost standpoint.

### 3. Verifier-off trades LLM cost for compute cost

With no gate at end, sciagent kept the cluster running longer ($0.77
compute vs 0.26–0.52 for the others). So skipping the $0.44 verifier
fee doesn't net a $0.44 saving — it nets ~$0.20.

## Per-subagent decomposition

The compute subagent is the dominant cost in all three tasks:

- photonics: $4.21 = **43%** of task LLM
- brca1:     $1.16 = **75%** of task LLM
- cfd:       $2.37 = **49%** of task LLM

Verifier LLM is small compared to any single research/compute child.

## Detected verifier session IDs (for reproducibility)

- photonics    → `5ca244d29b77`
- brca1        → `f7f3ea5e6d20`
- cfd_fig3_kde → `00017833b2c9`

All three sit **orphaned** in `~/.sciagent/sessions/` — spawned by the
orchestrator's `_run_llm_verification_gate` rather than by the agent's
subagent loop, which is why they don't appear as `subagent_completed`
events in the parent log. The detector logic (orphan + `file_ops`
heavy + ends within 5 min of the parent's `verification_result` event)
is documented in the analyzer script for future runs.
