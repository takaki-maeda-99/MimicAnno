#!/bin/bash
# Initialize git submodules (sam3, UniDAC) with SSH→HTTPS fallback.
#
# Exit codes: 0 success/skip, 1 fail, 2 user action required.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"

dry_run_short_circuit

cd "$REPO_ROOT"

# Sentinel: every required submodule has no leading '-' in status.
REQUIRED_PATHS=(sam3 UniDAC)
all_initialized() {
    local p status
    for p in "${REQUIRED_PATHS[@]}"; do
        # status line format: "<+ -| ><sha> <path> [(branch)]"
        status="$(git submodule status -- "$p" 2>/dev/null || true)"
        if [[ -z "$status" || "${status:0:1}" == "-" ]]; then
            return 1
        fi
    done
    return 0
}

if all_initialized; then
    skip "submodules already initialized (sam3, UniDAC)"
    exit "$STEP_OK"
fi

log "git submodule update --init --recursive"
if git submodule update --init --recursive; then
    ok "submodules initialized"
    exit "$STEP_OK"
fi

# Retry with SSH→HTTPS rewrite, scoped to THIS command only via `-c`.
# This avoids leaving a global git config behind if the retry also fails.
warn "submodule init failed (likely SSH auth). Retrying with HTTPS rewrite (this run only)…"
if git -c url."https://github.com/".insteadOf="git@github.com:" \
       submodule update --init --recursive; then
    ok "submodules initialized via HTTPS rewrite"
    warn "HTTPS rewrite was applied for this run only (not persisted)."
    warn "To persist, run: git config --global url.https://github.com/.insteadOf git@github.com:"
    exit "$STEP_OK"
fi

fail "submodule update failed even with HTTPS rewrite."
echo "  Check network access or SSH key, then run: git submodule update --init --recursive" >&2
exit "$STEP_FAIL"
