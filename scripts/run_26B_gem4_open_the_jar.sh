#!/usr/bin/env bash
# GEM4 open_the_jar — 26B QLoRA アダプタで推論
# Usage:
#   GPU=0 bash scripts/run_26B_gem4_open_the_jar.sh
#   GPU=0 START=0   END=103 bash scripts/run_26B_gem4_open_the_jar.sh &
#   GPU=1 START=104 END=207 bash scripts/run_26B_gem4_open_the_jar.sh

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
GPU="${GPU:?must set GPU=<index>}"
START="${START:-0}"
END="${END:-207}"

DATA="$REPO/data/GEM4_open_the_jar"
TASK="Open the jar"
ROBOT_CONFIG="$REPO/mimicanno/configs/robot/gem4_open_the_jar_robot_config.yaml"
RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4_open_the_jar_26B}"
LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4_open_the_jar_26B}"
ADAPTER="$REPO/models/gem4_26B_adapter"
SAM3="${SAM3:-$REPO/sam3/checkpoints/sam3.pt}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"
PYTHON=/home/gayagaya/anaconda3/envs/unsloth_env/bin/python

mkdir -p "$RUNS_ROOT" "$LOGS_DIR" "$VLM_DUMP_ROOT"
FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gem4-26B-adapter').hexdigest())")
VLM_MODEL="${ADAPTER}@${FAKE_SHA}"

echo "[gpu=$GPU] GEM4 open_the_jar 26B  episodes $START..$END"
cd "$REPO"
export CUDA_VISIBLE_DEVICES="$GPU"
export PYTORCH_ALLOC_CONF=expandable_segments:True

for i in $(seq "$START" "$END"); do
    EP=$(printf "episode_%06d" "$i")
    VIDEO="$DATA/videos/observation.images.front/chunk-000/${EP}.mp4"
    PARQ="$DATA/data/chunk-000/${EP}.parquet"
    LOG="$LOGS_DIR/${EP}_gpu${GPU}.log"
    [[ ! -f "$VIDEO" || ! -f "$PARQ" ]] && echo "[gpu=$GPU] $EP: SKIP" && continue

    echo "[gpu=$GPU] $EP: start $(date +%H:%M:%S)"
    export MIMICANNO_VLM_DUMP_DIR="$VLM_DUMP_ROOT/$EP"
    if "$PYTHON" -m mimicanno.cli annotate \
        --video "$VIDEO" --parquet "$PARQ" \
        --task "$TASK" --robot generic --robot-config "$ROBOT_CONFIG" \
        --target-phase 4 --offline \
        --vlm-model "$VLM_MODEL" --vlm-device cuda \
        --sam3-checkpoint "$SAM3" --runs-root "$RUNS_ROOT" --force \
        > "$LOG" 2>&1; then
        echo "[gpu=$GPU] $EP: OK $(date +%H:%M:%S)"
    else
        echo "[gpu=$GPU] $EP: FAIL — see $LOG"
    fi
done
echo "[gpu=$GPU] done $(date +%H:%M:%S)"
