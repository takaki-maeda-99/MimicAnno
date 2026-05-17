# MimicAnno

**English** | [日本語](README.ja.md)

Offline subtask annotation for robot imitation-learning episodes. Take a LeRobot v3 dataset, get back per-frame subtask labels (`approach_object`, `grasp_object`, …) and a SARM-trainable parquet output.

```
LeRobot v3 episode (video + state + action + task text)
        │
        ▼  mimicanno annotate
runs/<canonical>/{annotation.json, manifest.json, ...}
        │
        ▼  mimicanno export
SARM-trainable LeRobot v3 dataset (subtask_index + sidecar)
```

## Features

- **Signal-driven boundary detection** — gripper transitions, EEF velocity valleys, action-norm change points (no ML for boundaries).
- **VLM phase labeling** — Gemma 4 (or any image-text-to-text HF model) per segment, with allowed-label enforcement and JSON-schema validation.
- **SAM3 object tracking** — task-text-driven prompt generation, sampled-frame propagation, integrated boundary score.
- **Temporal smoothing** — same-label merge, min-duration absorb, optional Viterbi relabel.
- **SARM-ready export** — per-frame `subtask_index`, per-episode subtask lists, lossless `mimicanno_segments.parquet` sidecar, atomic publish, idempotent reuse.
- **Read-only React/Vite viewer** — timeline + waveforms + boundary markers (`frontend/`).
- **Pluggable robot adapters** — built-in for SO100 / Koch / Aloha; YAML-configurable for SO101 and arbitrary LeRobot v3 layouts.

## Install

Requires Linux + `uv`, `conda`, `python3.10`, `node` (>=20), `pnpm`, `ffmpeg`, `git`, `curl`, `lsof`.

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno

# One-shot bootstrap (submodules, core, unidac, hamer, frontend, gated weights).
# Set HF_TOKEN or run `hf auth login` first for SAM3 / Gemma 4.
bash scripts/setup_envs.sh

# Selective install (skip steps you don't need):
bash scripts/setup_envs.sh --core --frontend     # UI-only path
bash scripts/setup_envs.sh --all --skip-weights  # no model DLs

# Re-runs are idempotent (each step skips when its sentinel is satisfied).
```

Manual step: register at https://mano.is.tue.mpg.de and place `MANO_RIGHT.pkl` at
`hamer/_DATA/data/mano/MANO_RIGHT.pkl` (license-gated, cannot be scripted).

Launch the review UI:

```bash
bash scripts/start_ui.sh                                  # :8000 / :5173
API_PORT=8001 VITE_PORT=5174 bash scripts/start_ui.sh
bash scripts/start_ui.sh --runs-root /path/to/runs
```

## Quickstart

### 1. Annotate one episode

```bash
mimicanno annotate \
  --video        path/to/dataset/videos/.../episode_000000.mp4 \
  --parquet      path/to/dataset/data/.../episode_000000.parquet \
  --task         "Put the tape into the bottle" \
  --robot        generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it@<sha>" \
  --sam3-checkpoint /path/to/sam3.ckpt \
  --runs-root    ./runs
```

Produces `runs/<canonical_name>/{manifest,annotation,boundaries,signals,tracks}.json`. Re-running with the same config and inputs is a no-op.

Phases are cumulative: `--target-phase 1` (boundaries only, no VLM/SAM3 needed), `--target-phase 2` (+ VLM), `--target-phase 3` (+ SAM3, requires checkpoint), `--target-phase 4` (+ smoothing).

CPU-only or driver-mismatched? Add:

```bash
--vlm-device cpu --vlm-timeout-sec 600
```

(Expect roughly 1 hour on CPU vs ~1 minute on a recent GPU for an 8-segment episode.)

### 2. Export to a SARM-trainable dataset

```bash
mimicanno export \
  --dataset      path/to/dataset \
  --runs-root    ./runs \
  --target-phase 4 \
  --profile      so101_sarm \
  --out          path/to/dataset_annotated
