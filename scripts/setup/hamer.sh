#!/bin/bash
# HaMeR venv + torch cu124 + hamer[all] + ViTPose + scipy + demo data + MANO check.
#
# Idempotency sentinels:
#   - hamer/.hamer/bin/python -c "import hamer" succeeds → skip pip installs
#   - hamer/_DATA/hamer_ckpts/ non-empty → skip demo data fetch

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"
source "$SCRIPT_DIR/../lib/preflight.sh"

dry_run_short_circuit

cd "$REPO_ROOT"

require_tool_for hamer python3.10 "Install python3.10 (e.g., via pyenv or apt)"
check_optional gdown "HaMeR demo data fetch (Google Drive)"

HAMER_ROOT="$REPO_ROOT/hamer"
HAMER_VENV="$HAMER_ROOT/.hamer"
HAMER_PY="$HAMER_VENV/bin/python"

USER_ACTION=0  # set to 1 if MANO is missing (license gate)

# --- venv + packages -------------------------------------------------------
if [[ -x "$HAMER_PY" ]] && "$HAMER_PY" -c "import hamer" &>/dev/null; then
    skip "HaMeR venv already set up (hamer import OK)"
else
    if [[ ! -x "$HAMER_PY" ]]; then
        log "Creating HaMeR venv (python3.10)…"
        python3.10 -m venv "$HAMER_VENV"
    fi
    log "Installing torch cu124 into HaMeR venv…"
    "$HAMER_VENV/bin/pip" install \
        torch==2.6.0 torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cu124
    log "Installing hamer[all]…"
    "$HAMER_VENV/bin/pip" install -e "$HAMER_ROOT[all]"
    log "Installing third-party/ViTPose…"
    "$HAMER_VENV/bin/pip" install -v -e "$HAMER_ROOT/third-party/ViTPose"
    log "Installing scipy (pipeline.py requirement)…"
    "$HAMER_VENV/bin/pip" install scipy
    ok "HaMeR venv ready"
fi

# --- demo data -------------------------------------------------------------
if [[ -d "$HAMER_ROOT/_DATA/hamer_ckpts" ]] && [[ -n "$(ls -A "$HAMER_ROOT/_DATA/hamer_ckpts" 2>/dev/null)" ]]; then
    skip "HaMeR demo data already present"
else
    log "Fetching HaMeR demo data (uses gdown)…"
    if ! ( cd "$HAMER_ROOT" && bash fetch_demo_data.sh ); then
        warn "fetch_demo_data.sh failed (Google Drive 403 / rate-limit?)."
        warn "Manually download per hamer/README.md to: $HAMER_ROOT/_DATA/"
        USER_ACTION=1
    fi
fi

# --- MANO (license gate) ---------------------------------------------------
MANO="$HAMER_ROOT/_DATA/data/mano/MANO_RIGHT.pkl"
if [[ -f "$MANO" ]]; then
    ok "MANO_RIGHT.pkl found"
else
    warn "MANO_RIGHT.pkl not found."
    warn "Register at https://mano.is.tue.mpg.de and place at: $MANO"
    USER_ACTION=1
fi

if [[ "$USER_ACTION" -eq 1 ]]; then
    exit "$STEP_USER"
fi
exit "$STEP_OK"
