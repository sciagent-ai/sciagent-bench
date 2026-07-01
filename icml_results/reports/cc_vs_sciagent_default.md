# cc-bare vs sciagent-verifier-on-default across three tasks

Comparison table for the 6 cells used in the paper's main efficiency claim.
Each task contributes one cc-bare row and one sciagent row; both cells for a task use the same LLM (anthropic/claude-sonnet-4-6).

| task | condition | cell_id | adapter | main_model | iterations | wall_seconds | tool_calls | tokens_in | tokens_out | llm_cost_usd | compute_cost_usd | n_subagents | n_compute_jobs | n_sessions |
|:---|:---|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| photonics | cc-bare | photonics__cc-bare__sonnet | cc-bare | claude-sonnet-4-6 | 70 | 4802.4 | 67 | 6301875 | 249778 | 6.7038 | 0.0000 | 0 | 0 | 1 |
| photonics | sciagent-verifier-on-default | photonics__sciagent-verifier-on-default__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 90 | 5564.5 | 130 | 4981473 | 156842 | 9.8325 | 0.2551 | 4 | 12 | 4 |
| brca1_fitness_structure | cc-bare | brca1_fitness_structure__cc-bare__sonnet | cc-bare | claude-sonnet-4-6 | 17 | 187.3 | 16 | 343186 | 9785 | 0.3183 | 0.0000 | 0 | 0 | 1 |
| brca1_fitness_structure | sciagent-verifier-on-default | brca1_fitness_structure__sciagent-verifier-on-default__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 40 | 998.7 | 37 | 1340256 | 17288 | 1.5457 | 0.0299 | 1 | 1 | 2 |
| cfd_fig3_kde | cc-bare | cfd_fig3_kde__cc-bare__sonnet | cc-bare | claude-sonnet-4-6 | 8 | 45.6 | 181 | 297874 | 1844 | 7.3094 | 0.0000 | 0 | 0 | 1 |
| cfd_fig3_kde | sciagent-verifier-on-default | cfd_fig3_kde__sciagent-verifier-on-default__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 65 | 2369.5 | 74 | 3972635 | 35887 | 4.8705 | 0.2119 | 1 | 10 | 2 |

