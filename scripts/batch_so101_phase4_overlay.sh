#!/usr/bin/env bash
# Task 12 (vlm-mask-overlay): batch-run mimicanno annotate --target-phase 4
# across SO101 episodes with mask overlay enabled (the default).
#
# Thin wrapper around scripts/batch_so101_phase4.sh that points
# RUNS_ROOT / LOGS_DIR / VLM_DUMP_ROOT at the v3 (overlay) lot, leaving
# the v2 (no-overlay) artifacts at runs/so101_phase4/ untouched.
#
# Usage:
#   GPU=0 START=0  END=10 bash scripts/batch_so101_phase4_overlay.sh
#   GPU=1 START=21 END=32 bash scripts/batch_so101_phase4_overlay.sh
#
# Overlay defaults match MaskOverlayConfig: enabled=True, alpha=0.4. To
# A/B test the alpha value, override via CLI flag in the underlying
# script — but that would also break v2/v3 parity, so prefer running a
# whole new lot (e.g. runs/so101_phase4_v3_alpha06/).

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
export RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/so101_phase4_v3}"
export LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_so101_v3}"
export VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"

exec bash "$REPO/scripts/batch_so101_phase4.sh"
