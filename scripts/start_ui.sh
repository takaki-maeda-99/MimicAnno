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

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNS_ROOT="${RUNS_ROOT:-$REPO_ROOT/runs}"
API_PORT="${API_PORT:-8000}"
VITE_PORT="${VITE_PORT:-5173}"

# Parse --runs-root override
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs-root) RUNS_ROOT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$API_PID" "$VITE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "=== MimicAnno UI ==="
echo "  runs-root : $RUNS_ROOT"
echo "  API       : http://localhost:${API_PORT}"
echo "  UI        : http://localhost:${VITE_PORT}/?api=1"
echo ""

cd "$REPO_ROOT"
uv run mimicanno serve --runs-root "$RUNS_ROOT" --port "$API_PORT" &
API_PID=$!

cd "$REPO_ROOT/frontend"
MIMICANNO_API_PORT="$API_PORT" npm run dev -- --port "$VITE_PORT" &
VITE_PID=$!

wait
