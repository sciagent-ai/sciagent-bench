# icml_results/analysis

Paper-specific analysis scripts for `icml_results/`. Ported from
`sciagent-bench/results/20260608T200907Z/photonics/performance/analyze_performance.py`
(the two-cell hand-tuned analyzer). Same per-cell rollup logic; the
orchestration around it is parameterized + generalized.

## Scripts

**`analyze_pair.py`** — one (cc-bare, sciagent) pair → one report dir. Direct
port of `analyze_performance.py`; produces the same SUMMARY.md +
supporting CSVs, just with `--cc-dir`, `--sci-dir`, `--out-dir` args
instead of hardcoded `ROOT`. Regression-tested against the historical
2026-06-08 photonics output.

```bash
python3 analyze_pair.py \
    --cc-dir  ../20260608T200907Z/photonics/photonics__cc-bare__sonnet \
    --sci-dir ../20260630T120254Z/photonics/photonics__sciagent-verifier-on-default__sonnet \
    --out-dir ../reports/photonics_default_pair
```

**`analyze_photonics_all.py`** — sweeps every photonics cell across
`icml_results/*/photonics/`. Discovers by directory listing; classifies
adapter by `__sciagent` substring in cell id (same rule reverify uses).
Produces one wide comparison table (`photonics_all.md` + `.csv`).

```bash
python3 analyze_photonics_all.py
# → reports/photonics_all.{md,csv}
```

**`compare_cc_vs_sciagent.py`** — 6-cell cross-task comparison:
photonics / brca1_fitness_structure / cfd_fig3_kde × (cc-bare,
sciagent-verifier-on-default). Cell pointers hardcoded (`_CELLS` list at
top of file) because the six cells live across four TS dirs; explicit
list beats path-globbing when the paper claim is "these six exact
cells."

```bash
python3 compare_cc_vs_sciagent.py
# → reports/cc_vs_sciagent_default.{md,csv}
```

## Accounting model

Same as the parent bench:

- **cc-bare** LLM cost / tokens / iterations pulled from
  `stdout.txt`'s Claude Code session JSON (`total_cost_usd`,
  `duration_ms`, `num_turns`, `input_tokens`, etc.).
- **sciagent** LLM cost / tokens / iterations recursively walk the
  parent `provenance.jsonl` plus every child session referenced via
  `subagent_completed.child_session_id`. Without recursion, subagent
  spend is under-counted by ~5×.
- **Compute cost** for sciagent runs comes from `sky.cost_report()` for
  the cluster referenced by the first `compute_job_launched` event.
  Empty for tasks that stayed local (no cluster).

## Assumptions worth knowing

1. `~/.sciagent/sessions/<child_session_id>/provenance.jsonl` must still
   exist on the machine running the analyzer. If a session was garbage
   collected, the subagent walk for that cell will under-count.
2. Cell classification is by cell-id substring. Cells that don't follow
   `photonics__<condition>__<llm>` won't be picked up by the sweep.
3. `sky` must be importable for compute-cost lookup. If not, the field
   silently reports $0 for that cell (`_sky_cluster_cost` returns
   `{"error": ...}`).

## Regenerating reports

All three scripts overwrite their output files. Rerun anytime a new cell
lands under `icml_results/`. For `compare_cc_vs_sciagent.py`, edit the
`_CELLS` list to add / remove rows.
