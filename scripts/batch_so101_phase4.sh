#!/usr/bin/env bash
# Batch-run mimicanno annotate --target-phase 4 across SO101 episodes.
#
# Usage:
#   GPU=2 START=0  END=17 bash scripts/batch_so101_phase4.sh
#   GPU=3 START=18 END=35 bash scripts/batch_so101_phase4.sh
#
# Use CUDA_VISIBLE_DEVICES so each subprocess sees only its own physical GPU
# as cuda:0 — keeps the per-process model state simple.

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
GPU="${GPU:?must set GPU=<index>}"
START="${START:?must set START=<first episode>}"
END="${END:?must set END=<last episode (inclusive)>}"

DATA="$REPO/data/SO101"
GEMMA="/home/gayagaya/gemma_project/models/gemma-4-E4B-it"
SAM3="$REPO/sam3/checkpoints/sam3.pt"
ROBOT_CONFIG="$REPO/tests/exports/fixtures/so101_robot_config.yaml"

RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/so101_phase4}"
LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_so101}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"
BOUNDARY_CONFIG="${BOUNDARY_CONFIG:-}"
SMOOTHER_CONFIG="${SMOOTHER_CONFIG:-}"
mkdir -p "$RUNS_ROOT" "$LOGS_DIR" "$VLM_DUMP_ROOT"

EXTRA_ANNOTATE_ARGS=()
if [[ -n "$BOUNDARY_CONFIG" ]]; then
    EXTRA_ANNOTATE_ARGS+=(--boundary-config "$BOUNDARY_CONFIG")
fi
if [[ -n "$SMOOTHER_CONFIG" ]]; then
    EXTRA_ANNOTATE_ARGS+=(--smoother-config "$SMOOTHER_CONFIG")
fi

# Reproducibility: fake-but-stable 40-hex sha for the local Gemma path.
FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gemma-4-E4B-it-local').hexdigest())")
VLM_MODEL="${GEMMA}@${FAKE_SHA}"

echo "[gpu=$GPU] processing episodes $START..$END"
echo "[gpu=$GPU] runs_root=$RUNS_ROOT  logs=$LOGS_DIR"

cd "$REPO"
export CUDA_VISIBLE_DEVICES="$GPU"

for i in $(seq "$START" "$END"); do
    EP=$(printf "episode_%06d" "$i")
    VIDEO="$DATA/videos/chunk-000/observation.images.front/${EP}.mp4"
    PARQ="$DATA/data/chunk-000/${EP}.parquet"
    LOG="$LOGS_DIR/${EP}_gpu${GPU}.log"

    if [[ ! -f "$VIDEO" || ! -f "$PARQ" ]]; then
        echo "[gpu=$GPU] $EP: SKIP (missing video or parquet)"
        continue
    fi

    echo "[gpu=$GPU] $EP: starting at $(date +%H:%M:%S)"
    export MIMICANNO_VLM_DUMP_DIR="$VLM_DUMP_ROOT/$EP"
    if uv run mimicanno annotate \
        --video "$VIDEO" \
        --parquet "$PARQ" \
        --task "Put the tape into the bottle" \
        --robot generic \
        --robot-config "$ROBOT_CONFIG" \
        --target-phase 4 \
        --offline \
        --vlm-model "$VLM_MODEL" \
        --vlm-device cuda \
        --sam3-checkpoint "$SAM3" \
        --runs-root "$RUNS_ROOT" \
        "${EXTRA_ANNOTATE_ARGS[@]}" \
        > "$LOG" 2>&1; then
        echo "[gpu=$GPU] $EP: OK at $(date +%H:%M:%S)"
    else
        echo "[gpu=$GPU] $EP: FAIL (exit $?) — see $LOG"
    fi
done

echo "[gpu=$GPU] done at $(date +%H:%M:%S)"
