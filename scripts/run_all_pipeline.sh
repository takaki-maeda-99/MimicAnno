#!/bin/bash
# Full pipeline (Phase A + Phase B) for fisheye videos.
#
# Usage:
#   bash scripts/run_all_pipeline.sh [OPTIONS] [VIDEO_NAME ...]
#
# Examples:
#   # All fisheye videos in data/video/ (auto-detect 2704x1520)
#   bash scripts/run_all_pipeline.sh
#
#   # Specific videos only
#   bash scripts/run_all_pipeline.sh GX010175 GX010176
#
#   # Use a non-default dataset root (e.g. data/demo_hand_video/*.MP4)
#   bash scripts/run_all_pipeline.sh --video-dir data/demo_hand_video
#
#   # Override all I/O roots (also accept VIDEO_DIR / DEPTH_DIR / HANDS_DIR env)
#   bash scripts/run_all_pipeline.sh --video-dir VID --depth-dir D --hands-dir H
#
#   # GPU indices (default: 0 0 → single GPU). Pass two distinct ids to
#   # halve wall time by running batches in parallel.
#   bash scripts/run_all_pipeline.sh --gpus 0 1
#   bash scripts/run_all_pipeline.sh --gpus 2 3
#
#   # Skip Phase A (depth already precomputed)
#   bash scripts/run_all_pipeline.sh --skip-phase-a
#
#   # Skip Phase B / C independently
#   bash scripts/run_all_pipeline.sh --skip-phase-b
#   bash scripts/run_all_pipeline.sh --skip-phase-c
#
#   # Only (re)generate the depth viz mp4s for an existing run
#   bash scripts/run_all_pipeline.sh --skip-phase-a --skip-phase-b
#
#   # Overwrite existing outputs
#   bash scripts/run_all_pipeline.sh --overwrite
#
# Logs per video: /tmp/phaseA_<NAME>.log  /tmp/phaseB_<NAME>.log

set -euo pipefail
cd "$(dirname "$0")/.."

# ---------------------------------------------------------------------------
# Defaults
GPU0=0
GPU1=0
SKIP_PHASE_A=0
SKIP_PHASE_B=0
SKIP_PHASE_C=0
OVERWRITE=0
VIDEOS=()
VIDEO_DIR="${VIDEO_DIR:-data/video}"
DEPTH_DIR="${DEPTH_DIR:-outputs/depth}"
HANDS_DIR="${HANDS_DIR:-outputs/hands}"

# ---------------------------------------------------------------------------
# Argument parsing
while [[ $# -gt 0 ]]; do
    case "$1" in
        --gpus)      GPU0=$2; GPU1=$3; shift 3 ;;
        --video-dir) VIDEO_DIR=$2; shift 2 ;;
        --depth-dir) DEPTH_DIR=$2; shift 2 ;;
        --hands-dir) HANDS_DIR=$2; shift 2 ;;
        --skip-phase-a) SKIP_PHASE_A=1; shift ;;
        --skip-phase-b) SKIP_PHASE_B=1; shift ;;
        --skip-phase-c) SKIP_PHASE_C=1; shift ;;
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
# Resolve the UniDAC env's python without hardcoding $HOME or $USER.
# 1. Honor an explicit UNIDAC_PY override.
# 2. Otherwise ask conda where it put the `unidac` env.
# 3. Fall back to the legacy /home/gayagaya path so existing setups
#    keep working; complain clearly if nothing resolves.
if [[ -z "${UNIDAC_PY:-}" ]]; then
    if command -v conda &>/dev/null; then
        UNIDAC_PREFIX="$(conda env list 2>/dev/null | awk '/[\/]unidac$/ {print $NF; exit}')"
        if [[ -n "$UNIDAC_PREFIX" && -x "$UNIDAC_PREFIX/bin/python" ]]; then
            UNIDAC_PY="$UNIDAC_PREFIX/bin/python"
        fi
    fi
fi
UNIDAC_PY="${UNIDAC_PY:-/home/gayagaya/anaconda3/envs/unidac/bin/python}"
if [[ ! -x "$UNIDAC_PY" ]]; then
    echo "error: UniDAC python not found at $UNIDAC_PY." >&2
    echo "       Create the env with: bash scripts/setup_envs.sh --unidac" >&2
    echo "       Or set UNIDAC_PY=/path/to/conda/envs/unidac/bin/python" >&2
    exit 1
