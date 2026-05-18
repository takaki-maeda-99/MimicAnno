# scripts/

Helper scripts for MimicAnno. Two groups:

- **Hand pipeline** (`precompute_depth.py`, `run_hand_estimation.py`, `run_all_pipeline.sh`, `visualize_depth.py`) — GoPro fisheye → metric 3D hand pose. See [`docs/hand-pipeline.md`](../docs/hand-pipeline.md) for the data contract.
- **Annotation batch runners** (`batch_*.sh`, `batch_*.py`, `run_26B_*.sh`, `rebatch_*.sh`) — wrappers around `mimicanno annotate` for specific robots / tasks.
- **Setup & UI** (`setup_envs.sh`, `start_ui.sh`) — environment bootstrap and dev-server orchestrator.

---

## Hand pipeline

### `precompute_depth.py` — Phase A

Runs UniDAC (Preset A) over every frame of a fisheye video and saves euclid-distance depth maps as `.npy` files.

**Environment:** `conda activate unidac`

**Input:** MP4 video or directory of images (JPEG/PNG)

**Output layout:**

```
<out>/frames/frame_NNNNNN.npy    # float32 (512, 704) — ERP euclid depth [m]
<out>/meta.json
<out>/viz/erp.mp4                # colorized ERP depth (--save-viz, default on)
<out>/viz/depth_fisheye.mp4      # back-warped to fisheye space (--save-viz)
```

**Usage:**

```bash
conda activate unidac
PYTHONPATH=/path/to/MimicAnno:/path/to/MimicAnno/UniDAC \
python scripts/precompute_depth.py \
    --input data/video/new/GX010085.MP4 \
    --out   data/depth/GX010085/
```

**Key args:**

| Arg | Default | Description |
|-----|---------|-------------|
| `--input` | required | Video file or image directory |
| `--out` | required | Output directory |
| `--stride` | 1 | Process every N-th frame |
| `--preset` | `A` | UniDAC preset (`A` or `B`) |
| `--device` | auto | Torch device, e.g. `cuda:0` |
| `--overwrite` | off | Re-process frames whose `.npy` already exists |
| `--limit` | — | Stop after N frames (debug) |
| `--no-viz` | — | Skip writing visualization videos |
| `--viz-depth-range MIN MAX` | `0.3 5.0` | Colormap range in metres |

Runs are resumable: existing `.npy` files are skipped unless `--overwrite` is set.

### `run_hand_estimation.py` — Phase B

Reads precomputed UniDAC depth from Phase A, runs the hand backend (MediaPipe Hand Landmarker) frame-by-frame, and fuses depth into metric hand poses.

**Environment:** `.venv` (uv) — `uv run python scripts/run_hand_estimation.py …`

**Two-pass architecture:**

- **Pass 1** — Per-frame detection + UniDAC wrist depth sampling → `frames/frame_NNNNNN.pkl`
- **Pass 2** — Temporal gap-filling: for each hand side, linearly interpolate `wrist_depth_m` across gaps of up to `--max-interp-gap` consecutive frames where depth was unavailable. Re-saves corrected `.pkl` files.
- **Post-pass** — Generates `signals.json` (smoothed pinch distance) and `viz/overlay.mp4`.

**Output layout:**

```
<out>/frames/frame_NNNNNN.pkl    # list[HandEstimate] ([] if no hands detected)
<out>/meta.json
<out>/signals.json               # per-frame pinch distance (Gaussian smoothed)
<out>/viz/overlay.mp4            # 2D keypoints overlaid on source frames
```

**Usage:**

```bash
PYTHONPATH=/path/to/MimicAnno:/path/to/MimicAnno/UniDAC \
uv run python scripts/run_hand_estimation.py \
    --video data/video/new/GX010085.MP4 \
    --depth data/depth/GX010085 \
    --out   data/hands/GX010085
```

**Key args:**

| Arg | Default | Description |
|-----|---------|-------------|
| `--video` | required | Source MP4 |
| `--depth` | required | Phase A output directory |
| `--out` | required | Output directory |
| `--stride` | from `depth/meta.json` | Frame subsampling |
| `--max-interp-gap` | 5 | Max consecutive missing-depth frames to interpolate |
| `--overwrite` | off | Reprocess frames whose `.pkl` exists |
| `--limit` | — | Stop after N frames (debug) |
| `--no-viz` | — | Skip `viz/overlay.mp4` |
| `--viz-keypoints` | off | Draw all 21 joints + skeleton (default: wrist only) |
| `--pinch-smooth-sigma` | 2.0 | Gaussian smoothing sigma [frames] for `signals.json` |
| `--full-signals` | off | Write extended `signals.json` with `cam_t` + `euler_deg` + `joints_2d` |
| `--signals-only` | off | Skip inference; regenerate `signals.json` from existing `.pkl` files |

Runs are resumable: `.pkl` files that already exist are loaded and skipped in Pass 1.

