#!/usr/bin/env bash
# GEM4 — 4B Unsloth QLoRA アダプタで推論 (thin wrapper around batch_annotate_4B.py).
#
# Loads the 4B QLoRA-fine-tuned adapter once via Unsloth and reuses it
# across episodes. Faster than 26B but precision-tuned on the same
# phase-label task. Outputs land at `runs/gem4_<task>_4B/`.
#
# Requires: `unsloth_env` conda env, the 4B adapter at
# `models/gem4_4B_adapter/` (override via ADAPTER env var). Set
# `ADAPTER=` (empty) to skip the adapter and run the base Gemma 4 E4B-it.
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
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# Resolve unsloth_env python without hardcoding $HOME or $USER.
# 1. Honor an explicit UNSLOTH_PY override.
# 2. Use the currently-active conda env if it's unsloth_env.
# 3. Probe standard $HOME conda env paths.
# 4. Fail fast with an actionable error.
if [[ -z "${UNSLOTH_PY:-}" ]]; then
    if [[ "${CONDA_DEFAULT_ENV:-}" == "unsloth_env" && -x "${CONDA_PREFIX:-}/bin/python" ]]; then
        UNSLOTH_PY="$CONDA_PREFIX/bin/python"
    fi
fi
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
# ADAPTER unset → default to the 4B adapter dir. ADAPTER= (empty) → base model.
ADAPTER="${ADAPTER-$REPO/models/gem4_4B_adapter}"

cd "$REPO"

# Route output to `runs/gem4_<task>_4B/` instead of the 26B default.
export BATCH_RUNS_ROOT="${BATCH_RUNS_ROOT:-$REPO/runs/gem4_${TASK_KEY}_4B}"

args=(--dataset "gem4_${TASK_KEY}" --gpu "$GPU")
[[ -n "$ADAPTER" ]] && args+=(--adapter "$ADAPTER")
[[ -n "${START:-}" ]] && args+=(--start "$START")
[[ -n "${END:-}"   ]] && args+=(--end   "$END")

exec "$PYTHON" scripts/batch_annotate_4B.py "${args[@]}"
