# Photonics — verifier influence across variants (summary)

Companion to `photonics_verifier_variants.md` (the full per-variant
dump). Paper-ready narrative: outcome table + three findings + a notable
side observation from the raw data.

## Verifier outcomes across the 4 variants

| variant | verdict | conf | issues | supp | fab | miss |
|:---|:---|---:|---:|---:|---:|---:|
| verifier-on-default (sonnet, recursive)         | verified     | 0.75 | 3 | 18 | 0 | 3 |
| no-recursion (sonnet, legacy)                   | insufficient | 0.62 | 7 |  6 | 1 | 5 |
| crossverifier (openai/o4-mini, no recursion)    | insufficient | 0.82 | 3 |  4 | 0 | 3 |
| verifier-off (control)                          | (no event)   | —    | — |  — | — | — |

Confirmation that the crossverifier row is `no recursion` (not just
"legacy"): the cell was run 2026-06-08, before the Phase 1 recursion
flag existed, so recursion defaulted to `false`. Provenance backs this
up — the crossverifier's verifier `reasoning` field contains **zero**
references to child sessions (no mention of `child session`, `subagent`,
`~/.sciagent/sessions/…`); the same-family `no-recursion` cell's
reasoning explicitly says *"The critical compute work ran inside child
subagent session 8d81f17ae446, whose trajectory is not auditable from
this log."*

## Three findings the report surfaces

### 1. Recursion effect — the Phase 1 finding, cleanly demonstrated

Same sonnet verifier, only the `verifier_include_child_sessions` flag
differs:

- **No recursion** → `insufficient` @ 0.62, 6 supporting facts,
  5 missing-evidence entries, 1 fabrication indicator.
- **With recursion** → `verified` @ 0.75, **18 supporting facts (+12)**,
  3 missing (−2), 0 fabrication (−1).

The audit trail was on disk both times. Only the verifier's ability to
READ subagent logs changed. Verdict flipped.

### 2. Verifier-model effect (holding recursion off)

Same agent, both without recursion:

- **Sonnet verifier**: `insufficient` @ 0.62 (6 supporting facts).
- **openai/o4-mini verifier**: `insufficient` @ 0.82 (4 supporting facts).

Both reached the same "insufficient" verdict but the openai verifier
was **more confident about the insufficiency** despite citing fewer
facts. Could be calibration difference between models OR reasoning-tuned
model behavior (o4-mini). Report flags this as "don't lean on it
without a second point of data" — the current recipe has been bumped
to `openai/gpt-5.4`, so a fresh run under the new recipe would replace
this row.

### 3. Verifier-off control

`enable_verification: false` → zero `verification_result` events.
Included so the reader knows what a "verifier disabled" run looks like
in provenance (nothing) — distinguishable from a run that reached the
gate and got refuted.

## Interesting side-detail

Even the `verifier-off` cell has `produces_validation_failed` and
`session_end.exit_reason=done`. So sciagent still ran the data/exec
gates and cluster lifecycle — **only the LLM verification gate was
skipped**. Design worked as intended.

## Notable observation from the raw dump

The pre-Phase-1 no-recursion cell's fabrication indicator flagged a
real issue — the trajectory reported one MFE from an externally read
`summary.json` (3.69%) and later reported a different MFE from
agent-authored analysis (20.433%). Verifier said *"the trajectory does
not independently validate why the later analysis should supersede the
earlier RCWA summary."* That's a legit audit-grade concern the verifier
caught. Worth featuring in the paper narrative — **even the
"insufficient" no-recursion verdict was picking up something real**,
not just failing due to blindness to child sessions.

## Files in this folder

- `photonics_verifier_variants_summary.md` — this file (paper-ready narrative)
- `photonics_verifier_variants.md` — full per-variant dump (~20 KB, 4 variants)
- `photonics_verifier_variants.py` — the script that generated the dump
- `verifier_details.md` / `verifier_details_summary.md` — the three-task sciagent-only variant (not photonics-only)
- `verification_side_by_side.md` / `_summary.md` — sciagent vs cc-bare across three tasks
- `verify_and_compare.py` + `verification_comparison.{md,csv}` — compact cross-adapter T1/T2/T3 table
- `claim_values.csv` — hand-filled claim values
- `README.md` — the T1/T2/T3 methodology
