#!/usr/bin/env bash
# GEM4 — 4B Unsloth QLoRA アダプタで推論 (thin wrapper around batch_annotate.py).
#
# Loads the 4B QLoRA-fine-tuned adapter once via Unsloth and reuses it
# across episodes. Faster than 26B but precision-tuned on the same
# phase-label task. Outputs land at `runs/gem4_<task>_4B/`.
#
# Requires: `unsloth_env` conda env, the 4B adapter at
# `models/gem4_4B_adapter/` (override via ADAPTER env var).
#
# Usage:
#   GPU=0 bash scripts/run_4B_gem4.sh <task>
#   GPU=0 START=0 END=103 bash scripts/run_4B_gem4.sh open_the_jar &
#   GPU=1 START=104 END=207 bash scripts/run_4B_gem4.sh open_the_jar
#
# Tasks: open_the_jar | pick_up_bottle | replace_the_cookie

set -euo pipefail

TASK_KEY="${1:?Usage: $0 <open_the_jar|pick_up_bottle|replace_the_cookie>}"
case "$TASK_KEY" in
    open_the_jar|pick_up_bottle|replace_the_cookie) ;;
    *) echo "unknown task: $TASK_KEY" >&2; exit 2 ;;
esac

GPU="${GPU:?must set GPU=<index>}"
REPO=/misc/dl00/gayagaya/MimicAnno
PYTHON=/home/gayagaya/anaconda3/envs/unsloth_env/bin/python
ADAPTER="${ADAPTER:-$REPO/models/gem4_4B_adapter}"

cd "$REPO"

# Route output to `runs/gem4_<task>_4B/` instead of the 26B default.
export BATCH_RUNS_ROOT="${BATCH_RUNS_ROOT:-$REPO/runs/gem4_${TASK_KEY}_4B}"

args=(--dataset "gem4_${TASK_KEY}" --gpu "$GPU" --adapter "$ADAPTER")
[[ -n "${START:-}" ]] && args+=(--start "$START")
[[ -n "${END:-}"   ]] && args+=(--end   "$END")

exec "$PYTHON" scripts/batch_annotate.py "${args[@]}"
