#!/usr/bin/env bash
# Batch-run mimicanno annotate --target-phase 4 across GEM4 episodes.
#
# Generic LeRobot v3 batcher — pass DATA / TASK / RUNS_ROOT as env vars.
# Same shape as batch_so101_phase4.sh but with DATA + TASK externalized so
# both GEM4_pick_up_bottle and GEM4_replace_the_cookie can reuse it.
#
# Usage examples:
#   # GEM4_pick_up_bottle (episodes 3..303)
#   GPU=0 START=3 END=303 \
#     DATA=/misc/dl00/gayagaya/MimicAnno/data/GEM4_pick_up_bottle \
#     TASK="Pick up the bottle" \
#     RUNS_ROOT=/misc/dl00/gayagaya/MimicAnno/runs/gem4_pick_up_bottle \
#     LOGS_DIR=/misc/dl00/gayagaya/MimicAnno/logs/batch_gem4_pick_up \
#     bash scripts/batch_gem4.sh
#
#   # GEM4_replace_the_cookie (episodes 0..300)
#   GPU=0 START=0 END=300 \
#     DATA=/misc/dl00/gayagaya/MimicAnno/data/GEM4_replace_the_cookie \
#     TASK="Replace the cookie" \
#     RUNS_ROOT=/misc/dl00/gayagaya/MimicAnno/runs/gem4_replace_the_cookie \
#     LOGS_DIR=/misc/dl00/gayagaya/MimicAnno/logs/batch_gem4_cookie \
#     bash scripts/batch_gem4.sh

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
GPU="${GPU:?must set GPU=<index>}"
START="${START:?must set START=<first episode>}"
END="${END:?must set END=<last episode (inclusive)>}"
DATA="${DATA:?must set DATA=<dataset root containing data/ videos/ meta/>}"
TASK="${TASK:?must set TASK=<task instruction text>}"

GEMMA="${GEMMA:-/home/gayagaya/gemma_project/models/gemma-4-E4B-it}"
SAM3="${SAM3:-$REPO/sam3/checkpoints/sam3.pt}"
ROBOT="${ROBOT:-generic}"
ROBOT_CONFIG="${ROBOT_CONFIG:-$REPO/tests/exports/fixtures/so101_robot_config.yaml}"

RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4}"
LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"
BOUNDARY_CONFIG="${BOUNDARY_CONFIG:-}"
SMOOTHER_CONFIG="${SMOOTHER_CONFIG:-}"
TARGET_PHASE="${TARGET_PHASE:-4}"

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

echo "[gpu=$GPU] dataset=$DATA"
echo "[gpu=$GPU] task=\"$TASK\""
echo "[gpu=$GPU] processing episodes $START..$END"
echo "[gpu=$GPU] runs_root=$RUNS_ROOT  logs=$LOGS_DIR"

cd "$REPO"
export CUDA_VISIBLE_DEVICES="$GPU"

for i in $(seq "$START" "$END"); do
    EP=$(printf "episode_%06d" "$i")
    VIDEO="$DATA/videos/observation.images.front/chunk-000/${EP}.mp4"
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
        --robot "$ROBOT" \
        --robot-config "$ROBOT_CONFIG" \
        --target-phase "$TARGET_PHASE" \
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
