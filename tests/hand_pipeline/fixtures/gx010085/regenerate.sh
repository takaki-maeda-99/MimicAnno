#!/usr/bin/env bash
# Regenerate hand_pipeline test fixtures for GX010085.
# Run from repo root: tests/hand_pipeline/fixtures/gx010085/regenerate.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VIDEO="data/video/new/GX010085.MP4"
DEPTH_DIR="data/depth/GX010085/frames"

if [[ ! -f "$VIDEO" ]]; then
  echo "Missing $VIDEO" >&2; exit 1
fi

rm -f "$HERE"/det_frame_*.jpg "$HERE"/depth_frame_*.jpg "$HERE"/depth_frame_*.npz

# Detection-rate set: 25 frames at 640x360 q=80, frame index [90, 102, ..., 378]
#
# Range rationale (GX010085 specifics; see PR 3 description for full empirical
# backing):
# - Stable working phase covers frames 90-989. We sample the first ~10s of it.
# - Excludes intro frames 0-89 (no-hand / hand-transition: hand enters the
#   scene at frame ~66, MediaPipe stabilises by frame ~90).
# - Excludes 1080-1199 (heavy occlusion + grasping pose; MediaPipe limitation,
#   not a model-regression signal — documented in
#   test_mediapipe_detection_rate_gx010085 docstring).
# - Sampling every 12 frames keeps temporal locality tight while covering
#   ~10 seconds of stable detection.
for i in 90 102 114 126 138 150 162 174 186 198 210 222 234 246 258 270 282 294 306 318 330 342 354 366 378; do
  ffmpeg -hide_banner -loglevel error -y \
    -i "$VIDEO" -vf "select='eq(n,$i)',scale=640:360" -vframes 1 -q:v 5 \
    "$HERE/det_frame_$(printf '%03d' "$i").jpg"
done

# Depth-integration set: 5 frames, matching depth grids
for i in 0 30 60 90 120; do
  ffmpeg -hide_banner -loglevel error -y \
    -i "$VIDEO" -vf "select='eq(n,$i)',scale=640:360" -vframes 1 -q:v 5 \
    "$HERE/depth_frame_$(printf '%03d' "$i").jpg"

  SRC_DEPTH="$DEPTH_DIR/frame_$(printf '%06d' "$i").npy"
  if [[ ! -f "$SRC_DEPTH" ]]; then
    echo "Missing $SRC_DEPTH" >&2; exit 1
  fi
  # Recompress depth as float16 to save space
  uv run python -c "
import numpy as np
arr = np.load('$SRC_DEPTH')
np.savez_compressed('$HERE/depth_frame_$(printf '%06d' "$i").npz', depth=arr.astype('float16'))
"
done

echo "Fixtures regenerated. Total size:"
du -sh "$HERE"
