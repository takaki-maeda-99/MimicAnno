#!/usr/bin/env bash
# GEM4 再バッチ (26B Unsloth QLoRA アダプタ版)
#
# 必須環境: conda の unsloth_env
#
# Usage:
#   GPU=0 bash scripts/rebatch_gem4_26B.sh pick_up_bottle
#   GPU=1 bash scripts/rebatch_gem4_26B.sh replace_the_cookie
#
#   # 2台 GPU で分割
#   GPU=0 START=3   END=153 bash scripts/rebatch_gem4_26B.sh pick_up_bottle &
#   GPU=1 START=154 END=303 bash scripts/rebatch_gem4_26B.sh pick_up_bottle

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
TARGET="${1:?must pass 'pick_up_bottle' or 'replace_the_cookie'}"
GPU="${GPU:?must set GPU=<index>}"

case "$TARGET" in
  pick_up_bottle)
    DATA="$REPO/data/GEM4_pick_up_bottle"
    TASK="Pick up the bottle"
    ROBOT_CONFIG="$REPO/mimicanno/configs/robot/gem4_pick_up_bottle_robot_config.yaml"
    RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4_pick_up_bottle_26B}"
    LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4_pick_up_26B}"
    START="${START:-3}"
    END="${END:-303}"
    ;;
  replace_the_cookie)
    DATA="$REPO/data/GEM4_replace_the_cookie"
    TASK="Replace the cookie"
    ROBOT_CONFIG="$REPO/mimicanno/configs/robot/gem4_replace_the_cookie_robot_config.yaml"
    ROBOT_CONFIG_OFFSET="$REPO/mimicanno/configs/robot/gem4_replace_the_cookie_offset_robot_config.yaml"
    RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4_replace_the_cookie_26B}"
    LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4_cookie_26B}"
    START="${START:-0}"
    END="${END:-300}"
    ;;
  *)
    echo "Unknown target: $TARGET. Use 'pick_up_bottle' or 'replace_the_cookie'." >&2
    exit 1
    ;;
esac

ADAPTER="$REPO/models/gem4_26B_adapter"
SAM3="${SAM3:-$REPO/sam3/checkpoints/sam3.pt}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"

PYTHON=/home/gayagaya/anaconda3/envs/unsloth_env/bin/python

mkdir -p "$RUNS_ROOT" "$LOGS_DIR" "$VLM_DUMP_ROOT"

FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gem4-26B-adapter').hexdigest())")
VLM_MODEL="${ADAPTER}@${FAKE_SHA}"

echo "[gpu=$GPU] target=$TARGET  episodes $START..$END"
echo "[gpu=$GPU] adapter=$ADAPTER"
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

    EFFECTIVE_ROBOT_CONFIG="$ROBOT_CONFIG"
    if [[ -n "${ROBOT_CONFIG_OFFSET:-}" && "$i" -ge 30 && "$i" -le 114 ]]; then
        EFFECTIVE_ROBOT_CONFIG="$ROBOT_CONFIG_OFFSET"
    fi

    echo "[gpu=$GPU] $EP: starting at $(date +%H:%M:%S) (robot_config=$(basename $EFFECTIVE_ROBOT_CONFIG))"
    export MIMICANNO_VLM_DUMP_DIR="$VLM_DUMP_ROOT/$EP"
    if "$PYTHON" -m mimicanno.cli annotate \
        --video "$VIDEO" \
        --parquet "$PARQ" \
        --task "$TASK" \
        --robot generic \
        --robot-config "$EFFECTIVE_ROBOT_CONFIG" \
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
