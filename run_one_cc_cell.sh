#!/usr/bin/env bash
# Run a single cc-bare (Claude Code) cell into a chosen results timestamp dir.
#
# Sister to run_one_sciagent_cell.sh — same idea, but for the cc-bare
# adapter (no recipe; sciagent-bench shells to `claude --print`).
#
# Designed for interactive TTY use so Claude Code's stream can echo to
# your terminal as it runs. Running this via a non-tty wrapper will fall
# back to capture-only mode.
#
# Usage:
#   ./run_one_cc_cell.sh <cell_id> <task> [ts] [with_sky] [with_registry]
#
# Examples:
#   # cfd_fig3_kde cc-bare into existing TS dir, no cluster:
#   ./run_one_cc_cell.sh \
#       cfd_fig3_kde__cc-bare__sonnet \
#       cfd_fig3_kde \
#       20260630T184838Z
#
#   # bioinformatics cc-bare with sky+registry (PyTorch GPU service):
#   ./run_one_cc_cell.sh \
#       bioinformatics__cc-bare__sonnet \
#       bioinformatics \
#       "" \
#       true true
#
# Environment overrides:
#   LLM=...   Override the model label written into results.csv
#             (default: anthropic/claude-sonnet-4-6). Doesn't change
#             which `claude` CLI binary runs — that's controlled by
#             whatever `claude` resolves to on PATH.
#
# Outputs land at:
#   results/<TS>/<task>/<cell_id>/{stdout.txt, cost_breakdown.csv, result.txt, project/}
#   results/<TS>/<task>/results.csv  (one row appended)

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <cell_id> <task> [ts] [with_sky] [with_registry]" >&2
    echo "  ts defaults to a fresh UTC timestamp" >&2
    echo "  with_sky / with_registry default to false (no cluster access)" >&2
    echo "  LLM env var overrides the model label (default anthropic/claude-sonnet-4-6)" >&2
    exit 2
fi

CELL_ID="$1"
TASK="$2"
TS="${3:-$(date -u +%Y%m%dT%H%M%SZ)}"
WITH_SKY="${4:-false}"
WITH_REGISTRY="${5:-false}"
LLM="${LLM:-anthropic/claude-sonnet-4-6}"

BENCH_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$BENCH_ROOT"

# Sanity-check the task YAML exists.
if [[ ! -f "$BENCH_ROOT/tasks/${TASK}.yaml" ]]; then
    echo "error: task spec not found at $BENCH_ROOT/tasks/${TASK}.yaml" >&2
    exit 2
fi

MATRIX="$(mktemp -t cc_one_cell.XXXXXX).yaml"
trap 'rm -f "$MATRIX"' EXIT

cat > "$MATRIX" <<YAML
cells:
  - id: ${CELL_ID}
    task: ${TASK}
    adapter: claude_code
    adapter_config: {with_sky: ${WITH_SKY}, with_registry: ${WITH_REGISTRY}}
    llm: ${LLM}
YAML

echo "cell:          $CELL_ID"
echo "task:          $TASK"
echo "ts:            $TS"
echo "with_sky:      $WITH_SKY"
echo "with_registry: $WITH_REGISTRY"
echo "llm:           $LLM"
echo "matrix:        $MATRIX"
echo

exec ./run_matrix.py \
    --task "$TASK" \
    --matrix "$MATRIX" \
    --ts "$TS" \
    --skip-completed