```

Default `--symlink-data` mode produces `dataset_annotated/` with `videos/` symlinked from the source, `data/` augmented with `subtask_index` + canonical action columns, and a fresh `meta/` containing `subtasks.parquet`, `episodes/.../file-NNN.parquet` (with `<prefix>_subtask_*` lists), and a lossless `mimicanno_segments.parquet` sidecar.

Other modes:
- `--copy-data` — fully independent copy (no symlinks).
- `--in-place --yes-i-mean-it` — mutate the source dataset; creates `<source>/.mimicanno-backup-<ISO>/` for rollback.

Idempotent: re-running with identical args short-circuits to a no-op.

### 3. Inspect the output

```bash
uv run python -c "
import pyarrow.parquet as pq
sub = pq.read_table('dataset_annotated/meta/subtasks.parquet')
print('phases used:', sub.to_pylist())

ep0 = pq.read_table('dataset_annotated/data/chunk-000/episode_000000.parquet')
print('per-frame subtask_index distribution:')
sti = ep0.column('subtask_index').to_pylist()
for v in sorted(set(sti)):
    print(f'  index={v} ({sub.to_pylist()[v][\"subtask\"]}): {sti.count(v)} frames')
"
```

Example output for SO101 ep0 ("Put the tape into the bottle"):

```
phases used: [{'subtask': 'approach_object', 'subtask_index': 0, 'description': ''},
              {'subtask': 'grasp_object',    'subtask_index': 1, 'description': ''}]
per-frame subtask_index distribution:
  index=0 (approach_object): 121 frames
  index=1 (grasp_object):     30 frames
```

### 4. Programmatic API

```python
from mimicanno import export, ExportProfile

