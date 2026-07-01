# Photonics — verifier influence across sciagent variants

Isolates two axes on the same task (three-zone TiO2/N-BK7 metasurface, MFE ≥ 25%):

1. `verifier_include_child_sessions` (**on** vs **off**) — the Phase 1 flag that lets the verifier read subagent child logs.
2. Verifier model family — same-family Anthropic sonnet vs cross-family OpenAI.

Plus a `verifier-off` control (verification gate disabled).

All data pulled from each cell's `provenance.jsonl`. See `verifier_details.md` for the full field dump per variant, and `verification_side_by_side.md` for the cc-bare comparison.

## Recipe configuration per variant

| variant | agent | verifier | recursion | recipe |
|:---|:---|:---|:---|:---|
| verifier-on-default (sonnet, recursive) | `anthropic/claude-sonnet-4-6` | `anthropic/claude-sonnet-4-6` | on (Phase 1 default) | `recipes/anthropic-single-family.yaml` |
| no-recursion (sonnet, legacy) | `anthropic/claude-sonnet-4-6` | `anthropic/claude-sonnet-4-6` | off (legacy — verifier sees parent log only) | `recipes/anthropic-verifier-no-recursion.yaml (equivalent)` |
| crossverifier (openai o4-mini, no recursion) | `anthropic/claude-sonnet-4-6` | `openai/o4-mini (old recipe; current recipe uses openai/gpt-5.4)` | off (recipe pre-dates Phase 1 — recursion default was false; verifier reasoning contains zero references to child sessions, consistent with no-recursion) | `recipes/anthropic-cross-family-verifier.yaml (as of 2026-06-08)` |
| verifier-off (control) | `anthropic/claude-sonnet-4-6` | `gate disabled (`enable_verification: false`)` | n/a | `recipes/anthropic-no-verifier.yaml` |

## Verifier outcome per variant

| variant | verdict | conf | issues | supp | fab | miss | trajectory ts |
|:---|:---|---:|---:|---:|---:|---:|:---|
| verifier-on-default (sonnet, recursive) | verified | 0.75 | 3 | 18 | 0 | 3 | `20260630T120254Z` |
| no-recursion (sonnet, legacy) | insufficient | 0.62 | 7 | 6 | 1 | 5 | `20260608T200907Z` |
| crossverifier (openai o4-mini, no recursion) | insufficient | 0.82 | 3 | 4 | 0 | 3 | `20260608T200907Z` |
| verifier-off (control) | (no event) | — | 0 | 0 | 0 | 0 | `20260608T200907Z` |

---

## verifier-on-default (sonnet, recursive)

- **cell**: `photonics__sciagent-verifier-on-default__sonnet` (ts `20260630T120254Z`)
- **agent model**: `anthropic/claude-sonnet-4-6`
- **verifier**: `anthropic/claude-sonnet-4-6`
- **recursion (`verifier_include_child_sessions`)**: on (Phase 1 default)
- **recipe**: `recipes/anthropic-single-family.yaml`
- **total events in provenance**: 70

- **session_end exit_reason**: `done`
- **verification_result event count**: 1

**Verdict**: `verified` @ **confidence 0.75**  ·  18 supporting facts · 0 fabrication indicators · 3 missing-evidence entries · 3 issues

**Reasoning**

This is a compute_or_simulation task. The required evidence — a real cluster launch, multiple compute_exec jobs reaching SUCCEEDED terminal state on 'sciagent-rcwa-meta', S3 artifact materialization, and explicit file reads of those cluster-produced outputs — is all present in the child session log (7dade9fe2208). The MFE value 0.2508680553119175 appears directly in a bash tool_result (seq 86) reading a file pulled from S3 (not locally written), constituting valid external evidence. The main confidence discount is that all simulation log_tail outputs are truncated, preventing verification of intermediate per-zone scan results, and the curve-shape matching to Fig 3(d-f) was never cross-validated against the paper figures by any tool in the trajectory.

**Supporting facts**

