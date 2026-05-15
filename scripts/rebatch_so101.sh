#!/usr/bin/env bash
# SO101 再バッチ: fine-tuned 26B Unsloth QLoRA アダプタで全エピソード再実行。
#
# 必須環境: conda の unsloth_env (unsloth + mimicanno が両方入っている)
#
# Usage:
#   GPU=0 bash scripts/rebatch_so101.sh
#
#   # 2台 GPU で分割
#   GPU=0 START=0  END=17 bash scripts/rebatch_so101.sh &
#   GPU=1 START=18 END=35 bash scripts/rebatch_so101.sh

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
GPU="${GPU:?must set GPU=<index>}"
START="${START:-0}"
END="${END:-35}"

DATA="$REPO/data/SO101"
TASK="Put the tape into the bottle"
ROBOT_CONFIG="$REPO/tests/exports/fixtures/so101_robot_config.yaml"
RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/so101_26B}"
LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_so101_26B}"
ADAPTER="$REPO/models/gem4_26B_adapter"
SAM3="${SAM3:-$REPO/sam3/checkpoints/sam3.pt}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"

PYTHON=/home/gayagaya/anaconda3/envs/unsloth_env/bin/python

mkdir -p "$RUNS_ROOT" "$LOGS_DIR" "$VLM_DUMP_ROOT"

FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gem4-26B-adapter').hexdigest())")
VLM_MODEL="${ADAPTER}@${FAKE_SHA}"

echo "[gpu=$GPU] SO101 episodes $START..$END"
echo "[gpu=$GPU] adapter=$ADAPTER"
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
    if "$PYTHON" -m mimicanno.cli annotate \
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
        --force \
        > "$LOG" 2>&1; then
        echo "[gpu=$GPU] $EP: OK at $(date +%H:%M:%S)"
    else
        echo "[gpu=$GPU] $EP: FAIL (exit $?) — see $LOG"
    fi
done

echo "[gpu=$GPU] done at $(date +%H:%M:%S)"
