# Photonics — all runs, side by side

Total cells: 7. Sources under `icml_results/*/photonics/`.

Sciagent rows are the recursive rollup: parent session + every child session referenced via `subagent_completed.child_session_id`. cc-bare rows come from `stdout.txt` (Claude Code's session summary). Compute cost is `sky.cost_report()` for the cluster referenced by the first `compute_job_launched` event (empty when the run stayed local).

| ts | cell_id | adapter | main_model | iterations | wall_seconds | tool_calls | tokens_in | tokens_out | llm_cost_usd | compute_cost_usd | n_subagents | n_compute_jobs | n_sessions |
|:---|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260608T200907Z | photonics__cc-bare__sonnet | cc-bare | claude-sonnet-4-6 | 70 | 4802.4 | 67 | 6301875 | 249778 | 6.7038 | 0.0000 | 0 | 0 | 1 |
| 20260608T200907Z | photonics__cc-sky-registry__sonnet | cc-bare | claude-sonnet-4-6 | 8 | 2160.2 | 5 | 317106 | 128767 | 2.1545 | 0.0000 | 0 | 0 | 1 |
| 20260608T200907Z | photonics__sciagent-crossverifier__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 50 | 3226.1 | 48 | 2029425 | 114971 | 5.0477 | 0.5164 | 2 | 6 | 3 |
| 20260608T200907Z | photonics__sciagent-no-recursion__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 59 | 3073.6 | 63 | 3191737 | 77952 | 4.4485 | 0.2679 | 2 | 10 | 3 |
| 20260608T200907Z | photonics__sciagent-verifier-off__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 62 | 7468.2 | 98 | 4744621 | 175810 | 6.9730 | 0.2551 | 3 | 12 | 3 |
| 20260608T200907Z | photonics__sciagent-verifier-on-default__gpt5 | sciagent | openai/gpt-5.4 | 54 | 4439.4 | 68 | 1908131 | 50933 | 2.8106 | 0.2171 | 3 | 5 | 4 |
| 20260630T120254Z | photonics__sciagent-verifier-on-default__sonnet | sciagent | anthropic/claude-sonnet-4-6 | 90 | 5564.5 | 130 | 4981473 | 156842 | 9.8325 | 0.2551 | 4 | 12 | 4 |

