# Cost split — task vs verification

Per cell we separate two disjoint cost bins:

- **task cost** — parent session + every subagent child session
  (research / compute / analyze / plan / …) plus compute/storage
  costs observed anywhere in the trajectory.
- **verification cost** — the verifier subagent's own session.
  This is the orphan session (not referenced by any parent
  `subagent_completed` event) that
  `TaskOrchestrator._run_llm_verification_gate` spawns at the end
  of the run. Detected by: not in child_ids, ends within 5 min of
  the parent's `verification_result` event, uses `file_ops` to
  open logs.

cc-bare cells have no in-loop verifier, so verification cost is
**$0.00** by construction — total = task cost.


## Cross-adapter cost split (3 tasks × 2 adapters)

| task | condition | task LLM $ | task compute $ | task storage $ | verifier LLM $ | total $ | verifier % of total |
|:---|:---|---:|---:|---:|---:|---:|---:|
| photonics | cc-bare | 6.7038 | 0.0000 | 0.0000 | 0.0000 | 6.7038 | 0.0% |
| photonics | sciagent-verifier-on-default | 9.8325 | 0.2551 | 0.0000 | 0.4454 | 10.5330 | 4.2% |
| brca1_fitness_structure | cc-bare | 0.3183 | 0.0000 | 0.0000 | 0.0000 | 0.3183 | 0.0% |
| brca1_fitness_structure | sciagent-verifier-on-default | 1.5457 | 0.0299 | 0.0000 | 0.1727 | 1.7483 | 9.9% |
| cfd_fig3_kde | cc-bare | 7.3094 | 0.0000 | 0.0000 | 0.0000 | 7.3094 | 0.0% |
| cfd_fig3_kde | sciagent-verifier-on-default | 4.8705 | 0.2119 | 0.0000 | 0.0894 | 5.1718 | 1.7% |

## Photonics variants — cost split

Same task (photonics), five sciagent + cc-bare variants. Isolates how the verifier configuration affects verification cost.

| variant | task LLM $ | task compute $ | task storage $ | verifier LLM $ | total $ | verifier % of total |
|:---|---:|---:|---:|---:|---:|---:|
| sciagent-verifier-on-default | 9.8325 | 0.2551 | 0.0000 | 0.4454 | 10.5330 | 4.2% |
| sciagent-no-recursion | 4.4485 | 0.2679 | 0.0000 | 0.4773 | 5.1937 | 9.2% |
| sciagent-crossverifier | 5.0477 | 0.5164 | 0.0000 | 0.4389 | 6.0030 | 7.3% |
| sciagent-verifier-off | 6.9730 | 0.7715 | 0.0000 | 0.0000 | 7.7445 | 0.0% |
| cc-bare | 6.7038 | 0.0000 | 0.0000 | 0.0000 | 6.7038 | 0.0% |

## Sciagent subagent breakdown (per role)

For each sciagent cell, break `task LLM $` into parent + per-child-subagent contributions. Verifier row is the detected orphan session.

### photonics — `sciagent-verifier-on-default`

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 1.8669 | 822,979 | 21,515 |
| child `research/f8f6fcc4f920` | 0.1013 | 35,534 | 360 |
| child `research/ac76c4bd09e6` | 3.2176 | 1,017,126 | 54,679 |
| child `compute/7dade9fe2208` | 4.2053 | 2,820,152 | 75,675 |
| child `analyze/ffe28342fc1c` | 0.4414 | 285,682 | 4,613 |
| **verifier** `5ca244d29b77` | **0.4454** | 149,089 | 5,709 |

### brca1_fitness_structure — `sciagent-verifier-on-default`

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 0.3894 | 252,838 | 3,789 |
| child `compute/352545f3ca57` | 1.1563 | 1,087,418 | 13,499 |
| **verifier** `f7f3ea5e6d20` | **0.1727** | 66,958 | 2,450 |

### cfd_fig3_kde — `sciagent-verifier-on-default`

| role | LLM $ | tokens in | tokens out |
|:---|---:|---:|---:|
| main (parent) | 2.5000 | 1,145,174 | 19,426 |
| child `compute/b48a7be4742c` | 2.3705 | 2,827,461 | 16,461 |
| **verifier** `00017833b2c9` | **0.0894** | 33,947 | 295 |

## Charts

- `charts/cc_vs_sciagent_by_task.png` — task vs verification cost, 3 tasks × cc-bare/sciagent.
- `charts/photonics_variants_split.png` — same split across the 4 photonics sciagent variants + cc-bare.
- `charts/cost_types_by_cell.png` — LLM vs compute vs storage per cell (all 6 case-study cells).
