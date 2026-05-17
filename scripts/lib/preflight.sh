#!/bin/bash
# Tool availability checks for setup_envs.sh.
#
# Usage:
#   source scripts/lib/log.sh
#   source scripts/lib/preflight.sh
#   require_tool git                       # fail-fast
#   check_optional ffmpeg "unidac runtime" # warn-only
#   require_tool_for hamer python3.10      # fail only when --hamer/--all is selected

# require_tool <tool> [hint]
# Exits 1 immediately if missing. Use for tools needed unconditionally.
require_tool() {
    local tool="$1" hint="${2:-}"
    if ! command -v "$tool" &>/dev/null; then
        fail "Required tool '$tool' not found on PATH."
        [[ -n "$hint" ]] && echo "  Hint: $hint" >&2
        exit 1
    fi
}

# check_optional <tool> <purpose>
# Warns but does not exit. Returns 0 if present, 1 if missing.
check_optional() {
    local tool="$1" purpose="$2"
    if command -v "$tool" &>/dev/null; then
        return 0
    fi
    warn "Optional tool '$tool' not found (needed for: $purpose). Continuing."
    return 1
}

# require_tool_for <step_label> <tool> [hint]
# Same as require_tool but customizes the error message with the gating step.
require_tool_for() {
    local step="$1" tool="$2" hint="${3:-}"
    if ! command -v "$tool" &>/dev/null; then
        fail "Step '$step' requires '$tool' but it was not found on PATH."
        [[ -n "$hint" ]] && echo "  Hint: $hint" >&2
        exit 1
    fi
}

# check_node_major <min_major>
# Returns 0 if node major >= min_major, 1 otherwise (with warn).
check_node_major() {
    local min="$1"
    if ! command -v node &>/dev/null; then
        return 1
    fi
    local actual
    actual="$(node -v | sed 's/^v//' | cut -d. -f1)"
    if [[ "$actual" -lt "$min" ]]; then
        warn "node $actual found, but version >= $min recommended."
        return 1
    fi
    return 0
}

# print_driver_hint
# Best-effort CUDA driver version readout for cu118/cu124 mismatch debugging.
print_driver_hint() {
    if command -v nvidia-smi &>/dev/null; then
        local drv
        drv="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo unknown)"
        log "NVIDIA driver: $drv (HaMeR uses cu124 torch wheel; UniDAC uses cu118)"
    else
        warn "nvidia-smi not found — GPU steps may fail at runtime."
    fi
}
