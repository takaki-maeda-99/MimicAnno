#!/usr/bin/env bash
# Pre-fetch the MediaPipe hand landmarker model for offline / production use.
#
# Usage:
#   scripts/fetch_mediapipe_model.sh [DEST]
#
# Run once on a machine with internet access; copy the resulting file to
# production deployment artifacts. At runtime, set the environment variable
# MIMICANNO_HAND_LANDMARKER_PATH to the file's path; the hand_pipeline will
# skip its own network download and use the pre-fetched asset.
#
# MediaPipe Solutions is in Preview status. The URL pins the /1/ revision
# to keep model bytes reproducible across machines; bumping the revision is
# an explicit change, not an automatic upgrade. See
# https://ai.google.dev/edge/mediapipe/legal/tos for the upstream terms.
set -euo pipefail

URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
DEST="${1:-$HOME/.cache/mimicanno/hand_landmarker.task}"

mkdir -p "$(dirname "$DEST")"
echo "Downloading MediaPipe hand landmarker model..."
echo "  URL:  $URL"
echo "  DEST: $DEST"
curl -fSL "$URL" -o "$DEST.tmp"
mv "$DEST.tmp" "$DEST"

# Portable file-size lookup (Linux stat -c, BSD stat -f).
if SIZE=$(stat -c %s "$DEST" 2>/dev/null); then
    :
else
    SIZE=$(stat -f %z "$DEST")
fi
echo "Saved $((SIZE / 1024 / 1024)) MB to $DEST"
echo
echo "For production deployment:"
echo "  export MIMICANNO_HAND_LANDMARKER_PATH=\"$DEST\""
