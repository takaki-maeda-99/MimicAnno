#!/bin/bash
# Download gated HF weights: SAM3 snapshot + Gemma 4.
#
# Idempotency sentinels:
#   - sam3/checkpoints/sam3.pt AND model.safetensors both >0 bytes → skip SAM3
#   - huggingface_hub.try_to_load_from_cache returns a path → skip Gemma
#
# Auth: requires HF_TOKEN env OR prior `hf auth login`. On miss, WARN.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../lib/log.sh"
source "$SCRIPT_DIR/../lib/preflight.sh"

dry_run_short_circuit

cd "$REPO_ROOT"

# Must have core synced (huggingface_hub lives in --extra vlm/sam3).
if [[ ! -x ".venv/bin/python" ]]; then
    fail "weights step requires uv-managed .venv. Run setup_envs.sh --core first."
    exit "$STEP_FAIL"
fi

SAM3_REPO="${SAM3_HF_REPO:-facebook/sam3}"
GEMMA_REPO="${GEMMA_HF_REPO:-google/gemma-4-E2B-it}"
SAM3_DIR="$REPO_ROOT/sam3/checkpoints"

USER_ACTION=0

# --- auth check ------------------------------------------------------------
has_hf_auth() {
    if [[ -n "${HF_TOKEN:-}" ]]; then return 0; fi
    if [[ -f "$HOME/.cache/huggingface/token" ]]; then return 0; fi
    return 1
}

if ! has_hf_auth; then
    warn "No HF auth detected. Set HF_TOKEN or run: hf auth login"
    warn "Skipping gated weight downloads (SAM3, Gemma)."
    exit "$STEP_USER"
fi

# --- SAM3 ------------------------------------------------------------------
if [[ -s "$SAM3_DIR/sam3.pt" && -s "$SAM3_DIR/model.safetensors" ]]; then
    skip "SAM3 snapshot already present at sam3/checkpoints/"
else
    log "Downloading SAM3 snapshot from $SAM3_REPO…"
    if uv run hf download "$SAM3_REPO" --local-dir "$SAM3_DIR"; then
        if [[ -s "$SAM3_DIR/sam3.pt" && -s "$SAM3_DIR/model.safetensors" ]]; then
            ok "SAM3 snapshot ready"
        else
            warn "SAM3 snapshot downloaded but missing expected files (sam3.pt / model.safetensors)."
            warn "Try SAM3_HF_REPO=<other-id> bash scripts/setup/weights.sh"
            USER_ACTION=1
        fi
    else
        warn "SAM3 snapshot download failed (401? gated repo not granted?). See https://huggingface.co/$SAM3_REPO"
        USER_ACTION=1
    fi
fi

# --- Gemma 4 ---------------------------------------------------------------
GEMMA_CACHED=$(uv run python - <<EOF
from huggingface_hub import try_to_load_from_cache
p = try_to_load_from_cache(repo_id="$GEMMA_REPO", filename="config.json")
print(p or "")
EOF
)
if [[ -n "$GEMMA_CACHED" ]]; then
    skip "Gemma 4 weights cached at $GEMMA_CACHED"
else
    log "Downloading Gemma 4 ($GEMMA_REPO) to HF cache…"
    if uv run hf download "$GEMMA_REPO"; then
        ok "Gemma 4 weights downloaded"
    else
        warn "Gemma 4 download failed (401? gated repo not granted?). See https://huggingface.co/$GEMMA_REPO"
        USER_ACTION=1
    fi
fi

if [[ "$USER_ACTION" -eq 1 ]]; then
    exit "$STEP_USER"
fi
exit "$STEP_OK"
