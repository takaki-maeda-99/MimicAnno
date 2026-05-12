#!/usr/bin/env bash
# Phase 4 batch over the LegrandFrederic/Marker_pickup_piper dataset.
# Mirrors scripts/batch_so101_phase4.sh: SO101's pattern of CUDA_VISIBLE_DEVICES
# per-process, START/END range, single GPU per process. Run two of these in
# parallel on free GPUs to cover all 39 eps.
#
# Usage (run both in parallel, e.g. in two terminals or via tee):
#   GPU=1 START=0  END=19 bash scripts/batch_piper_phase4.sh
#   GPU=3 START=20 END=38 bash scripts/batch_piper_phase4.sh

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
GPU="${GPU:?must set GPU=<index>}"
START="${START:?must set START=<first episode>}"
END="${END:?must set END=<last episode (inclusive)>}"

DATA="$REPO/data/Piper"
GEMMA="/home/gayagaya/gemma_project/models/gemma-4-E4B-it"
SAM3="$REPO/sam3/checkpoints/sam3.pt"
ROBOT_CONFIG="$REPO/mimicanno/configs/robot/piper_robot_config.yaml"
TASK="Pick up the marker and place it"

RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/piper_phase4}"
LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_piper}"
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

FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gemma-4-E4B-it-local').hexdigest())")
VLM_MODEL="${GEMMA}@${FAKE_SHA}"

echo "[gpu=$GPU] processing piper episodes $START..$END"
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
        --task "$TASK" \
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
