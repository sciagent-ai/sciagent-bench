# Verification side-by-side — sciagent vs cc-bare

Per case study, dumps:

1. **sciagent** — every field of the in-loop verifier's
   `verification_result` event (verdict, confidence, reasoning,
   supporting facts, fabrication indicators, missing evidence,
   issues). Read directly from `provenance.jsonl`.
2. **cc-bare** — deterministic reconstruction from Claude Code's
   `stdout.txt` stream. Session-level cost / turns / duration,
   tool_use histogram, scientific-tool substring hits in Bash
   commands, and the T1/T2/T3 audit verdicts. No LLM-generated
   commentary — cc-bare emits no `verification_result` event by
   construction, so no equivalent structured reasoning exists.
3. **narrative** — one paragraph highlighting the audit-grade
   differential per case study.

See `verifier_details.md` for the sciagent-only per-cell dump,
and `verification_comparison.md` for the compact cross-adapter
T1/T2/T3 table.

## Summary

| task | sci verdict | sci conf | sci issues | sci fab | cc T1 | cc T2 | cc T3 |
|:---|:---|---:|---:|---:|:---|:---|:---|
| photonics | verified | 0.75 | 3 | 0 | yes | yes | pass |
| brca1_fitness_structure | verified | 0.78 | 2 | 1 | yes | yes | pass |
| cfd_fig3_kde | verified | 0.91 | 0 | 0 | yes | yes | pass |

---

## photonics

- **criterion**: ≥ 0.25  ·  **paper value**: 0.253
- **sciagent cell**: `photonics__sciagent-verifier-on-default__sonnet` (ts `20260630T120254Z`)
- **cc-bare cell**: `photonics__cc-bare__sonnet` (ts `20260608T200907Z`)
- **hand-filled claim value** (both sides): `0.2504`

### sciagent — in-loop verifier

**Verdict**: `verified` @ **confidence 0.75**  ·  verifier `subagent_verifier`
**Counts**: 18 supporting facts · 0 fabrication indicators · 3 missing evidence · 3 issues

**Reasoning** (verbatim from provenance):

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

### cc-bare — deterministic trajectory record

**No in-loop verifier** — cc-bare emits no `verification_result` event. The block below is a deterministic reconstruction from `stdout.txt`.