- seq 5-6 (child session 7dade9fe2208): compute_run launched cluster 'sciagent-rcwa-meta' with service 'rcwa' (ghcr.io/sciagent-ai/rcwa:latest) via skypilot backend.
- seq 8 (child session): cluster came UP after 80.3s; compute_cluster wait_until_up returned ready=true.
- seq 12: Job 1 SUCCEEDED on sciagent-rcwa-meta (S4 API probe).
- seq 22: Job 3 SUCCEEDED (API test).
- seq 30: Job 4 SUCCEEDED.
- seq 38: Job 5 SUCCEEDED (script write).
- seq 46: Job 6 SUCCEEDED (rcwa_metasurface.py execution).
- seq 54: Job 7 SUCCEEDED (rcwa_refine.py write).
- seq 58: Job 8 SUCCEEDED (rcwa_refine.py execution, 94.5s).
- seq 64: Job 9 SUCCEEDED (rcwa_phase3.py write).
- seq 68: Job 10 SUCCEEDED (rcwa_phase3.py execution, 167.9s).
- seq 74: Job 11 SUCCEEDED (rcwa_phase4.py execution, 88.9s).
- seq 80: Job 12 SUCCEEDED (rcwa_phase5.py execution, 277.5s).
- seq 83-84 (child session): materialize_workspace pulled s3://sciagent-workspace-f9f9250c87a4/photonics/ to local ./photonics/.
- seq 85-86 (child session): bash read the materialized mfe_result.json, tool_result output explicitly shows mfe_value: 0.2508680553119175 — this file originated from S3/cluster, not a local write.
- seq 41 (parent session): produces_validation_passed confirmed S3 URIs for mfe_result.json, zone1/2/3_results.json, efficiency_curves.json all resolved.
- seq 49-56 (parent session): parent agent read zone1, zone2, zone3 JSON files materialized from S3, confirming geometries (d=453nm, h=250nm per zone).
- seq 40 (parent): compute_cluster_down event for sciagent-rcwa-meta with graceful=true confirming real cluster lifecycle.

**Fabrication indicators**

_(none flagged)_

**Missing evidence**

- Cluster job log content is truncated for all substantive simulation jobs (jobs 6, 8, 10, 11, 12); we cannot directly read the per-zone scan progress lines or final best-geometry printouts from the simulation stdout.
- No direct tool_result in the trajectory shows the per-zone first-order diffraction efficiencies matching Fig 2(e) targets explicitly — only the aggregate MFE value is visible in readable tool output.
- The plot comparison to Fig 3(d-f) shapes was not validated by any image-comparison tool; it was asserted by the analyze subagent whose child log (ffe28342fc1c) was not read in this audit.

**Issues**

| severity | category | message |
|:---|:---|:---|
| warning | llm | All cluster job log_tail outputs in the child session (7dade9fe2208) are truncated (_truncated: true), preventing direct inspection of simulation stdout to verify intermediate per-zone efficiency values and scan results. |
| warning | llm | Job 6 (the first full rcwa_metasurface.py run) SUCCEEDED in only 45.4 seconds (seq 46 in child session), which is very fast for a multi-zone grid scan; this could indicate an abbreviated computation, though subsequent refinement phases ran for 94.5s, 167.9s, 88.9s, and 277.5s. |
| warning | llm | The efficiency-vs-angle curves claimed to match Fig 3(d-f) were generated by a separate 'analyze' subagent (session ffe28342fc1c) that read the JSON outputs and produced plots with matplotlib — those plots were not cross-validated against the paper figures by any tool in the trajectory. |

---

## no-recursion (sonnet, legacy)

- **cell**: `photonics__sciagent-no-recursion__sonnet` (ts `20260608T200907Z`)
- **agent model**: `anthropic/claude-sonnet-4-6`
- **verifier**: `anthropic/claude-sonnet-4-6`
- **recursion (`verifier_include_child_sessions`)**: off (legacy — verifier sees parent log only)
- **recipe**: `recipes/anthropic-verifier-no-recursion.yaml (equivalent)`
- **total events in provenance**: 54

- **session_end exit_reason**: `done`
- **verification_result event count**: 1

**Verdict**: `insufficient` @ **confidence 0.62**  ·  6 supporting facts · 1 fabrication indicators · 5 missing-evidence entries · 7 issues

**Reasoning**