result = export(
    dataset_root="/path/to/dataset",
    runs_root="./runs",
    target_phase=4,
    profile="so101_sarm",            # name, or path to a YAML
    out="/path/to/dataset_annotated",
    output_mode="symlink",           # "symlink" | "copy" | "in_place"
)
print(result.episode_count, result.subtask_count, result.reused)
```

## Supported robots

| Adapter | Notes |
|---|---|
| `aloha` | LeRobot v3 with aggregated 14-D `observation.state`, Cartesian EEF available |
| `koch` | Joint-only, 6-D `observation.state` |
| `so100` | Joint-only, 6-D `observation.state` (used by `lerobot/svla_so100_pickplace`) |
| `generic` | Configurable via YAML — supports split-state layouts (SO101 etc.) and direct rotvec passthrough |

Generic adapter example for SO101 (`tests/exports/fixtures/so101_robot_config.yaml`):

```yaml
schema_version: "0.2.0"
name: so101
gripper_column:        observation.state.gripper_pos
gripper_scale_min:     0.0
gripper_scale_max:     60.0   # SO101 raw range across 36 ep: 3.95..53.79; 60 = +12% headroom
eef_xyz_column:        observation.state.ee_pos
eef_rotvec_column:     observation.state.ee_rotvec
eef_quat_column:       null
```

To support a new robot, copy this template, name the right columns, and pass it via `--robot-config`. No code changes required.

## Export profiles

Three default profiles ship under `mimicanno/configs/exports/`:

- `so101_sarm.yaml` — SO101 via the generic adapter, body-frame `ee_delta_6d` + gripper extras, `mimicanno_*` column prefix.
- `aloha_sarm.yaml` — Aloha-specific.
- `generic.yaml` — minimal template for new datasets.

Profile YAML controls everything about the export: source adapter, action representation (`body_frame_t` / `world` / `base` delta basis), per-frame extra columns, sidecar location, and gates (`require_reviewed`, `forbid_unlabeled_segments`, `forbid_degraded_pipeline`). Validated against `mimicanno/jsonschemas/export_profile.schema.json`.

## Hand Pipeline — Environment Setup

The hand pipeline uses two environments separate from the MimicAnno core.

### One-shot setup

```bash
bash scripts/setup_envs.sh          # all three environments
bash scripts/setup_envs.sh --unidac # UniDAC only
bash scripts/setup_envs.sh --hamer  # HaMeR only
bash scripts/setup_envs.sh --core   # MimicAnno core only
```

Existing environments are skipped (idempotent).

### Three environments

| Environment | Purpose | Python |
|-------------|---------|--------|
| `conda env: unidac` | Phase A depth precomputation (UniDAC) | 3.10 |
| `hamer/.hamer` venv | Phase B hand pose estimation (HaMeR) | 3.10 |
| `.venv` (uv) | MimicAnno core / annotation | 3.11+ |

### Files that require manual download

#### MANO model (required for HaMeR)

1. Register and download from [https://mano.is.tue.mpg.de](https://mano.is.tue.mpg.de)
2. Place at:

```
hamer/_DATA/data/mano/MANO_RIGHT.pkl
```

#### UniDAC model weights

```
UniDAC/checkpoints/unidac.pt
UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth
```

HaMeR demo data (`hamer/_DATA/hamer_ckpts/` etc.) is downloaded automatically by `setup_envs.sh` via `fetch_demo_data.sh` (gdown + Google Drive; internet access required).

## Hand Pipeline (Phase A / B)

Sub-pipeline that extracts per-frame 3D hand pose and finger distances from GoPro Hero 11 Max Lens Mod fisheye footage.

### Input requirements

| Item | Value |
|------|-------|
| Video resolution | **2704 × 1520** (fisheye only) |
| Frame rate | 29.97 fps |
| Camera model | OPENCV_FISHEYE (equidistant, k1..k4 = 0) |
| Focal length (reference width) | fl_x = 1820 px, fl_y = 1275 px (at 5312 px native width) |

Non-fisheye resolutions (e.g. 1920×1080) are skipped automatically by `run_all_pipeline.sh`.

### Phase A — depth precomputation (`scripts/precompute_depth.py`)

Runs UniDAC (Preset A) to produce a per-frame ERP depth map.

| Item | Value |
|------|-------|
| Environment | `conda activate unidac` |
| Input | `data/video/new/<NAME>.MP4` |
| Output `.npy` shape | `(512, 704)` float32 — ERP-patch euclid distance [m] |
| Output path | `data/depth/<NAME>/frames/frame_NNNNNN.npy` |
| Metadata | `data/depth/<NAME>/meta.json` |

> UniDAC outputs **ray distance (euclid distance), not Z-depth**.  
> Back-projection: `cam_t = depth × unit_ray`

### Phase B — hand pose estimation (`scripts/run_hand_estimation.py`)

Fuses HaMeR (MANO) with Phase A depth to produce metric hand poses.

| Item | Value |
|------|-------|
| Environment | `hamer/.hamer/bin/python` + `CUDA_VISIBLE_DEVICES=N` |
| Input video | `data/video/new/<NAME>.MP4` |
| Input depth | `data/depth/<NAME>/` (Phase A output) |
| Per-frame output | `data/hands/<NAME>/frames/frame_NNNNNN.pkl` — `list[HandEstimate]` |
| Time-series output | `data/hands/<NAME>/signals.json` |
| Metadata | `data/hands/<NAME>/meta.json` |

### `HandEstimate` fields

| Field | Shape / type | Description |
|-------|-------------|-------------|
| `is_right` | `bool` | Whether this is the right hand |
| `cam_t` | `(3,)` float32 | Metric wrist position [m] in camera frame (x, y, z) |
| `global_orient` | `(3, 3)` float32 | Wrist rotation matrix |
| `hand_pose` | `(15, 3, 3)` float32 | Finger joint rotation matrices (15 joints) |
| `betas` | `(10,)` float32 | MANO shape parameters |
| `joints_3d` | `(21, 3)` float32 | All joint 3D positions [m] in camera frame |
| `joints_2d` | `(21, 2)` float32 | All joint 2D projections (pinhole approximation) |
| `bbox` | `(4,)` float32 | Detection bbox [x1, y1, x2, y2] in pixels |
| `wrist_depth_m` | `float \| None` | UniDAC wrist depth [m]. `None` = depth unavailable |
| `depth_interpolated` | `bool` | `True` = gap-filled by temporal interpolation |
| `pinch_distance_m` | `float \| None` | Thumb tip – index tip distance [m]. Valid whenever a hand is detected |

MANO joint indices: wrist=0, thumb_tip=4, index_tip=8 (standard 21-point skeleton).

### `signals.json` schema

```json
{
  "schema_version": 1,
  "frame_000060": {
    "right": {"value": 0.0811, "depth_ok": true},
    "left": null
  }
}
```

- `value`: Gaussian-smoothed (σ=2 frames) `pinch_distance_m` [m]
- `depth_ok`: whether `wrist_depth_m` is non-`None` (UniDAC depth correction applied)
- Frames with no detected hand are omitted entirely
- `value` is valid even when `depth_ok=false` (MANO metric scale)

### Batch execution

```bash
# All fisheye videos, parallel on GPU 2 and 3
bash scripts/run_all_pipeline.sh

