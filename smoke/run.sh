#!/usr/bin/env bash
# Shared smoke runner — one task, four (or N) provider recipes.
#
# Usage:
#   ./smoke/run.sh <task_id> [recipe_filter ...]
#
# Examples:
#   ./smoke/run.sh dbaasp                       # all four recipes on dbaasp
#   ./smoke/run.sh dbaasp xai                   # only xai cell
#   ./smoke/run.sh dbaasp anthropic openai      # two cells
#   ./smoke/run.sh code_fix                     # when you add a code_fix task
#
# Per-task layout:
#   smoke/<task_id>/
#     task.txt          one-line prompt the agent receives
#     results/<TS>/     per-run artifacts (gitignored)
#
# Cost (DBAASP at mid-tier recipes): ~$1-3 per provider; ~$10-15 total full.

set -u

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <task_id> [recipe_filter ...]" >&2
  exit 1
fi

TASK_ID="$1"
shift

BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCIAGENT_ROOT="$BENCH_ROOT/../sciagent-cli"
ROLLUP="$SCIAGENT_ROOT/scripts/cost_rollup.py"
TASK_DIR="$BENCH_ROOT/smoke/$TASK_ID"
TASK_FILE="$TASK_DIR/task.txt"

if [[ ! -f "$TASK_FILE" ]]; then
  echo "Task not found: $TASK_FILE" >&2
  echo "Expected layout: smoke/$TASK_ID/task.txt" >&2
  exit 1
fi

TASK_PROMPT="$(cat "$TASK_FILE")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$TASK_DIR/results/$TS"
mkdir -p "$OUT_DIR"

# Recipe roster. All single-family today; ablation variants slot in later.
ALL_RECIPES=(
  anthropic-single-family
  openai-single-family
  gemini-single-family
  xai-single-family
)

