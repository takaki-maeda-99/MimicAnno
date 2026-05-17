#!/bin/bash
# UniDAC conda env + editable install + weights download.
#
# Idempotency sentinels:
#   - conda env "unidac" exists AND `import unidac` succeeds → skip env setup
#   - UniDAC/checkpoints/unidac.pt non-zero → skip weights DL

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"
source "$SCRIPT_DIR/../lib/preflight.sh"

dry_run_short_circuit

cd "$REPO_ROOT"

require_tool_for unidac conda "Install miniforge or anaconda"
check_optional ffmpeg "precompute_depth.py runtime"
check_optional curl "UniDAC weights download"

# --- env -------------------------------------------------------------------
env_ready() {
    conda env list 2>/dev/null | grep -q '^unidac ' || return 1
    conda run -n unidac python -c "import unidac" &>/dev/null
}

if env_ready; then
    skip "conda env 'unidac' already set up"
else
    if ! conda env list 2>/dev/null | grep -q '^unidac '; then
        log "Creating conda env 'unidac' (python=3.10)…"
        conda create -n unidac python=3.10 -y
    fi
    log "Installing PyTorch (cu118) into unidac…"
    conda run -n unidac pip install \
        torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
        --index-url https://download.pytorch.org/whl/cu118
    log "Installing UniDAC requirements…"
    conda run -n unidac pip install -r "$REPO_ROOT/UniDAC/requirements.txt"
    log "Installing UniDAC package (editable)…"
    conda run -n unidac pip install -e "$REPO_ROOT/UniDAC" --no-deps
    ok "unidac env ready"
fi

# --- weights ---------------------------------------------------------------
WEIGHTS="$REPO_ROOT/UniDAC/checkpoints/unidac.pt"
if [[ -s "$WEIGHTS" ]]; then
    skip "UniDAC weights present at $(realpath --relative-to="$REPO_ROOT" "$WEIGHTS")"
    exit "$STEP_OK"
fi

# NOTE: replace UNIDAC_CKPT_URL with the actual public release URL recorded in
# UniDAC/README.md at implementation time. If unknown, leave UNIDAC_CKPT_URL
# empty and the step will WARN (exit 2) for manual download.
UNIDAC_CKPT_URL="${UNIDAC_CKPT_URL:-}"
if [[ -z "$UNIDAC_CKPT_URL" ]]; then
    warn "UniDAC weights URL not configured (UNIDAC_CKPT_URL env var)."
    warn "Manually download UniDAC checkpoint to: $WEIGHTS"
    exit "$STEP_USER"
fi

mkdir -p "$(dirname "$WEIGHTS")"
log "Downloading UniDAC weights from $UNIDAC_CKPT_URL…"
if curl -fL --retry 3 -o "$WEIGHTS" "$UNIDAC_CKPT_URL"; then
    ok "UniDAC weights downloaded"
    exit "$STEP_OK"
fi

fail "UniDAC weights download failed."
exit "$STEP_FAIL"