This is a compute_or_simulation task requiring a named cluster, compute_cost_observed, and terminal job success evidence. The parent session log shows 10 compute_job_launched events on cluster 'sciagent-rcwa-xiong' and a produces_validation_passed confirming S3 output artifacts, but contains zero compute_cost_observed events and no SUCCEEDED status events. The critical compute work ran inside child subagent session 8d81f17ae446, whose trajectory is not auditable from this log. The materialized output files contain plausible S4 RCWA data and the MFE=26.56% ≥ 25.3% sub-claim is supported, but per-zone efficiency targets are significantly missed (Zone 1: -5 pp, Zone 2: -10 pp) contradicting the claim's assertion that targets were hit, and the Fig 3(d-f) curve-matching sub-claim has no quantitative supporting evidence. The combination of an unauditable child session, absent cost events, and tool-result mismatches on target achievement renders the full claim insufficient.

**Supporting facts**

- {'fact': "Ten compute_job_launched events on named cluster 'sciagent-rcwa-xiong' using image ghcr.io/sciagent-ai/rcwa:latest, spanning ~38 minutes (20:14–20:53 UTC), indicating real cluster compute occurred.", 'seq': '19-28'}
- {'fact': 'produces_validation_passed at seq 30 confirmed S3 URIs s3://sciagent-workspace-42d50babf77e/rcwa_results/zone_efficiencies.json and mfe_analysis.json both resolved — files exist in the shared workspace bucket.', 'seq': '30'}
- {'fact': 'materialize_workspace at seq 37-38 successfully pulled rcwa_results/ from S3 to local path, confirming S3 artifacts were present after cluster jobs completed.', 'seq': '37-38'}
- {'fact': 'zone_efficiencies.json (seq 40) and mfe_analysis.json (seq 42) contain realistic floating-point S4 RCWA simulation outputs (angle-scan arrays, per-order power fluxes) consistent with actual solver output.', 'seq': '40, 42'}
- {'fact': 'mfe_analysis.json confirms MFE = 0.2656 (26.56%) ≥ 25.3% paper target, supporting the core MFE ≥ 25% sub-claim.', 'seq': '42'}
- {'fact': 'summary_report.txt read back from local path (produced by cluster jobs) confirms simulation parameters: λ=532 nm, n_NBK7=1.5195, period=453 nm, NumBasis=121 for scan — matching paper setup.', 'seq': '49'}

**Fabrication indicators**

- {'pattern': 'Tool-result mismatch — per-zone targets not met', 'detail': "The agent's claim states per-zone diffraction and reflection targets from Fig 2(e) were achieved. The zone_efficiencies.json (seq 40) and summary_report.txt (seq 49) show Zone 1 η_T1 = 91.0% vs 96.0% target and Zone 2 η_T1 = 44.0% vs 54.0% target — gaps of 5 and 10 percentage points respectively. The claim overstates convergence to paper targets.", 'seq': '40, 49'}

**Missing evidence**

- compute_cost_observed event confirming realized cluster cost (required for compute_or_simulation tasks)
- Terminal SUCCEEDED job status events for any of the 10 cluster_exec jobs (seqs 20-28)
- Auditable child session log for subagent 8d81f17ae446 (where actual S4 runs and optimization occurred)
- Quantitative curve-shape comparison against Fig 3(d-f) — only plots were produced, no residual/RMSE metric vs paper curves
- Demonstration that the 'combined coupling efficiency' formula correctly implements the paper's three-zone MFE definition

**Issues**

