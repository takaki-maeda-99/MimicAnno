#!/bin/bash
# One-shot environment setup for MimicAnno hand pipeline.
#
# Sets up three environments from scratch:
#   1. UniDAC  — conda env "unidac"  (Phase A depth precomputation)
#   2. HaMeR   — venv  hamer/.hamer  (Phase B hand pose estimation)
#   3. MimicAnno core — uv venv .venv
#
# Usage:
#   bash scripts/setup_envs.sh            # set up all three
#   bash scripts/setup_envs.sh --unidac   # UniDAC only
#   bash scripts/setup_envs.sh --hamer    # HaMeR only
#   bash scripts/setup_envs.sh --core     # MimicAnno core only
#
# Manual prerequisite (HaMeR):
#   Register at https://mano.is.tue.mpg.de and place MANO_RIGHT.pkl at:
#   hamer/_DATA/data/mano/MANO_RIGHT.pkl
#
# After setup, run the pipeline with:
#   bash scripts/run_all_pipeline.sh

set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$PWD"

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✓ $*"; }
warn() { echo "[$(date '+%H:%M:%S')] ! $*"; }

# ---------------------------------------------------------------------------
# Argument parsing (default: all)
DO_UNIDAC=0
DO_HAMER=0
DO_CORE=0
if [[ $# -eq 0 ]]; then
    DO_UNIDAC=1; DO_HAMER=1; DO_CORE=1
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --unidac) DO_UNIDAC=1; shift ;;
        --hamer)  DO_HAMER=1;  shift ;;
        --core)   DO_CORE=1;   shift ;;
        --help|-h)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# 1. UniDAC conda environment
# ---------------------------------------------------------------------------
if [[ $DO_UNIDAC -eq 1 ]]; then
    log "=== UniDAC conda env ==="

    if conda env list 2>/dev/null | grep -q '^unidac '; then
        ok "conda env 'unidac' already exists — skipping create"
    else
        log "Creating conda env 'unidac' (python=3.10)…"
        conda create -n unidac python=3.10 -y
    fi

    log "Installing PyTorch (cu118) into unidac…"
    conda run -n unidac pip install \
        torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
        --index-url https://download.pytorch.org/whl/cu118

    log "Installing UniDAC requirements…"
    conda run -n unidac pip install -r "$REPO_ROOT/UniDAC/requirements.txt"

    log "Installing UniDAC package (editable)…"
    conda run -n unidac pip install -e "$REPO_ROOT/UniDAC" --no-deps

    # Verify weights
    if [[ ! -f "$REPO_ROOT/UniDAC/checkpoints/unidac.pt" ]]; then
        warn "UniDAC weights not found at UniDAC/checkpoints/unidac.pt"
        warn "Download from the UniDAC release and place them there."
    else
        ok "UniDAC weights found"
    fi

    ok "UniDAC setup complete"
fi

# ---------------------------------------------------------------------------
# 2. HaMeR venv
# ---------------------------------------------------------------------------
if [[ $DO_HAMER -eq 1 ]]; then
    log "=== HaMeR venv ==="

    HAMER_ROOT="$REPO_ROOT/hamer"
    HAMER_VENV="$HAMER_ROOT/.hamer"
    HAMER_PY="$HAMER_VENV/bin/python"

    if [[ -f "$HAMER_PY" ]]; then
        ok "HaMeR venv already exists at hamer/.hamer — skipping create"
    else
        log "Creating HaMeR venv (requires python3.10)…"
        python3.10 -m venv "$HAMER_VENV"
    fi

    log "Installing PyTorch (cu124) into HaMeR venv…"
    "$HAMER_VENV/bin/pip" install \
        torch==2.6.0 torchvision==0.21.0 \
        --index-url https://download.pytorch.org/whl/cu124

    log "Installing HaMeR package [all]…"
    "$HAMER_VENV/bin/pip" install -e "$HAMER_ROOT[all]"

    log "Installing ViTPose (third-party)…"
    "$HAMER_VENV/bin/pip" install -v -e "$HAMER_ROOT/third-party/ViTPose"

    # Install scipy (needed for pipeline.py + run_hand_estimation.py)
    "$HAMER_VENV/bin/pip" install scipy

    # Fetch HaMeR demo data (model weights) if not already present
    if [[ -d "$HAMER_ROOT/_DATA/hamer_ckpts" ]]; then
        ok "HaMeR model weights already present"
    else
        log "Downloading HaMeR demo data (requires gdown / internet access)…"
        (cd "$HAMER_ROOT" && bash fetch_demo_data.sh)
    fi

    # Check MANO weights (requires manual registration)
    if [[ ! -f "$HAMER_ROOT/_DATA/data/mano/MANO_RIGHT.pkl" ]]; then
        warn "MANO_RIGHT.pkl not found."
        warn "Register at https://mano.is.tue.mpg.de and place the file at:"
        warn "  hamer/_DATA/data/mano/MANO_RIGHT.pkl"
    else
        ok "MANO_RIGHT.pkl found"
    fi

    ok "HaMeR setup complete"
fi

# ---------------------------------------------------------------------------
# 3. MimicAnno core (uv)
# ---------------------------------------------------------------------------
if [[ $DO_CORE -eq 1 ]]; then
    log "=== MimicAnno core (uv) ==="

    if ! command -v uv &>/dev/null; then
        warn "uv not found. Install with: curl -Ls https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    log "Running uv sync (core + dev + vlm + sam3)…"
    uv sync --extra dev --extra vlm --extra sam3

    ok "MimicAnno core setup complete"
fi

# ---------------------------------------------------------------------------
log "=== All done ==="
log "Run the pipeline:"
log "  bash scripts/run_all_pipeline.sh [VIDEO_NAME ...]"
