# In-loop verifier — case-study summary

Companion to `verifier_details.md` (the full per-field dump). This file
is the paper-ready 2-page narrative: what the report surfaces per case
study, the summary rollup, and the three concrete findings.

## What the report surfaces per case study (beyond just `verified/refuted/insufficient`)

- **Reasoning** — the verifier's full paragraph on why it landed on
  that verdict.
- **Supporting facts** — every concrete evidence point (seq numbers,
  event kinds, S3 URIs, cluster names). Photonics: 18 items · BRCA1: 6 ·
  CFD: 16.
- **Fabrication indicators** — what the verifier suspected. CFD: none ·
  BRCA1: 1 (scope downgrade — the SkyPilot cluster stuck in INIT,
  computation actually ran via local Docker) · Photonics: none.
- **Missing evidence** — what the trajectory didn't allow the verifier
  to check.
- **Issues** — severity/category/message tuples the verifier raised.

## Summary rollup

| task | verdict | conf | issues | supporting | fabrication | missing |
|:---|:---|---:|---:|---:|---:|---:|
| photonics    | verified | 0.75 | 3 | 18 | 0 | 3 |
| brca1        | verified | 0.78 | 2 |  6 | 1 | 2 |
| cfd_fig3_kde | verified | 0.91 | 0 | 16 | 0 | 0 |

## Concrete findings visible in the report

- **Photonics (conf 0.75)**: MFE = 0.2508680… traced to an S3-derived
  `tool_result`. Concerns: cluster job log_tails were truncated so
  per-zone intermediate scans couldn't be inspected; Fig 3(d-f) shape
  claim was made by the analyze subagent but never cross-validated
  against paper figures.
- **BRCA1 (conf 0.78)**: Verifier explicitly caught a **scope
  downgrade** — cluster stuck in INIT, actual compute ran via local
  Docker instead. Verdict still `verified` because the local Docker
  execution WAS on `ghcr.io/sciagent-ai/biopython:latest` against real
  input data, but the reported cluster path was misleading. This is a
  real audit-grade catch worth highlighting for the paper.
- **CFD (conf 0.91)**: Clean run. Zero issues, zero fabrication
  indicators, zero missing evidence. Full 12-job chain from meshing →
  checkMesh → `buoyantBoussinesqSimpleFoam` → post-processing all
  SUCCEEDED on cluster; results independently re-computed from
  S3-materialized CSV in the parent session. This is the "everything
  worked as designed" case study.

## Files in this folder

- `verifier_details_summary.md` — this file (paper-ready narrative)
- `verifier_details.md` — full per-field dump (~12 KB, all three case studies)
- `verifier_details.py` — the script that generated `verifier_details.md`
- `verify_and_compare.py` + `verification_comparison.{md,csv}` —
  cross-adapter T1/T2/T3 table
- `claim_values.csv` — hand-filled claim values
- `README.md` — the T1/T2/T3 methodology