fi
PP="$PWD:$PWD/UniDAC"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Resolve a video stem ("GX010175") to its on-disk path; accepts both
# .MP4 and .mp4 extensions. Prints the full path on stdout, or empty if
# neither exists.
resolve_video() {
    local stem="$1"
    if   [[ -f "$VIDEO_DIR/$stem.MP4" ]]; then echo "$VIDEO_DIR/$stem.MP4"
    elif [[ -f "$VIDEO_DIR/$stem.mp4" ]]; then echo "$VIDEO_DIR/$stem.mp4"
    fi
}

# ---------------------------------------------------------------------------
# Auto-detect fisheye videos (2704x1520) if none specified
if [[ ${#VIDEOS[@]} -eq 0 ]]; then
    log "Auto-detecting fisheye videos in $VIDEO_DIR/ ..."
    shopt -s nullglob
    for f in "$VIDEO_DIR"/*.MP4 "$VIDEO_DIR"/*.mp4; do
        res=$(ffprobe "$f" 2>&1 | grep -oP '\d{4}x\d{4}' | head -1)
        if [[ "$res" == "2704x1520" ]]; then
            stem="$(basename "$f")"
            VIDEOS+=("${stem%.*}")
        else
            log "  skip $(basename "$f") ($res — not fisheye)"
        fi
    done
    shopt -u nullglob
fi

if [[ ${#VIDEOS[@]} -eq 0 ]]; then
    log "No videos to process. Exiting."
    exit 0
fi

# Validate every named stem resolves to a .MP4 or .mp4 file under VIDEO_DIR.
for v in "${VIDEOS[@]}"; do
    if [[ -z "$(resolve_video "$v")" ]]; then
        echo "error: no $VIDEO_DIR/$v.MP4 or $VIDEO_DIR/$v.mp4 found" >&2
        exit 1
    fi
done

log "Videos to process: ${VIDEOS[*]}"
log "GPUs: cuda:$GPU0 (even batches) cuda:$GPU1 (odd batches)"

# ---------------------------------------------------------------------------
# Phase C helper: render fisheye-space depth mp4 + transcode to h264.
# Produces outputs/depth/<name>/viz_depth.mp4 which the viewer expects.
phase_c() {
    local name=$1 gpu=$2
    local out_mp4="$DEPTH_DIR/$name/viz_depth.mp4"
    local existing="$DEPTH_DIR/$name/viz/depth_fisheye.mp4"
    local logf="/tmp/phaseC_${name}.log"

    if [[ $OVERWRITE -eq 0 ]] && [[ -e "$out_mp4" ]]; then
        log "Phase C $name: viz_depth.mp4 exists, skip"
        return 0
    fi

    # precompute_depth.py already renders the fisheye-space mp4 at
    # viz/depth_fisheye.mp4. Reuse it via symlink instead of repaying
    # the back-warp pass.
    if [[ -e "$existing" ]]; then
        ln -sf "viz/depth_fisheye.mp4" "$out_mp4"
        log "Phase C $name: symlinked viz/depth_fisheye.mp4 → viz_depth.mp4"
        return 0
    fi

    log "Phase C $name → cuda:$gpu  (log: $logf)"
    CUDA_VISIBLE_DEVICES=$gpu PYTHONPATH=$PP \
        $UNIDAC_PY scripts/visualize_depth.py \
            --depth "$DEPTH_DIR/$name" \
            --video "$(resolve_video "$name")" \
            --out   "$out_mp4" \
            --no-side-by-side \
        >> "$logf" 2>&1
    log "Phase C $name done"
}

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
            --input "$(resolve_video "$name")" \
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
            --video "$(resolve_video "$name")" \
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

# ---------------------------------------------------------------------------
# Phase C: depth visualization (browser-playable mp4) — split across both GPUs.
if [[ $SKIP_PHASE_C -eq 0 ]]; then
    log "=== Phase C start (depth viz) ==="
    ( for v in "${GPU0_VIDEOS[@]}"; do phase_c "$v" $GPU0; done ) &
    PID_C0=$!
    ( for v in "${GPU1_VIDEOS[@]}"; do phase_c "$v" $GPU1; done ) &
    PID_C1=$!
    wait $PID_C0 $PID_C1
    log "=== Phase C complete ==="

    log "=== Transcoding viz mp4s to h264 (browser playback) ==="
    uv run python scripts/transcode_viz_to_h264.py "$DEPTH_DIR" >/tmp/transcode.log 2>&1 || \
        log "  transcode step had errors, see /tmp/transcode.log"
    log "=== Transcode complete ==="
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
