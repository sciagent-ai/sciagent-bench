# sciagent-bench

Benchmark + evaluation harness for [sciagent-cli](../sciagent-cli/), kept in a separate repo per `DESIGN_BENCH.md` §1.1.

The seam between the two repos is the CLI surface + provenance log v2 schema — **no `from sciagent.*` imports here.**

## Recipe naming convention

Each YAML under `recipes/` is one ablation cell. The filename names the axes being varied; everything not in the filename is held at sciagent default.

Current recipes (one per provider, all other axes at default):

```
recipes/
  anthropic-single-family.yaml    all four role models on Anthropic; gates ON; same-family verifier
  openai-single-family.yaml       all four role models on OpenAI
  gemini-single-family.yaml       all four role models on Gemini
  xai-single-family.yaml          all four role models on xAI Grok
```

Future ablation cells slot in with the same `<provider>-<variant>.yaml` shape:

```
recipes/
  <provider>-cross-family-verifier.yaml    main on <provider>, verifier on a different family
  <provider>-no-verifier.yaml              enable_verification: false
  <provider>-no-data-gate.yaml             enable_data_gate: false
  <provider>-raw.yaml                      all three gates off
```

The bench owns recipe naming (per `feedback_bench_owns_recipes.md` memory); sciagent just exposes the config knobs each recipe sets.

## Layout

```
recipes/                  per-cell config YAMLs
smoke/                    cheap pre-paper validation runs
  run.sh                  shared runner: ./smoke/run.sh <task_id> [filter ...]
  dbaasp/
    task.txt              the prompt the agent receives
    run.sh                thin wrapper preserving ./smoke/dbaasp/run.sh
    results/<TS>/         per-run artifacts (gitignored)
      summary.csv         metrics, machine-readable
      summary.md          metrics table + each cell's verbatim "Result:" block
      <recipe>/
        stdout.txt        full sciagent output
        provenance.jsonl  copy of the session log
        project/          the agent's workdir for this cell
        result.txt        verbatim "Result:" block from stdout
```

## Quick start — cross-provider DBAASP smoke

```
./smoke/dbaasp/run.sh              # all four recipes
./smoke/run.sh dbaasp xai          # only the xai cell
./smoke/run.sh dbaasp anthropic openai   # two cells
```

Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `BRAVE_SEARCH_API_KEY` exported in the shell. Missing keys → that row shows FAIL; loop continues.

`summary.md` includes a metrics table AND each cell's verbatim `Result:` block side by side, so you can read "anthropic produced 10 peptides" next to "xai gave up at 403" without opening four stdout files. The Result blocks are uninterpreted — no validator, no judgment — just what the agent itself said.

## Adding a new smoke task

```
mkdir smoke/<task_id>
echo "your one-line prompt here" > smoke/<task_id>/task.txt
./smoke/run.sh <task_id>
```

Optionally drop a 2-line `smoke/<task_id>/run.sh` wrapper if you want the per-task invocation pattern:

```bash
#!/usr/bin/env bash
exec "$(dirname "$0")/../run.sh" <task_id> "$@"
```

All tasks share the same recipe roster, the same metrics extraction, and the same summary format. Per-task results stay isolated under `smoke/<task_id>/results/<UTC-timestamp>/`.
