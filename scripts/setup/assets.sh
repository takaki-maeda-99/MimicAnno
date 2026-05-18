#!/bin/bash
# Download model weights + public datasets from Hugging Face.
# Includes: SAM3, Gemma 4, MediaPipe, UniDAC + DINOv3, GEM4 4B/26B
# QLoRA adapters, SO101 / fisheye / GEM4 datasets.
#
# Each block has its own idempotency check (file size, HF cache hit,
# or local dir non-empty) so re-runs are no-ops.
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
    fail "assets step requires uv-managed .venv. Run setup_envs.sh --core first."
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
            warn "Try SAM3_HF_REPO=<other-id> bash scripts/setup/assets.sh"
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

# --- MediaPipe hand landmarker --------------------------------------------
# Public (non-gated), but pre-fetching avoids the pipeline's first-run
# network DL when the runtime host has no internet access. The /1/ pin
# keeps model bytes reproducible across machines; bumping the revision
# is an explicit change. ToS: https://ai.google.dev/edge/mediapipe/legal/tos
MP_URL="https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
MP_DEST="${MIMICANNO_HAND_LANDMARKER_PATH:-$HOME/.cache/mimicanno/hand_landmarker.task}"
if [[ -s "$MP_DEST" ]]; then
    skip "MediaPipe hand landmarker cached at $MP_DEST"
else
    log "Downloading MediaPipe hand landmarker → $MP_DEST"
    mkdir -p "$(dirname "$MP_DEST")"
    if curl -fSL "$MP_URL" -o "$MP_DEST.tmp" && mv "$MP_DEST.tmp" "$MP_DEST"; then
        ok "MediaPipe hand landmarker ready"
    else
        warn "MediaPipe model download failed. Pipeline will retry at first use."
        rm -f "$MP_DEST.tmp"
    fi
fi

# --- UniDAC checkpoints ---------------------------------------------------
# Two files are required for Phase A (depth precompute):
#   - UniDAC/checkpoints/unidac.pt                                   (public)
#   - UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth (gated)
UNIDAC_CKPT_DIR="$REPO_ROOT/UniDAC/checkpoints"
mkdir -p "$UNIDAC_CKPT_DIR"

if [[ -s "$UNIDAC_CKPT_DIR/unidac.pt" ]]; then
    skip "UniDAC checkpoint cached at UniDAC/checkpoints/unidac.pt"
else
    log "Downloading girish1511/UniDAC/unidac.pt → UniDAC/checkpoints/"
    if uv run hf download girish1511/UniDAC unidac.pt --local-dir "$UNIDAC_CKPT_DIR"; then
        ok "UniDAC checkpoint ready"
    else
        warn "UniDAC checkpoint download failed."
        USER_ACTION=1
    fi
fi

DINOV3_FILE="dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth"
if [[ -s "$UNIDAC_CKPT_DIR/$DINOV3_FILE" ]]; then
    skip "DINOv3 backbone cached at UniDAC/checkpoints/$DINOV3_FILE"
else
    warn "DINOv3 backbone is license-gated by Meta and cannot be fetched"
    warn "automatically. Apply at"
    warn "  https://ai.meta.com/resources/models-and-libraries/dinov3-downloads/"
    warn "and place the file at UniDAC/checkpoints/$DINOV3_FILE"
    warn "(or scp it from another machine that already has it)."
    USER_ACTION=1
fi

# --- GEM4 QLoRA adapters (public) -----------------------------------------
# Pulled from Gayagaya/gem4_{4B,26B}_adapter on the Hugging Face Hub.
# Public repos, no auth required; HF_TOKEN is fine to have set but optional.
for adapter in gem4_4B_adapter gem4_26B_adapter; do
    dest="$REPO_ROOT/models/$adapter"
    if [[ -s "$dest/adapter_model.safetensors" ]]; then
        skip "$adapter cached at models/$adapter"
    else
        log "Downloading Gayagaya/$adapter → models/$adapter"
        if uv run hf download "Gayagaya/$adapter" --local-dir "$dest"; then
            ok "$adapter ready"
        else
            warn "$adapter download failed. The 26B/4B GEM4 wrapper scripts will not work without it."
            USER_ACTION=1
        fi
    fi
done

# --- Public datasets ------------------------------------------------------
# Each entry is "<hf_repo_id> -> <local path under repo root>". All public,
# no auth required. Empty placeholder repos (only .gitattributes) are
# detected and reported, not failed.
declare -A DATASETS=(
    ["Gayagaya/SO101_dataset"]="$REPO_ROOT/data/SO101"
    ["Gayagaya/fisheye_videos_processed"]="$REPO_ROOT/data/video"
    ["takaki99/GEM4_open_the_jar"]="$REPO_ROOT/data/GEM4_open_the_jar"
    ["takaki99/GEM4_pick_up_bottle"]="$REPO_ROOT/data/GEM4_pick_up_bottle"
    ["takaki99/GEM4_replace_the_cookie"]="$REPO_ROOT/data/GEM4_replace_the_cookie"
)
for repo_id in "${!DATASETS[@]}"; do
    dest="${DATASETS[$repo_id]}"
    label="${dest#$REPO_ROOT/}"
    if [[ -d "$dest" ]] && [[ -n "$(ls "$dest" 2>/dev/null | head -1)" ]]; then
        skip "$repo_id cached at $label"
        continue
    fi
    log "Downloading $repo_id → $label"
    mkdir -p "$dest"
    if uv run hf download "$repo_id" --local-dir "$dest" --repo-type dataset; then
        n_files=$(find "$dest" -type f -not -name ".gitattributes" -not -path "*/.cache/*" | wc -l)
        if [[ "$n_files" -eq 0 ]]; then
            warn "$repo_id is empty on the Hub (placeholder?). Skipping."
            rmdir "$dest" 2>/dev/null || true
        else
            ok "$repo_id ready ($n_files files)"
        fi
    else
        warn "$repo_id download failed (network? gated?). Pipeline may still work without it."
    fi
done

if [[ "$USER_ACTION" -eq 1 ]]; then
    exit "$STEP_USER"
fi
exit "$STEP_OK"
