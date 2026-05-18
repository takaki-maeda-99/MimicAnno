#!/usr/bin/env bash
# Start the MimicAnno review UI.
#   API server : http://localhost:${API_PORT:-8000}
#   Frontend   : http://localhost:${VITE_PORT:-5173}/?api=1
#
# Usage:
#   ./scripts/start_ui.sh                    # default ports
#   API_PORT=8001 VITE_PORT=5174 ./scripts/start_ui.sh
#   ./scripts/start_ui.sh --runs-root /path/to/runs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/log.sh"

cd "$REPO_ROOT"

RUNS_ROOT="${RUNS_ROOT:-$REPO_ROOT/runs}"
API_PORT="${API_PORT:-8000}"
VITE_PORT="${VITE_PORT:-5173}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs-root) RUNS_ROOT="$2"; shift 2 ;;
        *) fail "Unknown option: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Dependency self-check
deps_check() {
    if ! command -v uv &>/dev/null; then
        fail "uv not found. Install: curl -Ls https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    if [[ ! -x "$REPO_ROOT/.venv/bin/mimicanno" ]]; then
        fail "mimicanno CLI not found in .venv. Run: bash scripts/setup_envs.sh --core"
        exit 1
    fi
    if [[ ! -f "$REPO_ROOT/frontend/node_modules/.modules.yaml" ]]; then
        fail "frontend deps not installed. Run: bash scripts/setup_envs.sh --frontend"
        exit 1
    fi
}

probe_port() {
    local port="$1" label="$2"
    if ! command -v lsof &>/dev/null; then return 0; fi
    local pid
    pid="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)" || true
    if [[ -n "$pid" ]]; then
        fail "$label port $port is already in use by PID $pid."
        echo "  Set $label=<free port> and retry." >&2
        exit 1
    fi
}

deps_check
probe_port "$API_PORT"  API_PORT
probe_port "$VITE_PORT" VITE_PORT

echo "=== MimicAnno UI ==="
echo "  runs-root : $RUNS_ROOT"
echo "  API       : http://localhost:${API_PORT}"
echo "  UI        : http://localhost:${VITE_PORT}/?api=1"
echo ""

# ---------------------------------------------------------------------------
# Launch backend first, wait until it accepts connections, then frontend.
# Skips the startup-race ECONNREFUSED noise the proxy would otherwise log.
uv run --extra server mimicanno serve --runs-root "$RUNS_ROOT" --port "$API_PORT" &
API_PID=$!

wait_for_api() {
    local url="http://127.0.0.1:${API_PORT}/api/run-sets"
    local deadline=$(( SECONDS + 60 ))
    while (( SECONDS < deadline )); do
        if ! kill -0 "$API_PID" 2>/dev/null; then
            fail "API server exited before becoming ready."
            exit 1
        fi
        if curl -sf -o /dev/null --max-time 1 "$url"; then
            return 0
        fi
        sleep 0.3
    done
    fail "API server did not become ready within 60s ($url)."
    exit 1
}
wait_for_api

( cd "$REPO_ROOT/frontend" && MIMICANNO_API_PORT="$API_PORT" pnpm run dev --port "$VITE_PORT" ) &
VITE_PID=$!

cleanup() {
    # Clear trap immediately to prevent recursive invocations.
    trap - EXIT INT TERM
    echo ""
    log "Shutting down…"
    # Kill the entire process group (includes all backgrounded children and their
    # descendants — e.g. pnpm → node → vite, uv → uvicorn).
    kill -- -"$$" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for whichever child exits first, propagate its exit code, kill survivor.
set +e
wait -n "$API_PID" "$VITE_PID"
FIRST_EXIT=$?
set -e
cleanup
wait 2>/dev/null || true
exit "$FIRST_EXIT"
