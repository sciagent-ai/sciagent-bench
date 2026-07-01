# Sciagent vs cc-bare verification — case-study summary

Companion to `verification_side_by_side.md` (the full per-cell dump).
This file is the paper-ready 2-page narrative: report structure, key
observations per case study, and the summary rollup.

## Report structure per case study

Each case study section in `verification_side_by_side.md` contains:

1. **sciagent block** — full `verification_result` fields verbatim
   (same content as `verifier_details.md`).
2. **cc-bare block** — deterministic reconstruction from `stdout.txt`:
   - Session summary (model, turns, duration, cost, terminal reason)
   - Tool use histogram
   - Scientific-tool substring hits in Bash commands
   - T1/T2/T3 verdicts + evidence
   - Agent's final claim from `result.txt`
3. **Narrative** — one paragraph flagging the audit-grade differential.

## Key observations the report surfaces

### Photonics

- **Sciagent verifier**: `verified` @ 0.75, cluster launched `rcwa`
  service (S4), MFE 0.2508680 traced to S3-materialized bash
  `tool_result`.
- **cc-bare**: **18 `grcwa` mentions vs 3 `S4`** — cc-bare used the
  pure-Python `grcwa` library locally, not the task-specified S4.
  This is a legitimate substitution (grcwa is also RCWA) but the
  audit trail doesn't record why the substitution happened.
  Sciagent's structured verifier would have caught this as a
  fabrication indicator if it had done the same.

### BRCA1

- **Sciagent verifier** explicitly caught the scope downgrade —
  SkyPilot cluster stuck in INIT, actual compute ran via local
  Docker. Verdict still `verified` @ 0.78 because the local Docker
  execution WAS legit.
- **cc-bare**: no Docker mentions, biopython imported locally in
  Python. Same execution environment as sciagent's actual path, but
  no equivalent structured audit signal.

### CFD_fig3_kde

- **Sciagent**: `verified` @ 0.91, full 12-job cluster chain, zero
  issues, zero fabrication indicators, results independently
  re-computed in parent session from S3-materialized CSV.
- **cc-bare**: **58 Docker + 48 OpenFOAM mentions in Bash** —
  cc-bare ran OpenFOAM via Docker locally instead of the cluster.
  Both landed inside the [294, 298] K criterion (cc-bare said
  295.333, sciagent said 296.209 — the paper value is 296.2), so
  both pass T3. But the sciagent trajectory has structured evidence
  of every cluster job's outcome; cc-bare's is a raw shell history.

## Also interesting side-by-side

- **cc-bare cfd_fig3_kde ran 287 assistant messages / 154 Bash calls
  in 45 seconds wall time.** That's a Claude Code parallel/streaming
  anomaly worth noting in the paper's efficiency table too.

## Summary rollup

| task | sci verdict | conf | sci issues | sci fab | cc T1 | cc T2 | cc T3 |
|:---|:---|---:|---:|---:|:---|:---|:---|
| photonics    | verified | 0.75 | 3 | 0 | yes | yes | pass |
| brca1        | verified | 0.78 | 2 | 1 | yes | yes | pass |
| cfd_fig3_kde | verified | 0.91 | 0 | 0 | yes | yes | pass |

## Files in this folder

- `verification_side_by_side_summary.md` — this file (paper-ready narrative)
- `verification_side_by_side.md` — full per-case-study dump (~22 KB, both sides)
- `verification_side_by_side.py` — the script that generated it
- `verifier_details.md` / `verifier_details_summary.md` — sciagent-only variant
- `verify_and_compare.py` + `verification_comparison.{md,csv}` —
  compact cross-adapter T1/T2/T3 table
- `claim_values.csv` — hand-filled claim values
- `README.md` — the T1/T2/T3 methodology