if [[ $# -gt 0 ]]; then
  RECIPES=()
  for filter in "$@"; do
    for r in "${ALL_RECIPES[@]}"; do
      if [[ "$r" == *"$filter"* ]]; then
        RECIPES+=("$r")
      fi
    done
  done
  if [[ ${#RECIPES[@]} -eq 0 ]]; then
    echo "No recipes match filter(s): $*" >&2
    echo "Available: ${ALL_RECIPES[*]}" >&2
    exit 1
  fi
else
  RECIPES=("${ALL_RECIPES[@]}")
fi

SUMMARY_CSV="$OUT_DIR/summary.csv"
echo "recipe,status,iterations,tool_calls,verifier_verdict,verifier_confidence,tokens_in,tokens_out,cost_usd,wall_seconds,log_path" > "$SUMMARY_CSV"

echo "$TASK_ID smoke — $TS"
echo "Task: $TASK_PROMPT"
echo "Results: $OUT_DIR"
echo

for recipe_name in "${RECIPES[@]}"; do
  echo "=== $recipe_name ==="
  recipe="$BENCH_ROOT/recipes/$recipe_name.yaml"
  cell_dir="$OUT_DIR/$recipe_name"
  pdir="$cell_dir/project"
  mkdir -p "$pdir"

  if [[ ! -f "$recipe" ]]; then
    echo "  recipe missing: $recipe"
    echo "$recipe_name,FAIL,0,0,0,0,0.0000,0,none" >> "$SUMMARY_CSV"
    echo
    continue
  fi

  prev_log="$(ls -t ~/.sciagent/sessions/*/provenance.jsonl 2>/dev/null | head -1)"
  t_start=$(date +%s)

  status="OK"
  if ! sciagent run --config "$recipe" --project-dir "$pdir" "$TASK_PROMPT" 2>&1 | tee "$cell_dir/stdout.txt"; then
    status="FAIL"
  fi

  t_end=$(date +%s)
  wall=$((t_end - t_start))

  new_log="$(ls -t ~/.sciagent/sessions/*/provenance.jsonl 2>/dev/null | head -1)"
  tool_calls=0
  tokens_in=0
  tokens_out=0
  cost="0.0000"
  iterations=0
  log_field="none"
  verifier_verdict="none"
  verifier_confidence="0.00"

  if [[ -n "$new_log" && "$new_log" != "$prev_log" ]]; then
    cp "$new_log" "$cell_dir/provenance.jsonl"
    log_field="$new_log"
    tool_calls=$(grep -c '"event_kind": "tool_call"' "$new_log" 2>/dev/null || echo 0)
    iterations=$(grep -oE 'Completed in [0-9]+ iterations' "$cell_dir/stdout.txt" | grep -oE '[0-9]+' | head -1)
    iterations=${iterations:-0}
    read tokens_in tokens_out cost < <(
      python "$ROLLUP" "$new_log" 2>/dev/null \
        | awk -F',' 'NR>1 {tin+=$5; tout+=$6; cost+=$7}
                     END {printf "%d %d %.4f\n", tin+0, tout+0, cost+0}'
    )
    # Extract the LAST verification_result event from the session log.
    # Shape (per H3 + §5.4.b): { verdict: "verified"|"refuted"|"insufficient", confidence: 0.0-1.0, ... }
    read verifier_verdict verifier_confidence < <(
      grep '"event_kind": "verification_result"' "$new_log" 2>/dev/null | tail -1 \
        | python -c "import sys, json
try:
    e = json.loads(sys.stdin.read() or '{}')
    print(e.get('verdict') or 'unknown', f\"{float(e.get('confidence', 0.0)):.2f}\")
except Exception:
    print('parse_error 0.00')" 2>/dev/null
    )
    verifier_verdict="${verifier_verdict:-none}"
    verifier_confidence="${verifier_confidence:-0.00}"
  fi

  # Extract the agent's final "Result:" block (everything after the literal
  # line "Result:" until end of stdout). No interpretation — just verbatim
  # what the agent said, for side-by-side comparison in summary.md.
  awk '/^Result:$/{found=1; next} found' "$cell_dir/stdout.txt" > "$cell_dir/result.txt"

  echo "  → status=$status iter=$iterations tool_calls=$tool_calls verifier=$verifier_verdict@$verifier_confidence tokens_in=$tokens_in tokens_out=$tokens_out cost=\$$cost wall=${wall}s"
  echo "  artifacts: $cell_dir"
  echo "$recipe_name,$status,$iterations,$tool_calls,$verifier_verdict,$verifier_confidence,$tokens_in,$tokens_out,$cost,$wall,$log_field" >> "$SUMMARY_CSV"
  echo
done

# Markdown summary (metrics table + each cell's verbatim Result block).
{
  echo "# $TASK_ID smoke — $TS"
  echo
  echo "**Task:** $TASK_PROMPT"
  echo
  echo "## Metrics"
  echo
  echo "| Recipe | Status | Iter | ToolCalls | Verifier | Conf | TokensIn | TokensOut | Cost USD | Wall s |"
  echo "|---|---|---|---|---|---|---|---|---|---|"
  tail -n +2 "$SUMMARY_CSV" | while IFS=',' read -r recipe_name status iter tools verdict conf tin tout cost wall log; do
    printf "| %s | %s | %s | %s | %s | %s | %s | %s | \$%s | %s |\n" \
      "$recipe_name" "$status" "$iter" "$tools" "$verdict" "$conf" "$tin" "$tout" "$cost" "$wall"
  done
  echo
  echo "## Results per cell (verbatim)"
  echo
  for recipe_name in "${RECIPES[@]}"; do
    cell_dir="$OUT_DIR/$recipe_name"
    echo "### $recipe_name"
    echo
    if [[ -s "$cell_dir/result.txt" ]]; then
      cat "$cell_dir/result.txt"
    else
      echo "_(no Result block found in stdout — run may have failed before completion)_"
    fi
    echo
  done
  echo
  echo "Artifacts per cell: \`$OUT_DIR/<recipe>/\` — \`stdout.txt\`, \`provenance.jsonl\`, \`project/\`, \`result.txt\`."
} | tee "$OUT_DIR/summary.md"

echo
echo "Results saved to: $OUT_DIR"
echo "  - summary.csv (machine-readable)"
echo "  - summary.md  (metrics + verbatim Result blocks side by side)"
echo "  - <recipe>/stdout.txt + provenance.jsonl + project/ + result.txt"
