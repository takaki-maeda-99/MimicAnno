# scripts/

Helper scripts for the MimicAnno hand pipeline. The pipeline runs in two sequential phases:

- **Phase A** (`precompute_depth.py`) — UniDAC depth precomputation, runs in `conda activate unidac`
- **Phase B** (`run_hand_estimation.py`) — HaMeR pose estimation + depth fusion, runs in the HaMeR venv

See also: [Hand Pipeline section in README.ja.md](../README.ja.md#hand-pipeline-phase-a--b).

---

## precompute_depth.py

**Phase A.** Runs UniDAC (Preset A) over every frame of a fisheye video and saves euclid-distance depth maps as `.npy` files.

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
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
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

---

## run_hand_estimation.py

**Phase B.** Reads precomputed UniDAC depth from Phase A and runs HaMeR frame-by-frame, fusing depth into metric hand poses.

**Environment:** `hamer/.hamer/bin/python`

**Two-pass architecture:**

- **Pass 1** — Per-frame HaMeR detection + UniDAC wrist depth sampling → `frames/frame_NNNNNN.pkl`
- **Pass 2** — Temporal gap-filling: for each hand side, linearly interpolate `wrist_depth_m` across gaps of up to `--max-interp-gap` consecutive frames where depth was unavailable. Re-saves corrected `.pkl` files.
- **Post-pass** — Generates `signals.json` (smoothed pinch distance) and `viz/overlay.mp4`.

**Input:**

- `--video` — source MP4
- `--depth` — Phase A output directory

**Output layout:**

```
<out>/frames/frame_NNNNNN.pkl    # list[HandEstimate] ([] if no hands detected)
<out>/meta.json
<out>/signals.json               # per-frame pinch distance (Gaussian smoothed)
<out>/viz/overlay.mp4            # 2D keypoints overlaid on source frames
```

**Usage:**

```bash
CUDA_VISIBLE_DEVICES=2 \
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
hamer/.hamer/bin/python scripts/run_hand_estimation.py \
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
| `--rescale-factor` | 2.0 | HaMeR ViTDet bbox expansion factor |
| `--batch-size` | 8 | HaMeR DataLoader batch size |
| `--pinch-smooth-sigma` | 2.0 | Gaussian smoothing sigma [frames] for `signals.json` |
| `--full-signals` | off | Write schema_version 2 `signals.json` with `cam_t` + `euler_deg` |
| `--signals-only` | off | Skip HaMeR; regenerate `signals.json` from existing `.pkl` files |

Runs are resumable: `.pkl` files that already exist are loaded and skipped in Pass 1 (depth interpolation is skipped for those frames since raw HaMeR output is not cached).

**`signals.json` format (schema_version 1, default):**

```json
{
  "schema_version": 1,
  "frame_000060": {
    "right": {"value": 0.0811, "depth_ok": true},
    "left": null
  }
}
```

`value` is the Gaussian-smoothed `pinch_distance_m` in metres. `depth_ok` is `true` when `wrist_depth_m` is available. Frames where neither hand was detected are omitted. With `--full-signals`, schema_version 2 adds `cam_t` and `euler_deg` per hand.

---

## run_all_pipeline.sh

Batch runner that processes multiple fisheye videos through Phase A and Phase B in parallel across two GPUs.

**Usage:**

```bash
# All 2704x1520 fisheye videos in data/video/new/
bash scripts/run_all_pipeline.sh

# Specific videos only
bash scripts/run_all_pipeline.sh GX010175 GX010176

# Override GPU indices (default: 2 3)
bash scripts/run_all_pipeline.sh --gpus 0 1

# Skip Phase A (depth already precomputed)
bash scripts/run_all_pipeline.sh --skip-phase-a

# Overwrite existing outputs
bash scripts/run_all_pipeline.sh --overwrite
```

**GPU assignment:** videos are split into two equal batches (even/odd index) and processed sequentially within each batch. By default GPUs 2 and 3 are used.

**Skip logic:** Phase A is skipped for a video if `data/depth/<NAME>/meta.json` exists and `interrupted=false`. Phase B is skipped if `data/hands/<NAME>/meta.json` exists and `pass1_complete=true` and `interrupted=false`.

**Logs:** per-video logs are written to `/tmp/phaseA_<NAME>.log` and `/tmp/phaseB_<NAME>.log`.

After completion, a summary table is printed showing frames processed, hand detection rate, depth-missing count, and failures per video.

---

## setup_envs.sh

One-shot environment setup. Creates and installs all three environments from scratch.

**Environments created:**

| Flag | Environment | Purpose | Python |
|------|-------------|---------|--------|
| `--unidac` | `conda env: unidac` | Phase A — UniDAC depth | 3.10 |
| `--hamer` | `hamer/.hamer` venv | Phase B — HaMeR pose | 3.10 |
| `--core` | `.venv` (uv) | MimicAnno core | 3.11+ |

**Usage:**

```bash
bash scripts/setup_envs.sh            # all three
bash scripts/setup_envs.sh --unidac   # UniDAC only
bash scripts/setup_envs.sh --hamer    # HaMeR only
bash scripts/setup_envs.sh --core     # MimicAnno core only
```

**What each step does:**

- `--unidac`: creates `conda env unidac` (Python 3.10), installs PyTorch 2.7.0 (cu118), installs `UniDAC/requirements.txt`, installs UniDAC editable.
- `--hamer`: creates `hamer/.hamer` venv (Python 3.10), installs PyTorch 2.6.0 (cu124), installs `hamer[all]`, installs ViTPose from `hamer/third-party/`, installs scipy, downloads HaMeR demo data via `fetch_demo_data.sh` (requires internet + gdown).
- `--core`: runs `uv sync --extra dev --extra vlm --extra sam3`.

All steps are idempotent: existing environments are detected and skipped.

**Manual prerequisites (not automated):**

- MANO model: register at https://mano.is.tue.mpg.de and place `MANO_RIGHT.pkl` at `hamer/_DATA/data/mano/MANO_RIGHT.pkl`
- UniDAC weights: place at `UniDAC/checkpoints/unidac.pt` and `UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth`

---

## visualize_depth.py

Loads precomputed `.npy` depth files from Phase A, back-warps them from ERP space to the fisheye image grid, and writes colorized output.

**Environment:** `conda activate unidac` (needs `_back_warp_depth` from `mimicanno.hand_pipeline.pipeline`)

**Usage:**

```bash
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
/home/gayagaya/anaconda3/envs/unidac/bin/python scripts/visualize_depth.py \
    --depth data/depth/GX010085 \
    --video data/video/new/GX010085.MP4 \
    --out   data/depth/GX010085/viz.mp4

# Single PNG for one frame
python scripts/visualize_depth.py \
    --depth data/depth/GX010085 \
    --video data/video/new/GX010085.MP4 \
    --out   data/depth/GX010085/frame0.png \
    --frames 0

# Depth only, every 5th frame, half resolution
python scripts/visualize_depth.py \
    --depth data/depth/GX010086 \
    --out   data/depth/GX010086/depth_only.mp4 \
    --stride 5 --scale 0.5 --no-side-by-side
```

Default output is side-by-side (original | depth) at 0.5x scale. The colormap range is estimated automatically from the 2nd–98th percentile of a random sample of frames.

**Key args:**

| Arg | Default | Description |
|-----|---------|-------------|
| `--depth` | required | Phase A output directory |
| `--out` | required | Output `.mp4` or `.png` |
| `--video` | — | Source MP4 for side-by-side mode |
| `--frames` | all | Comma-separated frame indices |
| `--stride` | 1 | Render every N-th frame |
| `--scale` | 0.5 | Output scale relative to 2704x1520 |
| `--no-side-by-side` | off | Depth only (no original video column) |
| `--colormap` | `plasma` | One of `plasma`, `viridis`, `magma`, `jet` |
| `--device` | auto | Torch device for back-warp |
