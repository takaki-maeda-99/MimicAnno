#!/bin/bash
# Install frontend deps via pnpm.
#
# Idempotency: pnpm install --frozen-lockfile is itself a no-op when the
# lockfile matches node_modules. We also sentinel on .modules.yaml existence
# for a fast skip when the user has run this before.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"
source "$SCRIPT_DIR/../lib/preflight.sh"

cd "$REPO_ROOT/frontend"

require_tool_for frontend node "Install Node >=20 (e.g., via nvm)"
require_tool_for frontend pnpm "corepack enable && corepack prepare pnpm@latest --activate"

if ! check_node_major 20; then
    warn "node major < 20 — frontend may not build."
fi

if [[ -f node_modules/.modules.yaml ]]; then
    # Re-run pnpm install anyway; --frozen-lockfile is a fast no-op when in sync.
    log "node_modules/.modules.yaml present — verifying with pnpm install --frozen-lockfile"
else
    log "Fresh install: pnpm install --frozen-lockfile"
fi

if pnpm install --frozen-lockfile; then
    ok "frontend deps installed"
    exit "$STEP_OK"
fi

fail "pnpm install failed"
exit "$STEP_FAIL"
