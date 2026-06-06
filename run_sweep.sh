#!/bin/bash
# Disconnect-safe matrix runner. Wraps run_matrix.py in:
#   - tmux: survives terminal close / SSH drop
#   - caffeinate: keeps the Mac awake (display, idle, disk, system)
# Resume via --ts <existing> --skip-completed if you need to restart.
#
# Usage (from sciagent-bench/):
#   ./run_sweep.sh --task photonics --matrix matrices/photonics_smoke.yaml
#   ./run_sweep.sh --task photonics --matrix matrices/photonics_smoke.yaml --ts 20260603T123456Z --skip-completed
#
# Detach from tmux:   Ctrl-b d
# Reattach:           tmux attach -t <session-name>  (printed below)
# List sessions:      tmux ls
set -u

TASK=""
MATRIX=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK="$2"; shift 2 ;;
    --matrix) MATRIX="$2"; shift 2 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

if [[ -z "$TASK" || -z "$MATRIX" ]]; then
  echo "Usage: $0 --task <task_id> --matrix <matrix.yaml> [--ts <ts>] [--skip-completed]" >&2
  exit 1
fi

# Fail fast on missing API key — the verifier step at the end of each
# cell needs ANTHROPIC_API_KEY in env to call litellm in-process.
# Without this check we'd discover the gap only after the agent has
# done its full ~60-90 min of work.
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY not exported in this shell." >&2
  echo "  The verifier step at cell-end will crash without it." >&2
  echo "  Fix: export ANTHROPIC_API_KEY=sk-ant-...  then re-run." >&2
  exit 2
fi

TS_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
SESSION="bench-${TASK}-${TS_TAG}"
LOG="run_sweep_${SESSION}.log"

BENCH_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Build the inner command. caffeinate keeps the Mac fully awake.
# ${EXTRA_ARGS[@]+...} avoids the unbound-variable error under set -u when
# the array is empty (no --ts / --skip-completed passed).
EXTRA_STR=""
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  EXTRA_STR="${EXTRA_ARGS[*]}"
fi
CMD="cd '$BENCH_ROOT' && caffeinate -dimsu ./run_matrix.py --task '$TASK' --matrix '$MATRIX' $EXTRA_STR 2>&1 | tee '$BENCH_ROOT/$LOG'"

if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session $SESSION already exists. Use a different timestamp or kill it: tmux kill-session -t $SESSION" >&2
    exit 1
  fi
  echo "Starting tmux session: $SESSION"
  echo "  detach: Ctrl-b d"
  echo "  reattach later: tmux attach -t $SESSION"
  echo "  watch log: tail -f $BENCH_ROOT/$LOG"
  echo "  list sessions: tmux ls"
  echo
  tmux new-session -d -s "$SESSION" "$CMD"
  echo "Attached: tmux attach -t $SESSION"
  exec tmux attach -t "$SESSION"
else
  echo "tmux not installed — falling back to nohup + caffeinate (disconnect kills it)."
  echo "Log: $BENCH_ROOT/$LOG"
  echo "PID will be printed below."
  nohup bash -c "$CMD" </dev/null >>"$LOG" 2>&1 &
  echo "PID: $!"
fi