# Specific videos only
bash scripts/run_all_pipeline.sh GX010175 GX010176

# Skip Phase A (depth already computed)
bash scripts/run_all_pipeline.sh --skip-phase-a

# Override GPU indices
bash scripts/run_all_pipeline.sh --gpus 0 1
```

## Viewer

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:5173/?run=<canonical_name>
```

Read-only timeline / waveform viewer for run directories. Edit affordances are deferred to Phase 5B (not started).

## Server (Phase 5 A read-only + Phase 5 B r1 edit)

An HTTP backend that serves the same JSON shapes as the static `runs/`
tree and accepts phase-relabel edits with optimistic locking. Installed
lazily via the `[server]` optional dependency group.

```bash
uv sync --extra server
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
    --runs-root runs/ \
    --host 127.0.0.1 --port 8000 \
    --cors-origin http://localhost:5173
```

`MIMICANNO_REVIEWER` is captured at startup and stamped as `reviewer_id`
on every edit; unset/empty → `reviewer_id=null` on persisted segments.

Endpoints:
- `GET /healthz` — liveness probe
- `GET /api/runs/index.json` — same shape as the static `runs/index.json`
- `GET /api/runs/<canonical_name>/<artifact>` — `manifest.json`, `annotation.json`, `boundaries.json`, `signals.json`, `tracks.json` (allow-list)
- `GET /api/labelset` — labelset doc `{labels:[{id, requires_object}], labels_yaml_sha256}` with `Cache-Control: public, max-age=300`
- `PATCH /api/runs/<canonical_name>/segments/<segment_id>` — change a segment's `phase` with `If-Match: "<run_hash>"` optimistic locking; returns the new manifest + `ETag: "<new_run_hash>"`. Status codes: `200 / 400 (invalid_body|invalid_label|invalid_name|invalid_segment) / 404 (run_not_found) / 405 / 412 (etag_mismatch) / 415 / 428 (etag_required)`.

Behaviour:
- Manifest GET responses carry `ETag: "<run_hash>"`; clients reuse it as `If-Match` on PATCH.
- A successful PATCH atomically rewrites annotation → manifest → index under a `runs/index.json.lock` file lock, with the edit attributed to `MIMICANNO_REVIEWER` and `smoothing_ops` appended with `"edited"`.
- Other artifacts stream via `FileResponse` so 10 MB+ tracks.json never loads into memory.
- The server absorbs the short publish dir-gap (`publish.py:141-165`) with 100 ms × 3 retry, so concurrent `mimicanno annotate` runs don't surface 500s.
- CORS is **opt-in**: empty `--cors-origin` → no middleware, no wildcard.
- Frontend toggle: visit the viewer with `?api=1` to route fetches through `/api/runs/` and enable the phase dropdown. Without the toggle the viewer reads the static `runs/` tree as before.

Internal layout, design contracts, and test stratification:
[`mimicanno/server/README.md`](mimicanno/server/README.md).

## Development

```bash
env -u PYTHONPATH uv run pytest -q                    # full suite (~40 s)
env -u PYTHONPATH uv run mypy --strict mimicanno/     # type check
env -u PYTHONPATH uv run ruff check mimicanno/        # lint
```

`PYTHONPATH=` strips a ROS2 humble path leak that some hosts inject; harmless if you don't have ROS2.

Architecture and design rationale: `docs/superpowers/specs/`. Implementation plans (TDD task lists): `docs/superpowers/plans/`. The parent design document is `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md`.

## License

MIT (see [`LICENSE`](LICENSE)).
