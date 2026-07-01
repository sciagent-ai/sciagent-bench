# Verification comparison — cc-bare vs sciagent (T1 · T2 · T3)

Deterministic audit across the design-doc rubric applied to both adapters:
- **T1 (Computed?)** — did the required tool run?  sciagent: `compute_job_launched.service` events across parent + child sessions.  cc-bare: `Bash` tool_use commands in the Claude Code stream matched against a per-service signature (see `_CC_BARE_T1_SIGNATURES`).
- **T2 (Traceable?)** — does the claimed value appear in some `tool_result` output within float tolerance?  sciagent: `tool_result.output_summary` across parent + child sessions.  cc-bare: `tool_result` blocks in the Claude Code stream.
- **T3 (Correct?)** — does the claim satisfy the paper's numeric threshold? Deterministic; adapter-agnostic.
- **sciagent-only**: `sci_verdict` / `sci_confidence` from the last `verification_result` event; `agreement` compares that verdict against the deterministic T3 result.

T1 for cc-bare can report `yes*` when at least one required service matched but at least one has no signature mapping; `unknown` when none of the services have signatures. See `README.md`.

| task | condition | criterion | claimed_value | paper_value | T1_computed | T2_traceable | T3_passes_threshold | sci_verdict | sci_confidence | agreement |
|:---|:---|:---|---:|---:|:---|:---|:---|:---|---:|:---|
| photonics | cc-bare | ≥ 0.25 | 0.2504 | 0.253 | yes | yes | pass | — | — | — |
| photonics | sciagent-verifier-on-default | ≥ 0.25 | 0.2509 | 0.253 | yes | yes | pass | verified | 0.75 | yes |
| brca1_fitness_structure | cc-bare | ≥ 0.95 | 1.0 | 1.0 | yes | yes | pass | — | — | — |
| brca1_fitness_structure | sciagent-verifier-on-default | ≥ 0.95 | 1.0 | 1.0 | yes | yes | pass | verified | 0.78 | yes |
| cfd_fig3_kde | cc-bare | in [294.0, 298.0] | 295.333 | 296.2 | yes | yes | pass | — | — | — |
| cfd_fig3_kde | sciagent-verifier-on-default | in [294.0, 298.0] | 296.2092 | 296.2 | yes | yes | pass | verified | 0.91 | yes |

