#!/usr/bin/env bash
# GEM4 再バッチ: gripper 正規化修正後の robot-config で上書き実行。
#
# 問題: SO101 用 robot-config (scale_min=0, max=60) を GEM4 に流用したため
#   gripper 信号が全フレーム 0.0 に clip されていた。
#   → boundaries.detect_gripper_delta_peaks 不発、clip_features 常に 0
#
# 修正: GEM4 実測レンジで個別 robot-config を作成 (2026-05-16)
#   gem4_pick_up_bottle    : scale_min=-5.25, scale_max=0.0
#   gem4_replace_the_cookie: scale_min=-6.0,  scale_max=6.5
#
# Usage:
#   # GEM4_pick_up_bottle を GPU0 で全エピソード再実行
#   GPU=0 bash scripts/rebatch_gem4.sh pick_up_bottle
#
#   # GEM4_replace_the_cookie を GPU0 で全エピソード再実行
#   GPU=0 bash scripts/rebatch_gem4.sh replace_the_cookie
#
#   # 2台 GPU で分割
#   GPU=0 START=3   END=153 bash scripts/rebatch_gem4.sh pick_up_bottle &
#   GPU=1 START=154 END=303 bash scripts/rebatch_gem4.sh pick_up_bottle

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
TARGET="${1:?must pass 'pick_up_bottle' or 'replace_the_cookie'}"
GPU="${GPU:?must set GPU=<index>}"

case "$TARGET" in
  pick_up_bottle)
    DATA="$REPO/data/GEM4_pick_up_bottle"
    TASK="Pick up the bottle"
    ROBOT_CONFIG="$REPO/mimicanno/configs/robot/gem4_pick_up_bottle_robot_config.yaml"
    RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4_pick_up_bottle}"
    LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4_pick_up}"
    START="${START:-3}"
    END="${END:-303}"
    ;;
  replace_the_cookie)
    DATA="$REPO/data/GEM4_replace_the_cookie"
    TASK="Replace the cookie"
    ROBOT_CONFIG="$REPO/mimicanno/configs/robot/gem4_replace_the_cookie_robot_config.yaml"
    ROBOT_CONFIG_OFFSET="$REPO/mimicanno/configs/robot/gem4_replace_the_cookie_offset_robot_config.yaml"
    RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/gem4_replace_the_cookie}"
    LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_gem4_cookie}"
    START="${START:-0}"
    END="${END:-300}"
    ;;
  *)
    echo "Unknown target: $TARGET. Use 'pick_up_bottle' or 'replace_the_cookie'." >&2
    exit 1
    ;;
esac

GEMMA="${GEMMA:-/home/gayagaya/gemma_project/models/gemma-4-E4B-it}"
SAM3="${SAM3:-$REPO/sam3/checkpoints/sam3.pt}"
VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"

mkdir -p "$RUNS_ROOT" "$LOGS_DIR" "$VLM_DUMP_ROOT"

FAKE_SHA=$(python3 -c "import hashlib; print(hashlib.sha1(b'gemma-4-E4B-it-local').hexdigest())")
VLM_MODEL="${GEMMA}@${FAKE_SHA}"

echo "[gpu=$GPU] target=$TARGET  episodes $START..$END"
echo "[gpu=$GPU] robot_config=$ROBOT_CONFIG"
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

    # ep030-114 は gripper ゼロ点が -2π ズレているのでオフセット用 config を使う
    EFFECTIVE_ROBOT_CONFIG="$ROBOT_CONFIG"
    if [[ -n "${ROBOT_CONFIG_OFFSET:-}" && "$i" -ge 30 && "$i" -le 114 ]]; then
        EFFECTIVE_ROBOT_CONFIG="$ROBOT_CONFIG_OFFSET"
    fi

    echo "[gpu=$GPU] $EP: starting at $(date +%H:%M:%S) (robot_config=$(basename $EFFECTIVE_ROBOT_CONFIG))"
    export MIMICANNO_VLM_DUMP_DIR="$VLM_DUMP_ROOT/$EP"
    if uv run mimicanno annotate \
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
