#!/usr/bin/env bash
# Phase 4 finer-segmentation v4 batch: ZC detector enabled via
# configs/boundary/so101_zero_crossing.yaml.
#
# spec: docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md
# plan: docs/superpowers/plans/2026-05-11-phase4-finer-segmentation-plan.md (T8)
#
# Mirrors batch_so101_phase4_overlay.sh: SO101 dataset, overlay defaults,
# but lands at runs/so101_phase4_v4/ and passes --boundary-config.

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
export RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/so101_phase4_v4}"
export LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_so101_v4}"
export VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"
export BOUNDARY_CONFIG="${BOUNDARY_CONFIG:-$REPO/mimicanno/configs/boundary/so101_zero_crossing.yaml}"

exec bash "$REPO/scripts/batch_so101_phase4.sh"
