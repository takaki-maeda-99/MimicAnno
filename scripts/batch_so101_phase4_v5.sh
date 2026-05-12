#!/usr/bin/env bash
# Phase 4 finer-segmentation v5 batch: ZC detector + source-aware merge
# preserve (mimicanno/configs/smoother/so101_zc_preserve.yaml).
#
# spec: docs/superpowers/specs/2026-05-12-phase4-smoother-source-aware-merge-design.md
# plan: docs/superpowers/plans/2026-05-12-phase4-smoother-source-aware-merge-plan.md (T8)
#
# Mirrors batch_so101_phase4_v4.sh; adds SMOOTHER_CONFIG so the underlying
# script appends ``--smoother-config`` (T8a wired the passthrough).

set -euo pipefail

REPO=/misc/dl00/gayagaya/MimicAnno
export RUNS_ROOT="${RUNS_ROOT:-$REPO/runs/so101_phase4_v5}"
export LOGS_DIR="${LOGS_DIR:-$REPO/logs/batch_so101_v5}"
export VLM_DUMP_ROOT="${VLM_DUMP_ROOT:-$RUNS_ROOT/_vlm_dumps}"
export BOUNDARY_CONFIG="${BOUNDARY_CONFIG:-$REPO/mimicanno/configs/boundary/so101_zero_crossing.yaml}"
export SMOOTHER_CONFIG="${SMOOTHER_CONFIG:-$REPO/mimicanno/configs/smoother/so101_zc_preserve.yaml}"

exec bash "$REPO/scripts/batch_so101_phase4.sh"
