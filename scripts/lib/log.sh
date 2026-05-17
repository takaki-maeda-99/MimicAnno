#!/bin/bash
# Shared logging + exit-code helpers for scripts/setup/*.sh and setup_envs.sh.
#
# Source with:  source "$(dirname "$0")/../lib/log.sh"  (or absolute path)

# Exit code conventions (also returned by each setup/*.sh step):
#   0 — success or skip
#   1 — hard fail (something broke)
#   2 — user action required (license-gated weights, auth missing, etc.)
export STEP_OK=0
export STEP_FAIL=1
export STEP_USER=2

_ts() { date '+%H:%M:%S'; }

log()  { echo "[$(_ts)] $*"; }
ok()   { echo "[$(_ts)] ✓ $*"; }
warn() { echo "[$(_ts)] ! $*" >&2; }
skip() { echo "[$(_ts)] ⊘ $*"; }
fail() { echo "[$(_ts)] ✗ $*" >&2; }

# Summary table accumulator. setup_envs.sh appends rows via summary_add and
# prints them via summary_print at the end.
SUMMARY_ROWS=()
summary_add() {
    # args: <status> <step_name> <duration_or_reason>
    SUMMARY_ROWS+=("$1|$2|$3")
}
summary_print() {
    echo ""
    echo "===================== Summary ====================="
    printf "%-6s %-20s %s\n" "Status" "Step" "Detail"
    echo "---------------------------------------------------"
    local row status step detail
    for row in "${SUMMARY_ROWS[@]}"; do
        status="${row%%|*}"
        step="$(echo "$row" | cut -d'|' -f2)"
        detail="${row##*|}"
        printf "[%-4s] %-20s %s\n" "$status" "$step" "$detail"
    done
    echo "==================================================="
}