`HandEstimate` field reference and `signals.json` schema: [`docs/hand-pipeline.md`](../docs/hand-pipeline.md).

### `run_all_pipeline.sh`

Batch runner that processes multiple fisheye videos through Phase A and Phase B in parallel across two GPUs.

```bash
bash scripts/run_all_pipeline.sh                       # all 2704x1520 fisheye videos
bash scripts/run_all_pipeline.sh GX010175 GX010176     # specific videos only
bash scripts/run_all_pipeline.sh --gpus 0 1            # override GPU indices (default: 2 3)
bash scripts/run_all_pipeline.sh --skip-phase-a        # depth already precomputed
bash scripts/run_all_pipeline.sh --overwrite           # ignore existing outputs
```

**Skip logic:** Phase A is skipped for a video if `data/depth/<NAME>/meta.json` exists and `interrupted=false`. Phase B is skipped if `data/hands/<NAME>/meta.json` exists and `pass1_complete=true` and `interrupted=false`.

**Logs:** per-video logs at `/tmp/phaseA_<NAME>.log` and `/tmp/phaseB_<NAME>.log`. A summary table is printed on completion.

### `visualize_depth.py`

Loads precomputed `.npy` depth files from Phase A, back-warps them from ERP to fisheye, and writes colorized output (side-by-side with the source video by default).

```bash
PYTHONPATH=/path/to/MimicAnno:/path/to/MimicAnno/UniDAC \
conda run -n unidac python scripts/visualize_depth.py \
    --depth data/depth/GX010085 \
    --video data/video/new/GX010085.MP4 \
    --out   data/depth/GX010085/viz.mp4
```

Useful flags: `--frames 0,5,10` (specific indices), `--stride N`, `--scale 0.5`, `--no-side-by-side`, `--colormap {plasma,viridis,magma,jet}`.

---

## Annotation batch runners

Thin wrappers around `mimicanno annotate` for specific dataset / robot / model combinations. All require the relevant model weights and `RUNS_ROOT` to be set.

| Script | What it runs |
|--------|--------------|
| `batch_annotate.py` | Generic batch over a dataset directory (configurable robot + VLM) |
| `batch_annotate_4B.py` | Same, pinned to Gemma 4 E4B with shared SAM3 runtime |
| `batch_so101_phase4*.sh` | SO101 + phase-4 smoother variants (v4 / v5 / overlay) |
| `batch_piper_phase4.sh` | Marker_pickup_piper dataset, phase-4 |
| `batch_gem4.sh` | GEM4 (3 task suite), 4B VLM |
| `run_26B_gem4_<task>.sh` | GEM4 with 26B QLoRA adapter, one script per task (`open_the_jar`, `pick_up_bottle`, `replace_the_cookie`). Requires `unsloth_env` and `models/gem4_26B_adapter/` |
| `run_26B_so101.sh` | SO101 with 26B QLoRA adapter |
| `rebatch_*.sh` | Re-runs that skip already-completed episodes |
| `prep_piper_episodes.py` | Pre-processing for Marker_pickup_piper raw data |

Common env overrides: `GPU`, `START`, `END`, `RUNS_ROOT`, `LOGS_DIR`, `VLM_DUMP_ROOT`, `SAM3`.

Inspection helpers: `aggregate_gemma_pairs.py`, `show_gemma_outputs.py`, `summarize_so101_runs.py`, `smoke_sam3_*.py`, `transcode_viz_to_h264.py`.

---

## Setup & UI

### `setup_envs.sh`

One-shot environment setup. Idempotent — existing environments are detected and skipped.

| Flag | Environment | Purpose | Python |
|------|-------------|---------|--------|
| `--unidac` | `conda env: unidac` | Phase A — UniDAC depth | 3.10 |
| `--core` | `.venv` (uv) | MimicAnno core + Phase B hand inference | 3.11+ |
| `--frontend` | `frontend/node_modules` | React/Vite review UI | — |
| `--weights` | model downloads (HF) | SAM3 + Gemma 4 | — |

```bash
bash scripts/setup_envs.sh                       # --all (default)
bash scripts/setup_envs.sh --core --frontend     # UI-only path
bash scripts/setup_envs.sh --all --skip-weights  # no model DLs
bash scripts/setup_envs.sh --unidac              # UniDAC only
```

For the `weights` step, set `HF_TOKEN` or run `hf auth login` beforehand.

**Manual prerequisite:** UniDAC weights — place at `UniDAC/checkpoints/unidac.pt` and `UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth`.

### `start_ui.sh`

Launches the FastAPI backend (port 8000) and the Vite dev server (port 5173) together. Probes for free ports, waits on either process exiting, and tears both down on Ctrl-C.

```bash
bash scripts/start_ui.sh                                  # defaults
API_PORT=8001 VITE_PORT=5174 bash scripts/start_ui.sh     # override ports
bash scripts/start_ui.sh --runs-root /path/to/runs        # custom runs root
```
