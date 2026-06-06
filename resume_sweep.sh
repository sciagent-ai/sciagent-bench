#!/bin/bash
# Resume the photonics sweep in the existing results dir, skipping
# already-completed cells. Wraps the launch so terminal line-wrapping
# during paste can't drop the --skip-completed flag.
#
# Usage:  ./resume_sweep.sh
#
# Pre-conditions:
#   - venvtest activated
#   - ANTHROPIC_API_KEY in env (verifier needs it)
#   - BRAVE_SEARCH_API_KEY in env (sciagent's web tool)
#   - matrices/photonics_smoke.yaml has the cells you want to run

set -u
TS="20260605T203832Z"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY not in env. Export it and re-run." >&2
  exit 2
fi

exec caffeinate -dimsu ./run_matrix.py \
  --task photonics \
  --matrix matrices/photonics_smoke.yaml \
  --ts "$TS" \
  --skip-completed
