#!/bin/bash
# One-shot environment setup for MimicAnno.
#
# Steps (in order, when selected):
#   submodules → core → unidac → frontend → weights
#
# Usage:
#   bash scripts/setup_envs.sh                # --all (default)
#   bash scripts/setup_envs.sh --core         # MimicAnno core (uv) only
#   bash scripts/setup_envs.sh --unidac
#   bash scripts/setup_envs.sh --all --skip-weights
#
# Auth (for weights step):
#   Either export HF_TOKEN or run `hf auth login` beforehand.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/preflight.sh"

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Flag parsing
DO_SUBMODULES=0
DO_CORE=0
DO_UNIDAC=0
DO_FRONTEND=0
DO_WEIGHTS=0
SKIP_WEIGHTS=0
EXPLICIT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)       DO_SUBMODULES=1; DO_CORE=1; DO_UNIDAC=1; DO_FRONTEND=1; DO_WEIGHTS=1; EXPLICIT=1; shift ;;
        --core)      DO_CORE=1;     EXPLICIT=1; shift ;;
        --unidac)    DO_UNIDAC=1;   EXPLICIT=1; shift ;;
        --frontend)  DO_FRONTEND=1; EXPLICIT=1; shift ;;
        --weights)   DO_WEIGHTS=1;  EXPLICIT=1; shift ;;
        --skip-weights) SKIP_WEIGHTS=1; shift ;;
        --help|-h)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) fail "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ "$EXPLICIT" -eq 0 ]]; then
    DO_SUBMODULES=1; DO_CORE=1; DO_UNIDAC=1; DO_FRONTEND=1; DO_WEIGHTS=1
fi
if [[ "$SKIP_WEIGHTS" -eq 1 ]]; then
    DO_WEIGHTS=0
fi
# --weights implies --core (hf lives in .venv)
if [[ "$DO_WEIGHTS" -eq 1 && "$DO_CORE" -eq 0 ]]; then
    DO_CORE=1
    log "--weights implies --core; adding core step."
fi
# Anything but pure --core implies --submodules so the dirs exist.
if [[ "$DO_SUBMODULES" -eq 0 && ("$DO_UNIDAC" -eq 1 || "$DO_WEIGHTS" -eq 1) ]]; then
    DO_SUBMODULES=1
    log "Selected steps depend on submodules; adding submodules step."
fi

# ---------------------------------------------------------------------------
# Preflight
log "=== Preflight ==="
require_tool git
[[ "$DO_CORE" -eq 1 || "$DO_WEIGHTS" -eq 1 ]] && require_tool uv "curl -Ls https://astral.sh/uv/install.sh | sh"
[[ "$DO_UNIDAC" -eq 1 ]] && require_tool conda "Install miniforge or anaconda"
[[ "$DO_FRONTEND" -eq 1 ]] && { require_tool node "Install Node >=20"; require_tool pnpm "corepack enable && corepack prepare pnpm@latest --activate"; }
[[ "$DO_UNIDAC" -eq 1 ]] && check_optional curl "UniDAC weights DL"
[[ "$DO_UNIDAC" -eq 1 ]] && check_optional ffmpeg "precompute_depth.py runtime"
check_optional lsof "start_ui.sh port probe"
print_driver_hint

if [[ "${SETUP_DRY_RUN:-0}" == "1" ]]; then
    log "SETUP_DRY_RUN=1 — each step will short-circuit and not execute install commands."
fi

# ---------------------------------------------------------------------------
# Ensure standard I/O directories exist so the pipeline can write without
# needing each script to mkdir -p its own. data/video/ is the GoPro source
# (populated by --weights from Gayagaya/fisheye_videos_processed or by hand);
# outputs/{depth,hands}/ are generated artifacts.
mkdir -p data/video outputs/depth outputs/hands

# ---------------------------------------------------------------------------
# Step runner
run_step() {
    local label="$1" script_path="$2"
    log "=== Step: $label ==="
    local start_ts=$SECONDS
    local rc=0
    bash "$script_path" || rc=$?
    local dur=$((SECONDS - start_ts))
    case "$rc" in
        0) summary_add "PASS" "$label" "${dur}s" ;;
        2) summary_add "WARN" "$label" "user action required (${dur}s)" ;;
        *) summary_add "FAIL" "$label" "exit=$rc (${dur}s)" ;;
    esac
    return "$rc"
}

OVERALL=0  # 0 ok, 1 fail, 2 warn

step_and_track() {
    local label="$1" path="$2"
    set +e
    run_step "$label" "$path"
    local rc=$?
    set -e
    if [[ "$rc" -eq 1 ]]; then
        OVERALL=1
    elif [[ "$rc" -eq 2 && "$OVERALL" -ne 1 ]]; then
        OVERALL=2
    fi
}

# Run selected steps in canonical order.
[[ "$DO_SUBMODULES" -eq 1 ]] && step_and_track submodules "$SCRIPT_DIR/setup/submodules.sh"
[[ "$DO_CORE"       -eq 1 ]] && step_and_track core       "$SCRIPT_DIR/setup/core.sh"
[[ "$DO_UNIDAC"     -eq 1 ]] && step_and_track unidac     "$SCRIPT_DIR/setup/unidac.sh"
[[ "$DO_FRONTEND"   -eq 1 ]] && step_and_track frontend   "$SCRIPT_DIR/setup/frontend.sh"
[[ "$DO_WEIGHTS"    -eq 1 ]] && step_and_track weights    "$SCRIPT_DIR/setup/weights.sh"

summary_print

case "$OVERALL" in
    0) ok "All done."; exit 0 ;;
    2) warn "Completed with user-action items above."; exit 2 ;;
    1) fail "Completed with failures. See summary above."; exit 1 ;;
esac