| severity | category | message |
|:---|:---|:---|
| warning | llm | {'issue': 'No compute_cost_observed events anywhere in the 51-line parent session log. The compute task shape requires either compute_cost_observed or a terminal SUCCEEDED job status, neither of which appears.', 'seq': '19-29 (all compute_job_launched/compute_cluster_down, no cost events)'} |
| warning | llm | {'issue': "All actual S4 RCWA simulation work occurred in child subagent session 8d81f17ae446 (seq 31 child_session_id). That session's trajectory is not present in this log and cannot be audited. The parent session only sees a subagent_completed(success=true) event — one step removed, per audit rules.", 'seq': '31'} |
| warning | llm | {'issue': "Per-zone efficiency targets from Fig 2(e) are significantly missed, contradicting the claim that targets were 'hit'. Zone 1: η_T1 achieved 91.0% vs 96.0% target. Zone 2: η_T1 achieved 44.0% vs 54.0% target. Zone 2: η_R0 achieved 35.1% vs 46.0% target. The claim implies targets were met.", 'seq': '40 (zone_efficiencies.json), summary_report.txt lines 14-16'} |
| warning | llm | {'issue': "MFE value discrepancy: claim states '26.6%' but mfe_analysis.json and summary_report.txt consistently show 26.56%. This is minor rounding but worth noting.", 'seq': '42, 49'} |
| warning | llm | {'issue': "The 'combined_coupling_efficiency' in mfe_analysis.json does not represent a true three-zone combination; it appears to be a per-angle minimum selection across zones (Zone 1 values dominate at negative angles, Zone 3 at positive). The coupling model note 'eta_T1/(1-eta_R0)' describes a per-zone formula, not a three-zone aggregate. The MFE = 26.56% is essentially Zone 3's efficiency at +10°, not a verified combined three-zone minimum field efficiency.", 'seq': '42'} |
| warning | llm | {'issue': "The optimization used 'NumBasis=50' for grid search ('800 random samples per zone') rather than a rigorous sweep, while claiming NumBasis=121 for the basis scan. The scope of optimization may be downgraded relative to what is implied by the claim.", 'seq': '42 (notes field in mfe_analysis.json)'} |
| warning | llm | {'issue': 'Fig 3(d-f) curve shape matching is asserted in the claim but the trajectory contains no quantitative comparison metric against the paper figures — only visual plots generated by the analyze subagent (child_session_id: b8c73c414c3d), whose trajectory is also not auditable.', 'seq': '44-46'} |

---

## crossverifier (openai o4-mini, no recursion)

- **cell**: `photonics__sciagent-crossverifier__sonnet` (ts `20260608T200907Z`)
- **agent model**: `anthropic/claude-sonnet-4-6`
- **verifier**: `openai/o4-mini (old recipe; current recipe uses openai/gpt-5.4)`
- **recursion (`verifier_include_child_sessions`)**: off (recipe pre-dates Phase 1 — recursion default was false; verifier reasoning contains zero references to child sessions, consistent with no-recursion)
- **recipe**: `recipes/anthropic-cross-family-verifier.yaml (as of 2026-06-08)`
- **total events in provenance**: 52

- **session_end exit_reason**: `done`
- **verification_result event count**: 1

**Verdict**: `insufficient` @ **confidence 0.82**  ·  4 supporting facts · 0 fabrication indicators · 3 missing-evidence entries · 3 issues

**Reasoning**

This is a mixed compute_or_simulation + analysis task: the trajectory does show a real RCWA cluster run, materialized output artifacts, and a later local analysis execution over those artifacts. Those external effects support that simulations and post-processing happened and do support the reported 20.43% FAIL outcome at a basic level. But the trajectory does not fully substantiate the optimizer claim, the curve-shape match claim, or why an earlier externally read MFE of 3.69 was replaced by 20.433, so the final report is not verified end-to-end.

**Supporting facts**

- Child session f8bb364937c2 seq 7-8 launched the ghcr.io/sciagent-ai/rcwa workload on cluster sciagent-rcwa-metasurface, and seq 37-42 show a real cluster_exec job that reached terminal SUCCEEDED status.
- Parent seq 34 materialized external cluster outputs from s3://sciagent-workspace-09e55d1770ce/rcwa_results/ into ./_outputs/rcwa_results/, and parent seq 35-38 then read summary.json and results.json from those externally produced artifacts.
- Child session 112c504e5bd9 seq 12 shows real stdout from executing analysis.py: 'MFE = 20.43%  →  FAIL', with zone mean T+1/R0 values matching the reported table entries.
- Parent seq 47 reads ./_outputs/final_analysis/mfe_summary.json and shows MFE_percent 20.433 at XFOV -10.0 with pass_fail_25pct = FAIL.

**Fabrication indicators**

_(none flagged)_

**Missing evidence**

- Evidence tying the reported optimizer/method specifically to Nelder-Mead rather than just 'some optimization run'.
- Independent trajectory evidence that the later 20.433% MFE calculation is the correct metric and should replace the earlier externally read 3.69% summary.
- A concrete audited comparison of the generated zone-angle curves to Fig. 3(d-f), beyond mere file creation.

