#!/usr/bin/env bash
# GEM4 — 26B Unsloth QLoRA アダプタで推論 (thin wrapper around batch_annotate.py).
#
# Loads the 26B QLoRA-fine-tuned adapter once via Unsloth and reuses
# it across episodes. Higher quality than 4B but slower; outputs land
# at `runs/gem4_<task>_26B/`.
#
# Requires: `unsloth_env` conda env, the 26B adapter at
# `models/gem4_26B_adapter/` (override via ADAPTER env var).
#
# Usage:
#   GPU=0 bash scripts/run_26B_gem4.sh <task>
#   GPU=0 START=0  END=151 bash scripts/run_26B_gem4.sh pick_up_bottle &
#   GPU=1 START=152 END=303 bash scripts/run_26B_gem4.sh pick_up_bottle
#
# Tasks: open_the_jar | pick_up_bottle | replace_the_cookie

set -euo pipefail

TASK_KEY="${1:?Usage: $0 <open_the_jar|pick_up_bottle|replace_the_cookie>}"
case "$TASK_KEY" in
    open_the_jar|pick_up_bottle|replace_the_cookie) ;;
    *) echo "unknown task: $TASK_KEY" >&2; exit 2 ;;
esac

GPU="${GPU:?must set GPU=<index>}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Resolve unsloth_env python without hardcoding $HOME or $USER.
if [[ -z "${UNSLOTH_PY:-}" ]]; then
    for candidate in \
        "$HOME/anaconda3/envs/unsloth_env/bin/python" \
        "$HOME/miniconda3/envs/unsloth_env/bin/python" \
        "$HOME/miniforge3/envs/unsloth_env/bin/python" \
        "$HOME/.conda/envs/unsloth_env/bin/python"; do
        if [[ -x "$candidate" ]]; then
            UNSLOTH_PY="$candidate"
            break
        fi
    done
fi
if [[ -z "${UNSLOTH_PY:-}" || ! -x "${UNSLOTH_PY:-}" ]]; then
    echo "error: unsloth_env python not found." >&2
    echo "       Create the env per README, or set UNSLOTH_PY=/path/to/python" >&2
    exit 1
fi
PYTHON="$UNSLOTH_PY"
ADAPTER="${ADAPTER:-$REPO/models/gem4_26B_adapter}"

cd "$REPO"

export BATCH_RUNS_ROOT="${BATCH_RUNS_ROOT:-$REPO/runs/gem4_${TASK_KEY}_26B}"

args=(--dataset "gem4_${TASK_KEY}" --gpu "$GPU" --adapter "$ADAPTER")
[[ -n "${START:-}" ]] && args+=(--start "$START")
[[ -n "${END:-}"   ]] && args+=(--end   "$END")

exec "$PYTHON" scripts/batch_annotate.py "${args[@]}"
