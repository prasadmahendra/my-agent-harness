#!/usr/bin/env bash
# tools/run-cross-repo.sh — launch the cross_repo orchestrator.
#
# What this wrapper does:
#   - Export HARNESS_DIR so the orchestrator can locate tools/ (and thus
#     harness_repos.py / smoke.py) regardless of where it's run from.
#   - cd $HOME first so cwd-attached session state in a project subdir can't
#     attract an unintended resume. The orchestrator resolves all repo paths
#     from repos.yaml, independent of cwd.
#   - exec `omni run <agent-dir>` and forward all extra args.
#
# Runs persist in ~/.omnigent/chat.db, so --resume / --continue / `omni
# resume` all work after exit. Add --no-session to opt into ephemeral runs.
#
# Usage:
#   tools/run-cross-repo.sh                             # fresh REPL (persists)
#   tools/run-cross-repo.sh -p "task ..."              # one-shot
#   tools/run-cross-repo.sh -c                          # continue most recent
#   tools/run-cross-repo.sh --resume conv_abc          # resume a stored conv
#   tools/run-cross-repo.sh --no-session               # ephemeral
set -eu

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export HARNESS_DIR
AGENT_DIR="$HARNESS_DIR/agents/cross_repo"

if [[ ! -d "$AGENT_DIR" ]]; then
  echo "error: agent dir not found at $AGENT_DIR" >&2
  exit 1
fi

cd "$HOME"
exec omni run "$AGENT_DIR" "$@"
