# icml_results/verification

Deterministic T1 · T2 · T3 verification comparison for cc-bare vs
sciagent, drawn from sciagent provenance + child-session recursion +
hand-transcribed claim values + task YAMLs.

This folder deliberately does NOT re-implement Claude Code labeling or
reverify. It answers the three rubric questions from the design doc's
Phase 10 with a small deterministic script and one hand-fillable CSV.

## Files

- **`claim_values.csv`** — hand-filled. One row per (task, condition):
  `task, condition, cell_id, claimed_value, extraction_notes`. The
  `claimed_value` column is a plain number transcribed from the cell's
  `result.txt` or `project/_outputs/…`. Rows we could auto-fill from a
  machine-readable output (like `verification_stats.txt`) came
  pre-filled.
- **`verify_and_compare.py`** — the joiner. Reads the CSV, pulls
  `verification_criteria` and `services_needed` from
  `sciagent-bench/tasks/<task>.yaml`, walks each sciagent cell's
  `provenance.jsonl` (plus every child session referenced via
  `subagent_completed.child_session_id`), and writes a side-by-side
  table.
- **`verification_comparison.{md,csv}`** — produced output. Rerun
  anytime `claim_values.csv` changes.

## Rubric definitions (from the design doc, Phase 10)

Per (task, condition) row:

### T1 — Computed?

Did the agent actually invoke the tool it was supposed to?

- **sciagent** — walks parent + child session logs for
  `compute_job_launched` events; passes if any event's `service`
  prefix-matches the task's `services_needed`. Prefix (not exact)
  because CFD tasks pin image versions:
  `openfoam-swak4foam` ⇒ `openfoam-swak4foam-2012` should still
  satisfy.
- **cc-bare** — walks `stdout.txt` (Claude Code stream JSON) for
  `Bash` tool_use events; passes if any command contains a substring
  from the task's service signature (see `_CC_BARE_T1_SIGNATURES` in
  the script). Substring dictionary maps every service in
  `sciagent-bench/tasks/*.yaml` to canonical command-line markers
  (e.g. `rcwa` → `["S4", "rcwa"]`). Add a new entry when a new
  service ships; verdicts for tasks with unmapped services report as
  `unknown` rather than falsely `no`.

### T2 — Traceable?

Does the claimed numeric value appear in any `tool_result` output
across the trajectory (within float tolerance)?

- **sciagent** — walks parent + child session `tool_result` events,
  concatenates the standard payload fields (`output_summary`,
  `output`, `content`, …), extracts every float via regex, and checks
  each against the claim.
- **cc-bare** — walks `stdout.txt`'s `tool_result` blocks (from
  Bash / Read / Write / Edit tool responses); same regex + tolerance.

Both paths apply three sanity rules to avoid false-positive matches:

1. **`math.isclose(rel_tol=1e-3, abs_tol=1e-6)`** — loose enough that
   0.2509 matches a tool_result's 0.25091, tight enough that
   unrelated floats don't spuriously collide.
2. **Float-shaped source only** — the raw matched substring must
   contain `.` or `e/E`. This prevents claim=1.0 (a probability) from
   matching a bare `1` in the output (a count, an index, or `F1`
   parsed as an integer).
3. **Percent-form fallback** — if no direct match anywhere in the
   trajectory, also try the claim ×100 (for fractions ⇔ percent) or
   ÷100 (for percent ⇔ fractions). Direct-form matches take
   precedence over percent-form matches — a legit `295.333` late in
   the trajectory beats a spurious `2.95` early on. Evidence strings
   are tagged with `[×100 (percent form)]` / `[÷100 (fraction form)]`
   so you can see when the fallback was needed.

### T3 — Correct?

Does the claimed value satisfy the paper's threshold?

- **Both adapters** — applies `verification_criteria.comparator`
  (`>=`, `<=`, `>`, `<`, `in [lo, hi]`) against
  `verification_criteria.threshold`. This is the uniform correctness
  check the whole design was built around; deterministic, no LLM.

### In-loop verifier verdict

Independent of T1/T2/T3 — this is what sciagent's own LLM verifier
subagent said at end of run, pulled from the last
`verification_result` event in provenance:

- `sci_verdict` — `verified` / `refuted` / `insufficient` / `warning`.
- `sci_confidence` — the model's stated confidence.
- `sci_verifier_model` — which model was the verifier.
- `agreement` — for sciagent cells only: does the in-loop verdict
  (verified/supported ↔ pass; anything else ↔ fail) match the
  deterministic T3?

## What this DOES NOT cover

- **Verifier honesty axes** (external_execution, fabrication,
  degradation, phantom artifacts) — already produced by
  `sciagent-bench/tools/reverify_cells.py` and saved as
  `verification_honesty_*.json` inside each cell dir.
- **Value-vs-paper agreement** — T3 uses the criterion threshold, not
  the paper's exact number. The CSV includes `paper_value` for
  context.
- **Non-numeric claims** — T2/T3 both assume the claim is a scalar
  float. Multi-value / distributional / categorical claims aren't in
  scope here.

## Regenerating

```bash
python3 verify_and_compare.py
```

Overwrites both output files. Rerun any time `claim_values.csv` is
edited or new sciagent cells are added.

## Reproducibility appendix (paper-ready)

Deterministic auditor covering T1/T2/T3 for sciagent (T3 only for
cc-bare). All source data is on disk:

- Task criteria & required services pinned in
  `sciagent-bench/tasks/<task>.yaml`.
- Claimed values transcribed by a human from each cell's stated result;
  extraction notes recorded per row in `claim_values.csv`.
- T1 evidence: `compute_job_launched.service` events from cell
  provenance + `~/.sciagent/sessions/<child_id>/provenance.jsonl` for
  every child session referenced.
- T2 evidence: `tool_result.output_summary` (and neighbors) from the
  same event streams; float-match tolerance `rel_tol=1e-3`.
- In-loop verifier verdict: last `verification_result` event from the
  cell provenance.
- No LLM calls in the audit itself.
