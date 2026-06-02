#!/usr/bin/env bash
# Thin wrapper — delegates to ../run.sh with task_id=dbaasp.
# Preserves the old `./smoke/dbaasp/run.sh [filter ...]` invocation.
exec "$(dirname "$0")/../run.sh" dbaasp "$@"
