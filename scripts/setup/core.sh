#!/bin/bash
# uv sync MimicAnno core + dev + vlm + sam3 + server extras.
#
# Idempotency: uv sync --locked is itself idempotent (no-op when in sync).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"
source "$SCRIPT_DIR/../lib/preflight.sh"

dry_run_short_circuit

cd "$REPO_ROOT"

require_tool_for core uv "curl -Ls https://astral.sh/uv/install.sh | sh"

log "uv sync --locked --extra dev --extra vlm --extra sam3 --extra server"
if uv sync --locked --extra dev --extra vlm --extra sam3 --extra server; then
    ok "core synced"
    exit "$STEP_OK"
fi

fail "uv sync failed"
exit "$STEP_FAIL"