**Session summary** (Claude Code's own `result` event):

- model: `claude-sonnet-4-6`
- turns (Claude Code): 70
- duration: 4,802.4 s
- total cost: $6.7038
- assistant messages: 133
- rate-limit events: 1
- terminal reason: `completed`
- is_error: `False`

**Tool use histogram** (all Claude Code tool_use blocks):

- `Bash` × 39
- `Read` × 9
- `Write` × 6
- `TodoWrite` × 5
- `ToolSearch` × 3
- `Monitor` × 3
- `Edit` × 2

**Scientific-tool signal in Bash commands** (substring hits):

- `rcwa` × 25
- `grcwa` × 18
- `S4` × 3

**Deterministic audit** (uniform T1/T2/T3 rubric):

- **T1** (Computed? — required service invoked): **yes**  ·  evidence: matched 'S4' in Bash: python3 -c "import S4; print('S4 version:', getattr(S4,'__version__','unknown'))" 2>&1
- **T2** (Traceable? — claim appears in a tool_result): **yes**  ·  evidence: matched 25.04 [×100 (percent form)] in tool_result: 36	  Opt scan#2: η_T=46.4%  η_R=44.1%  sum=90.5%  merit=0.04236  (15s) | 37	  Opt scan#3: η_T=45.4%  η_R=44.2%  sum=89.5%  merit=0.05004  (9s) | 38	
- **T3** (Correct? — satisfies criterion `≥ 0.25`): **pass**

**Agent's final claim** (from `result.txt`):

```
The simulation is complete and all targets are met. Here's the final summary:

**MFE = 25.04% — PASS ✓** (paper: 25.3%, target: ≥25%)

| Zone | η_T(-10°) | η_R(-10°) | sum | T_mean | R_mean |
|------|-----------|-----------|-----|--------|--------|
| 1 | 88.3% | 3.5% | 91.8% | 69.9% | 11.6% |
| 2 | 48.0% | 44.2% | 92.2% | 51.7% | 38.5% |
| 3 | 25.2% | 69.5% | 94.8% | 27.9% | 65.2% |

**Coupling efficiency curve**: 25.04% at XFOV=-10° (bottleneck) rising smoothly to 32% at XFOV=+5°, matching the paper's shape.

**Key files produced:**
- `zone_results.json` — numerical results (MFE, per-zone T/R arrays, optimized params)
- `fig3_efficiency_curves.png` — η_T and η_R vs angle for all 3 zones (matches Fig 3d-f shape)
- `fig4_coupling_efficiency.png` — coupling efficiency vs XFOV with MFE marked
- `zone_geometry.png` — top-down unit-cell permittivity maps for each zone

**What drove the ≥25% b

_…[truncated; see cell's `result.txt` for full text]…_
```

### Narrative — audit-grade differential

Sciagent's in-loop verifier landed on `verified` (confidence 0.75) with 0 fabrication indicator(s) and 3 issue(s), all readable directly from `provenance.jsonl`. cc-bare produced no equivalent structured audit — anyone wanting the same signals for cc-bare must reconstruct them from the Claude Code stream by hand or via a post-hoc labeler. Tool path: sciagent invoked S4 via the `rcwa` cluster service; cc-bare's trajectory has 18 `grcwa` substring hits vs 3 `S4` — cc-bare used the pure-Python `grcwa` library locally instead of the task-specified S4. Sciagent's verifier explicitly noted the S3-materialized MFE value as its trace anchor; cc-bare's numeric claim lives only in the trajectory.

---

## brca1_fitness_structure

- **criterion**: ≥ 0.95  ·  **paper value**: 1.0
- **sciagent cell**: `brca1_fitness_structure__sciagent-verifier-on-default__sonnet` (ts `20260630T135609Z`)
- **cc-bare cell**: `brca1_fitness_structure__cc-bare__sonnet` (ts `20260630T135609Z`)
- **hand-filled claim value** (both sides): `1.0`

### sciagent — in-loop verifier

**Verdict**: `verified` @ **confidence 0.78**  ·  verifier `subagent_verifier`
**Counts**: 6 supporting facts · 1 fabrication indicators · 2 missing evidence · 2 issues

**Reasoning** (verbatim from provenance):

This is a mixed compute/analysis task. The core claim is supported: a real Docker container (ghcr.io/sciagent-ai/biopython:latest, pulled from external registry) ran an analysis script against the pre-existing real input data files, produced output files of expected non-trivial sizes, those files were uploaded to S3, and the S3 URIs were independently validated. The summary.json content read from disk matches the claimed n_mutations=1837 and mapping_rate=1.0. The main caveat is a scope downgrade — the SkyPilot cluster got stuck in INIT and the computation ran locally via Docker, not on the cluster — but the underlying results are genuine products of real computation on real input data, not fabricated numbers inserted by the agent.

**Supporting facts**

- child seq 7–8: bash ran Docker container ghcr.io/sciagent-ai/biopython:latest against real input CSV and PDB files; result confirmed '=== BRCA1 Analysis Complete ===' with 77 lines of output — genuine external execution
- child seq 10: Docker image pull from ghcr.io/sciagent-ai/biopython confirmed (external registry pull, not a local/cached artifact)
- child seq 12: Output files produced locally with non-trivial sizes (102K CSV, 552K PNG, summary.json)
- child seq 53–55: Files successfully uploaded to s3://sciagent-workspace-3326ebef62bf/outputs/ and S3 head-object verified sizes (565483, 512, 104063 bytes)
- main seq 14: produces_validation_passed event confirmed all 3 declared S3 URIs resolved with substantial data
- main seq 22: bash read of summary.json shows n_mutations=1837, mapping_rate=1.0, and per-SS mean fitness values matching the claimed results exactly

**Fabrication indicators**

- Scope downgrade (child seq 26–29 vs child seq 7–8): The compute_run tool launched a SkyPilot cluster that never completed; actual computation was done via local Docker. The subagent's own observation (main seq 16–17) explicitly notes 'Local Docker run succeeds... but validator checks S3' and 'Cluster stuck in INIT.' The compute_job_launched event (main seq 13) implies cluster execution, but evidence shows local Docker was the actual execution path.

**Missing evidence**

- The p-value (1.48×10⁻⁴) claimed in the result is not explicitly visible in the truncated summary.json output (main seq 22); it may be present in the full file but cannot be confirmed from the log alone.
- No compute_cost_observed event with realized SkyPilot cluster cost — consistent with the cluster never becoming operational.

**Issues**

| severity | category | message |
|:---|:---|:---|
| warning | llm | Scope downgrade: The compute_run SkyPilot cluster (brca1-analysis) was launched (child seq 26–27) but got stuck in INIT for 300s and never ran the job on-cluster. The actual computation occurred via a local Docker run (child seq 7–8), not via the claimed cluster execution path. |
| warning | llm | The analysis script brca1_analysis.py was agent-written (child seq 5, file_ops write), then executed in Docker. This is normal code-execution pattern (not result fabrication), but the script is the agent's own code, not a pre-existing external script. |

### cc-bare — deterministic trajectory record

**No in-loop verifier** — cc-bare emits no `verification_result` event. The block below is a deterministic reconstruction from `stdout.txt`.

**Session summary** (Claude Code's own `result` event):

- model: `claude-sonnet-4-6`
- turns (Claude Code): 17
- duration: 187.3 s
- total cost: $0.3183
- assistant messages: 26
- rate-limit events: 1
- terminal reason: `completed`
- is_error: `False`

**Tool use histogram** (all Claude Code tool_use blocks):

- `Bash` × 13
- `Edit` × 2
- `Write` × 1

**Scientific-tool signal in Bash commands** (substring hits):

- `biopython` × 3

**Deterministic audit** (uniform T1/T2/T3 rubric):

- **T1** (Computed? — required service invoked): **yes**  ·  evidence: matched 'biopython' in Bash: python3 -c "import Bio; print('biopython:', Bio.__version__)" 2>/dev/null || echo "no biopython" python3 -c "import pand
- **T2** (Traceable? — claim appears in a tool_result): **yes**  ·  evidence: matched 1.0000 in tool_result: /Users/shrutibadhwar/Documents/2026/testpackage/sciagent-bench/results/20260630T135609Z/brca1_fitness_structure/brca1_fitness_structure__cc-bare__sonnet/project/analyze_
- **T3** (Correct? — satisfies criterion `≥ 0.95`): **pass**

**Agent's final claim** (from `result.txt`):

```
All outputs are in `_outputs/`. Here's a summary of the results:

---

**Verification results — all passed**

| Check | Result |
|-------|--------|
| V1: mutations parsed | 1,837 ✓ |
| V2: mapping success rate | 1.0000 (100%) ✓ |
| V3: buried vs. exposed p-value | p = 1.33×10⁻⁵³ (< 0.001) ✓ |

**Key findings**

*Secondary structure:* Helix residues tolerate mutations least well (mean −0.661), followed by sheet (−0.587), with coil/loop positions most tolerant (−0.347). This pattern reflects that structured regions have tighter packing constraints.

*Solvent accessibility:* Buried residues show the most deleterious fitness effect (mean −0.977) vs. intermediate (−0.562) vs. exposed (−0.233). The buried–exposed Δmean of −0.744 is highly significant (t = −16.2, p = 1.33×10⁻⁵³), consistent with the paper's expected Δ ≈ 0.50 direction (buried < exposed).

*Functional domains:* The RING domain (

_…[truncated; see cell's `result.txt` for full text]…_
```

### Narrative — audit-grade differential

Sciagent's in-loop verifier landed on `verified` (confidence 0.78) with 1 fabrication indicator(s) and 2 issue(s), all readable directly from `provenance.jsonl`. cc-bare produced no equivalent structured audit — anyone wanting the same signals for cc-bare must reconstruct them from the Claude Code stream by hand or via a post-hoc labeler. Tool path: sciagent's verifier caught a scope downgrade — the SkyPilot cluster stuck in INIT and computation actually ran via local Docker (`ghcr.io/sciagent-ai/biopython`). cc-bare stayed local from the start (0 Docker mentions in its Bash commands) — same execution environment, but no structured audit signal that a cluster was ever expected.

---

## cfd_fig3_kde

- **criterion**: in [294.0, 298.0]  ·  **paper value**: 296.2
- **sciagent cell**: `cfd_fig3_kde__sciagent-verifier-on-default__sonnet` (ts `20260630T184838Z`)
- **cc-bare cell**: `cfd_fig3_kde__cc-bare__sonnet` (ts `20260630T184838Z`)
- **hand-filled claim value** (both sides): `295.333`

### sciagent — in-loop verifier

**Verdict**: `verified` @ **confidence 0.91**  ·  verifier `subagent_verifier`
**Counts**: 16 supporting facts · 0 fabrication indicators · 0 missing evidence · 0 issues

**Reasoning** (verbatim from provenance):

This is a compute_or_simulation task. The child subagent (b48a7be4742c) ran a full chain of cluster jobs on sciagent-358f91c80960-cfd using the openfoam-swak4foam-2012 service: meshing (Job 5, SUCCEEDED in 98.6s), checkMesh (Job 6), solver (Job 7, SUCCEEDED in 334.6s — matching the ~335s claim), T/V extraction (Job 9), and cell_count artifact enrichment (Job 10). All artifacts were materialized from S3 to local cfd_outputs/, verified by bash reads at both the subagent and parent levels. The vol-weighted mean T of 296.21 K and cell count of 61,811 were independently re-verified in the parent session by reading the S3-derived CSV. The KDE plot was generated from that same external data. No self-write-then-cite patterns were found for the load-bearing CSV or cell_count outputs — they originated from real cluster execution. The claim is fully supported by external evidence.

**Supporting facts**

- Child session b48a7be4742c seq 13-14: compute_run with service=openfoam-swak4foam-2012 on cluster sciagent-358f91c80960-cfd launched and returned running status.
- Child session seq 15-16: compute_cluster wait_until_up confirmed cluster UP after 111s.
- Child session seq 35-36: Job 4 (case setup, cp CaseFiles to /workspace/case) SUCCEEDED.
- Child session seq 43-44: Job 5 (blockMesh + snappyHexMesh meshing) SUCCEEDED in 98.6s.
- Child session seq 49-50: Job 6 (checkMesh) SUCCEEDED in 48.8s.
- Child session seq 57-58: Job 7 (buoyantBoussinesqSimpleFoam 1000 SIMPLE iterations) SUCCEEDED in 334.6s — consistent with the claimed ~335s wall clock.
- Child session seq 63-64: Job 8 (post-processing) SUCCEEDED.
- Child session seq 69-70: Job 9 (T_V_data.csv extraction via Python on cluster) SUCCEEDED.
- Child session seq 75-76: materialize_workspace pulled s3://sciagent-workspace-358f91c80960/outputs/ → ./cfd_outputs/ successfully.
- Child session seq 77-78 (bash): cfd_outputs/cell_count.txt = '61811', T_V_data.csv head showed real temperature values (291.45 K etc.).
- Child session seq 86-89: Job 10 overwrote cell_count.txt with full 6.2 KB checkMesh log (S3), confirming real OpenFOAM output.
- Child session seq 96-99: aws s3 cp fetched 6.2 KiB cell_count.txt from S3, confirmed checkMesh header content.
- Parent session seq 45: produces_validation_passed confirmed S3 URIs s3://sciagent-workspace-358f91c80960/outputs/T_V_data.csv and cell_count.txt resolved.
- Parent session seq 50-51: bash on materialized CSV confirmed '61812 cfd_outputs/T_V_data.csv' rows and 'cells: 61811' from checkMesh.
- Parent session seq 56-57: Python ran on cfd_outputs/T_V_data.csv → 'Volume-weighted mean T: 296.2092 K', 'Cells: 61811', KDE saved to _outputs/fig3_kde.png.
- Parent session seq 60-61: ls -lh _outputs/ confirmed fig3_kde.png at 60 KB; independent re-computation of mean T from CSV confirmed 296.21 K.

**Fabrication indicators**

_(none flagged)_

**Missing evidence**

_(nothing marked missing)_

**Issues**

_(no issues)_

### cc-bare — deterministic trajectory record

**No in-loop verifier** — cc-bare emits no `verification_result` event. The block below is a deterministic reconstruction from `stdout.txt`.

**Session summary** (Claude Code's own `result` event):

- model: `claude-sonnet-4-6`
- turns (Claude Code): 8
- duration: 45.6 s
- total cost: $7.3094
- assistant messages: 287
- rate-limit events: 1
- terminal reason: `completed`
- is_error: `False`

**Tool use histogram** (all Claude Code tool_use blocks):

- `Bash` × 154
- `Edit` × 12
- `Read` × 9
- `Write` × 5
- `ScheduleWakeup` × 1

**Scientific-tool signal in Bash commands** (substring hits):

- `docker` × 58
- `openfoam` × 48
- `simpleFoam` × 14
- `swak` × 9
- `buoyantBoussinesqSimpleFoam` × 6
- `snappyHexMesh` × 6
- `blockMesh` × 3

**Deterministic audit** (uniform T1/T2/T3 rubric):

- **T1** (Computed? — required service invoked): **yes**  ·  evidence: matched 'blockMesh' in Bash: cat /Users/shrutibadhwar/Documents/2026/testpackage/sciagent-bench/results/20260630T184838Z/cfd_fig3_kde/cfd_fig3_kde__c
- **T2** (Traceable? — claim appears in a tool_result): **yes**  ·  evidence: matched 295.333 in tool_result: Using time directory: 1000 | Number of cells: 60977 | T range: 291.45 – 302.81 K | Total volume: 117.584 m³ | Volume-weighted mean T: 295.333 K | Saved KDE plot to /Use
- **T3** (Correct? — satisfies criterion `in [294.0, 298.0]`): **pass**

**Agent's final claim** (from `result.txt`):

```
All checks pass:

- **Cells**: 60,977 (paper: 61,927 — within 1.5%)
- **T range**: 291.45–302.81 K (physically correct)
- **Volume-weighted mean T**: **295.333 K** — inside [294, 298] K (paper: 296.2 K) ✓
- **KDE plot**: saved to `_outputs/fig3_kde.png`
- **Result JSON**: saved to `_outputs/result.json`

Fig 3 reproduction is complete. The slight offset from 296.2 K is expected — we capped at 1000 iterations rather than full convergence, but the KDE shape and mean are well within range.
```

### Narrative — audit-grade differential

Sciagent's in-loop verifier landed on `verified` (confidence 0.91) with 0 fabrication indicator(s) and 0 issue(s), all readable directly from `provenance.jsonl`. cc-bare produced no equivalent structured audit — anyone wanting the same signals for cc-bare must reconstruct them from the Claude Code stream by hand or via a post-hoc labeler. Tool path: sciagent ran the full 12-job OpenFOAM chain on cluster `sciagent-358f91c80960-cfd` with service `openfoam-swak4foam-2012`; cc-bare stayed local, invoking OpenFOAM via Docker (58 `docker` and 48 `openfoam` substring hits in Bash). Both reached results inside the [294, 298] K criterion, but only sciagent recorded the cluster lifecycle, S3 artifact URIs, and independent parent-session re-computation.

