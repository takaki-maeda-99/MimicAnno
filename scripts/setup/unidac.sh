#!/bin/bash
# UniDAC conda env + editable install. Weights download is handled by
# scripts/setup/weights.sh (girish1511/UniDAC for unidac.pt; DINOv3
# backbone is a manual step per README).
#
# Idempotency sentinel:
#   - conda env "unidac" exists AND `import unidac` succeeds → skip env setup

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

# UniDAC checkpoint and DINOv3 backbone are pulled by the `weights` step
# (scripts/setup/weights.sh). Nothing else to do here.
exit "$STEP_OK"
