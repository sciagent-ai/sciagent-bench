#!/usr/bin/env bash
# Run a single sciagent cell into a chosen results timestamp dir.
#
# Why this exists: run_matrix.py needs a matrix file and a task; for a
# one-off cell on an existing matrix dir, this wrapper builds the matrix
# on the fly. Lets us drop a new cell into an existing results/<TS>/<task>/
# tree without editing the canonical matrices/ yaml.
#
# Designed for interactive TTY use so the sciagent adapter's `script(1)`
# wrapping fires (adapters/sciagent.py:359) — needed for any ask_user /
# DATA-gate prompt the agent might raise mid-run. Running this via a
# non-tty wrapper will fall into capture-only mode and HANG if the agent
# asks the user anything.
#
# Usage:
#   ./run_one_sciagent_cell.sh <cell_id> <recipe_path> [ts] [task]
#
# Examples:
#   # Recursive default verifier into the existing photonics TS dir:
#   ./run_one_sciagent_cell.sh \
#       photonics__sciagent-verifier-on-default__sonnet \
#       recipes/anthropic-single-family.yaml \
#       20260608T200907Z
#
#   # Cross-family verifier into the same TS dir:
#   ./run_one_sciagent_cell.sh \
#       photonics__sciagent-crossverifier__sonnet \
#       recipes/anthropic-cross-family-verifier.yaml \
#       20260608T200907Z
#
# Outputs land at:
#   results/<TS>/<task>/<cell_id>/{provenance.jsonl, cost_breakdown.csv, result.txt, project/}
#   results/<TS>/<task>/results.csv  (one row appended)

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <cell_id> <recipe_path> [ts] [task]" >&2
    echo "  ts defaults to a fresh UTC timestamp" >&2
    echo "  task defaults to 'photonics'" >&2
    exit 2
fi

CELL_ID="$1"
RECIPE="$2"
TS="${3:-$(date -u +%Y%m%dT%H%M%SZ)}"
TASK="${4:-photonics}"

# Resolve the bench root regardless of where the script was invoked from.
BENCH_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$BENCH_ROOT"

# Sanity-check the recipe path resolves against bench root.
if [[ ! -f "$BENCH_ROOT/$RECIPE" ]]; then
    echo "error: recipe not found at $BENCH_ROOT/$RECIPE" >&2
    exit 2
fi

# Derive the LLM from the recipe's agent.model field so callers don't
# have to remember to keep them in sync.
LLM=$(python3 -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))['agent']['model'])" "$BENCH_ROOT/$RECIPE")

MATRIX="$(mktemp -t sciagent_one_cell.XXXXXX).yaml"
trap 'rm -f "$MATRIX"' EXIT

cat > "$MATRIX" <<YAML
cells:
  - id: ${CELL_ID}
    task: ${TASK}
    adapter: sciagent
    adapter_config: {recipe: ${RECIPE}}
    llm: ${LLM}
YAML

echo "cell:   $CELL_ID"
echo "recipe: $RECIPE"
echo "llm:    $LLM"
echo "task:   $TASK"
echo "ts:     $TS"
echo "matrix: $MATRIX"
echo

# --skip-completed is defensive — re-running the same cell id won't redo
# work that's already in results.csv.
exec ./run_matrix.py \
    --task "$TASK" \
    --matrix "$MATRIX" \
    --ts "$TS" \
    --skip-completed
