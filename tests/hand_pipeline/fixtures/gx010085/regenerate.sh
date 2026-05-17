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

# Detection-rate set: 25 frames at 640x360 q=80
for i in 0 6 12 18 24 30 36 42 48 54 60 66 72 78 84 90 96 102 108 114 120 126 132 138 144; do
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
