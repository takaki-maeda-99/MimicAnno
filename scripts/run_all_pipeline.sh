#!/bin/bash
# Full pipeline (Phase A + Phase B) for fisheye videos.
#
# Usage:
#   bash scripts/run_all_pipeline.sh [OPTIONS] [VIDEO_NAME ...]
#
# Examples:
#   # All fisheye videos in data/video/new/ (auto-detect 2704x1520)
#   bash scripts/run_all_pipeline.sh
#
#   # Specific videos only
#   bash scripts/run_all_pipeline.sh GX010175 GX010176
#
#   # Override GPU indices (default: 2 3)
#   bash scripts/run_all_pipeline.sh --gpus 0 1
#
#   # Skip Phase A (depth already precomputed)
#   bash scripts/run_all_pipeline.sh --skip-phase-a
#
#   # Overwrite existing outputs
#   bash scripts/run_all_pipeline.sh --overwrite
#
# Logs per video: /tmp/phaseA_<NAME>.log  /tmp/phaseB_<NAME>.log

set -euo pipefail
cd "$(dirname "$0")/.."

# ---------------------------------------------------------------------------
# Defaults
GPU0=2
GPU1=3
SKIP_PHASE_A=0
SKIP_PHASE_B=0
OVERWRITE=0
VIDEOS=()

# ---------------------------------------------------------------------------
# Argument parsing
while [[ $# -gt 0 ]]; do
    case "$1" in
        --gpus)      GPU0=$2; GPU1=$3; shift 3 ;;
        --skip-phase-a) SKIP_PHASE_A=1; shift ;;
        --skip-phase-b) SKIP_PHASE_B=1; shift ;;
        --overwrite) OVERWRITE=1; shift ;;
        --help|-h)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*)  echo "Unknown option: $1"; exit 1 ;;
        *)   VIDEOS+=("$1"); shift ;;
    esac
done

# ---------------------------------------------------------------------------
# Paths
UNIDAC_PY=/home/gayagaya/anaconda3/envs/unidac/bin/python
PP="$PWD:$PWD/UniDAC"
VIDEO_DIR=data/video/new
DEPTH_DIR=data/depth
HANDS_DIR=data/hands

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------------------------------------------------------------------------
# Auto-detect fisheye videos (2704x1520) if none specified
if [[ ${#VIDEOS[@]} -eq 0 ]]; then
    log "Auto-detecting fisheye videos in $VIDEO_DIR/ ..."
    for f in "$VIDEO_DIR"/*.MP4; do
        res=$(ffprobe "$f" 2>&1 | grep -oP '\d{4}x\d{4}' | head -1)
        if [[ "$res" == "2704x1520" ]]; then
            VIDEOS+=("$(basename "$f" .MP4)")
        else
            log "  skip $(basename "$f") ($res — not fisheye)"
        fi
    done
fi

if [[ ${#VIDEOS[@]} -eq 0 ]]; then
    log "No videos to process. Exiting."
    exit 0
fi

log "Videos to process: ${VIDEOS[*]}"
log "GPUs: cuda:$GPU0 (even batches) cuda:$GPU1 (odd batches)"

# ---------------------------------------------------------------------------
# Phase A helper
phase_a() {
    local name=$1 gpu=$2
    local out="$DEPTH_DIR/$name"
    local logf="/tmp/phaseA_${name}.log"

    if [[ $OVERWRITE -eq 0 ]] && [[ -f "$out/meta.json" ]]; then
        interrupted=$(python3 -c "import json; m=json.load(open('$out/meta.json')); print(m.get('interrupted', False))" 2>/dev/null || echo "True")
        if [[ "$interrupted" == "False" ]]; then
            log "Phase A $name: already done, skip"
            return 0
        fi
    fi

    log "Phase A $name → cuda:$gpu  (log: $logf)"
    local overwrite_flag=""
    [[ $OVERWRITE -eq 1 ]] && overwrite_flag="--overwrite"

    CUDA_VISIBLE_DEVICES=$gpu PYTHONPATH=$PP \
        $UNIDAC_PY scripts/precompute_depth.py \
            --input "$VIDEO_DIR/$name.MP4" \
            --out   "$out" \
            --device cuda:0 \
            $overwrite_flag \
        >> "$logf" 2>&1
    log "Phase A $name done"
}

# Phase B helper
phase_b() {
    local name=$1 gpu=$2
    local out="$HANDS_DIR/$name"
    local logf="/tmp/phaseB_${name}.log"

    if [[ $OVERWRITE -eq 0 ]] && [[ -f "$out/meta.json" ]]; then
        done=$(python3 -c "import json; m=json.load(open('$out/meta.json')); print(m.get('pass1_complete') and not m.get('interrupted'))" 2>/dev/null || echo "False")
        if [[ "$done" == "True" ]]; then
            log "Phase B $name: already done, skip"
            return 0
        fi
    fi

    log "Phase B $name → cuda:$gpu  (log: $logf)"
    local overwrite_flag=""
    [[ $OVERWRITE -eq 1 ]] && overwrite_flag="--overwrite"

    CUDA_VISIBLE_DEVICES=$gpu PYTHONPATH=$PP \
        uv run python scripts/run_hand_estimation.py \
            --video "$VIDEO_DIR/$name.MP4" \
            --depth "$DEPTH_DIR/$name" \
            --out   "$out" \
            $overwrite_flag \
        >> "$logf" 2>&1
    log "Phase B $name done"
}

# ---------------------------------------------------------------------------
# Split videos into two GPU batches
GPU0_VIDEOS=()
GPU1_VIDEOS=()
for i in "${!VIDEOS[@]}"; do
    if (( i % 2 == 0 )); then
        GPU0_VIDEOS+=("${VIDEOS[$i]}")
    else
        GPU1_VIDEOS+=("${VIDEOS[$i]}")
    fi
done

# ---------------------------------------------------------------------------
# Phase A
if [[ $SKIP_PHASE_A -eq 0 ]]; then
    log "=== Phase A start (${#VIDEOS[@]} videos) ==="
    ( for v in "${GPU0_VIDEOS[@]}"; do phase_a "$v" $GPU0; done ) &
    PID_A0=$!
    ( for v in "${GPU1_VIDEOS[@]}"; do phase_a "$v" $GPU1; done ) &
    PID_A1=$!
    wait $PID_A0 $PID_A1
    log "=== Phase A complete ==="
fi

# Phase B
if [[ $SKIP_PHASE_B -eq 0 ]]; then
    log "=== Phase B start (${#VIDEOS[@]} videos) ==="
    ( for v in "${GPU0_VIDEOS[@]}"; do phase_b "$v" $GPU0; done ) &
    PID_B0=$!
    ( for v in "${GPU1_VIDEOS[@]}"; do phase_b "$v" $GPU1; done ) &
    PID_B1=$!
    wait $PID_B0 $PID_B1
    log "=== Phase B complete ==="
fi

log "All done. Summary:"
for name in "${VIDEOS[@]}"; do
    meta="$HANDS_DIR/$name/meta.json"
    if [[ -f "$meta" ]]; then
        python3 -c "
import json
m = json.load(open('$meta'))
total = m['frames_processed']
hands = m['frames_with_hands']
pct = round(100*hands/total) if total else 0
miss = m['frames_depth_missing']
print(f'  $name  {total}frames  hands={pct}%  depth_missing={miss}  failures={len(m[\"failures\"])}')
"
    fi
done
