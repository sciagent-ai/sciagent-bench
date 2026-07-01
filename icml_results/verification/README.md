# icml_results/verification

Deterministic Correctness (T3 axis of the design doc's Phase 10 rubric)
across cc-bare and sciagent cells, plus the sciagent in-loop verifier
verdict for the sciagent side.

This folder deliberately does NOT re-implement Claude Code labeling or
reverify. It answers exactly the T3 question: **does the agent's claimed
number satisfy the task's numeric threshold?** — no LLM calls, no external
audit, just YAML criteria × hand-filled claims × verifier events already
in provenance.

## Files

- **`claim_values.csv`** — hand-filled. One row per (task, condition):
  `task, condition, cell_id, claimed_value, extraction_notes`. The
  `claimed_value` column is a plain number the human pulled out of the
  cell's `result.txt` or `project/_outputs/…` files. Rows we could
  auto-fill from a machine-readable output (like
  `verification_stats.txt`) came pre-filled.
- **`verify_and_compare.py`** — the joiner. Reads the CSV, pulls
  `verification_criteria` from `sciagent-bench/tasks/<task>.yaml`,
  extracts the last `verification_result` event from each sciagent
  cell's `provenance.jsonl`, applies the comparator, and writes a
  side-by-side table.
- **`verification_comparison.{md,csv}`** — produced output. Rerun the
  script anytime `claim_values.csv` changes.

## How the comparison works

Per (task, condition) row:

1. `criterion` = `<comparator> <threshold>` from the task YAML
   (e.g. `≥ 0.25`, `in [294, 298]`).
2. `claimed_value` = what the agent said (human-transcribed).
3. `passes_threshold` = deterministic check: does the claim satisfy the
   criterion? Comparators supported: `>=`, `<=`, `>`, `<`, `in [lo, hi]`.
4. `sci_verdict` / `sci_confidence` / `sci_verifier_model` = the last
   `verification_result` event's contents from the sciagent cell's
   `provenance.jsonl`. Blank for cc-bare cells (no in-loop verifier).
5. `agreement` = for sciagent cells only: does `passes_threshold` match
   the in-loop verifier (verified/supported ↔ pass; anything else ↔ fail)?
   Blank when either signal is missing.

## What this DOES NOT cover

- **T1 (Computed?)** — did the agent actually invoke the required tool?
  → check `provenance.jsonl` (sciagent) or `stdout.txt` (cc-bare) for
  the expected tool calls. Not automated here.
- **T2 (Traceable?)** — does the claimed value appear in any
  `tool_result` block? Not automated here.
- **Verifier honesty axes** (external_execution, fabrication, etc.) —
  already produced by `sciagent-bench/tools/reverify_cells.py` and
  saved as `verification_honesty_*.json` alongside each cell.

Add those when needed. For now, T3 + sciagent's in-loop verdict is
sufficient for the cc-bare vs sciagent paper claim.

## Filling the blanks

Two rows currently need a human-transcribed number (brca1
`mapping_success_rate` for both cc-bare and sciagent — no
machine-readable summary file was produced). Open the cell's
`result.txt` or `project/_outputs/…`, find the value, put it in
`claim_values.csv`'s `claimed_value` column, and rerun:

```bash
python3 verify_and_compare.py
```

## Reproducibility appendix (for the paper)

Deterministic auditor, T3 axis only. Criteria pinned in
`sciagent-bench/tasks/<task>.yaml`. Claimed values transcribed by a
human from each cell's stated result. Sciagent verdicts read verbatim
from the last `verification_result` event in the cell's
`provenance.jsonl`. No LLM calls in the audit itself.