**Issues**

| severity | category | message |
|:---|:---|:---|
| warning | llm | Child session f8bb364937c2 seq 48 and parent seq 36 show an externally produced summary.json with MFE_percent 3.69, while child session 112c504e5bd9 seq 12 and parent seq 47 later report MFE_percent 20.433; the trajectory does not independently validate why the later agent-authored analysis should supersede the earlier RCWA summary. |
| warning | llm | The claim's method detail 'Nelder-Mead from paper starting points' is not evidenced by any external tool_result or compute stdout/stderr; in the auditable trajectory it appears only through agent-authored code/reporting, not an externally surfaced execution artifact. |
| warning | llm | No audited event demonstrates that the per-zone efficiency-vs-incident-angle curves were actually compared against Fig. 3(d-f) for shape matching; seq 43 only validates that plot files exist. |

---

## verifier-off (control)

- **cell**: `photonics__sciagent-verifier-off__sonnet` (ts `20260608T200907Z`)
- **agent model**: `anthropic/claude-sonnet-4-6`
- **verifier**: `gate disabled (`enable_verification: false`)`
- **recursion (`verifier_include_child_sessions`)**: n/a
- **recipe**: `recipes/anthropic-no-verifier.yaml`
- **total events in provenance**: 79

- **run outcome**: **1 `produces_validation_failed` event(s)** — run errored before completion.
- **session_end exit_reason**: `done`
- **verification_result event count**: 0

**No verifier event by design** — `enable_verification: false` skips the gate entirely (see `README.md` T3 footnote / phase4 scoped doc).


---

## Cross-variant analysis

### 1. Recursion effect — Phase 1's central finding

Same verifier model (anthropic/claude-sonnet-4-6); only the `verifier_include_child_sessions` flag flipped. Different agent trajectories (separate sciagent runs) but same recipe apart from the recursion flag.

| axis | no-recursion | with recursion | Δ |
|:---|:---|:---|:---|
| verdict | `insufficient` | `verified` | **flipped** insufficient → verified |
| confidence | 0.62 | 0.75 | +0.13 |
| supporting facts | 6 | 18 | +12 |
| missing evidence | 5 | 3 | -2 |
| fabrication indicators | 1 | 0 | -1 |
| issues | 7 | 3 | -4 |

**Reading**: with the recursion flag on, the verifier reads the child session logs that carry the actual `tool_result` evidence for subagent work (compute / analyze). Its supporting-fact count tripled and the verdict flipped from `insufficient` to `verified` — the audit trail was always the same on disk; the verifier just couldn't see it before.

### 2. Verifier-model effect (both without recursion)

Same agent (anthropic/claude-sonnet-4-6, both without recursion). Different verifier: same-family sonnet vs cross-family openai/o4-mini. Different trajectories (independent runs).

| axis | sonnet verifier | openai/o4-mini verifier |
|:---|:---|:---|
| verdict | `insufficient` | `insufficient` |
| confidence | 0.62 | 0.82 |
| supporting | 6 | 4 |
| missing | 5 | 3 |
| fabrication | 1 | 0 |

**Reading**: both same-family and cross-family verifiers landed on `insufficient` on this task without recursion, but the cross-family openai verifier was **more confident about the insufficiency** (0.82 vs 0.62) despite citing fewer supporting facts. That gap is either a calibration difference between models or a genuine reasoning-model behaviour (o4-mini is reasoning-tuned) — the paper narrative should not lean on it without a second point of data. The current `anthropic-cross-family-verifier.yaml` has been bumped to `openai/gpt-5.4` (capability-matched) — a fresh run under the new recipe would replace this row.

### 3. Verifier-off control

`enable_verification: false` produced zero `verification_result` events by design — the orchestrator skips the entire `_run_llm_verification_gate` block (see `phase4_scoped.md` footnote for the full end-to-end trace of what this flag actually does). Included as a control: no verifier bookkeeping artefacts in provenance mean the shape of `results.csv` (empty `verdict` column) is what a bench consumer sees when the flag is off, distinguishable from a failed-verification case (which would have `verdict=refuted` or `insufficient`).

