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
- **React/Vite review UI** — timeline + waveforms + boundary markers, with phase / boundary / reviewed / label edits via an HTTP backend.
- **Pluggable robot adapters** — built-in for SO100 / Koch / Aloha; YAML-configurable for SO101 and arbitrary LeRobot v3 layouts.

## Install

Requires Linux + `uv`, `conda`, `python3.11+`, `node` (>=22, Vite 8 dropped Node 20 support), `pnpm`, `ffmpeg`, `git`, `curl`, `lsof`.

<details>
<summary>Don't have these? (one-liners — Ubuntu/Debian)</summary>

```bash
# uv (Python toolchain)
curl -Ls https://astral.sh/uv/install.sh | sh

# Node 22 via nvm + pnpm via corepack
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
. "$HOME/.nvm/nvm.sh"
nvm install 22
corepack enable && corepack prepare pnpm@latest --activate

# Miniforge (conda)
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh
bash Miniforge3-$(uname)-$(uname -m).sh

# ffmpeg + lsof (apt — adjust for your distro)
sudo apt-get install -y ffmpeg lsof
```
</details>

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno

# One-shot bootstrap (submodules, core, frontend, assets (unidac opt-in via --unidac)).
# Authenticate to Hugging Face first. Required for gated repos (SAM3,
# Gemma 4) and **strongly recommended for everything else** — anonymous
# downloads share a per-IP rate limit that the full weights+datasets
# fetch will trip. Either export HF_TOKEN=hf_xxx or run `hf auth login`.
bash scripts/setup_envs.sh

# Selective install (skip steps you don't need):
bash scripts/setup_envs.sh --core --frontend     # UI-only path
bash scripts/setup_envs.sh --all --skip-assets  # no model DLs

# Re-runs are idempotent (each step skips when its sentinel is satisfied).
```

Two manual steps the bootstrap can't do automatically — the Demo flow
below uses both:

**unsloth_env (for GEM4 batch wrappers)** — Unsloth's CUDA pinning is too
fragile to script. Create the env once:

```bash
conda create -n unsloth_env python=3.11 -y
conda activate unsloth_env
uv pip install unsloth
uv pip install -e '.[sam3]'           # [sam3] extra so batch_annotate.py can import the vendored sam3 submodule
uv pip install 'setuptools<81'        # sam3 uses pkg_resources, removed in setuptools 81+
```

If `uv pip` rejects unsloth's CUDA constraints, fall back to plain
`pip install unsloth` and `pip install -e .` (pip's resolver is looser).

**DINOv3 backbone (for Hand pipeline Phase A)** — UniDAC needs
`UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth`
(~1.2 GB), gated by Meta. Apply at
<https://ai.meta.com/resources/models-and-libraries/dinov3-downloads/>;
the email returns a signed URL — `wget` it (browsers won't follow the
redirect) into `UniDAC/checkpoints/`. Or `scp` it from another machine.

> **`.venv` is owned by `setup_envs.sh`.** Other helpers (`start_ui.sh`,
> `mimicanno` CLI) read from the existing `.venv` without modifying
> it. If `start_ui.sh` reports a `.venv` health-check failure, re-run
> `bash scripts/setup_envs.sh --core` to restore the full extras set
> (`dev`, `vlm`, `sam3`, `server`).

## Getting data

A fresh clone has no data. The `assets` step of `setup_envs.sh`
fetches these public datasets in addition to model weights:

| HF dataset | Local path | Contents |
|---|---|---|
| `Gayagaya/SO101_dataset` | `data/SO101/` | LeRobot v3 SO101 episodes (33 ep, 4960 frames) |
| `Gayagaya/fisheye_videos_processed` | `data/video/` | Face-blurred GoPro Max Lens Mod fisheye videos (currently only the demo clip; full set follows) |
| `takaki99/GEM4_open_the_jar` | `data/GEM4_open_the_jar/` | LeRobot v3, ~208 ep |
| `takaki99/GEM4_pick_up_bottle` | `data/GEM4_pick_up_bottle/` | LeRobot v3, ~304 ep |
| `takaki99/GEM4_replace_the_cookie` | `data/GEM4_replace_the_cookie/` | LeRobot v3, ~216 ep |

Or pull them manually:

```bash
hf download Gayagaya/SO101_dataset                --local-dir data/SO101                  --repo-type dataset
hf download Gayagaya/fisheye_videos_processed     --local-dir data/video                  --repo-type dataset
hf download takaki99/GEM4_open_the_jar            --local-dir data/GEM4_open_the_jar      --repo-type dataset
hf download takaki99/GEM4_pick_up_bottle          --local-dir data/GEM4_pick_up_bottle    --repo-type dataset
hf download takaki99/GEM4_replace_the_cookie      --local-dir data/GEM4_replace_the_cookie --repo-type dataset
```

## Demo

End-to-end smoke test after a fresh `bash scripts/setup_envs.sh`. Each
command is a no-op on re-run, so it doubles as the install-verification
flow.

```bash
# 1. Hand pipeline on the bundled demo fisheye video (Phase A → C, ~5 min / 1 GPU)
bash scripts/run_all_pipeline.sh demo_hand_video_2.7k

# 2. Annotate one SO101 episode (Phase 1–4, ~1 min on GPU)
uv run mimicanno annotate \
  --video        data/SO101/videos/chunk-000/observation.images.front/episode_000032.mp4 \
  --parquet      data/SO101/data/chunk-000/episode_000032.parquet \
  --task         "Put the tape into the bottle" \
  --robot        generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it" \
  --sam3-checkpoint sam3/checkpoints/sam3.pt \
  --runs-root    ./runs/so101

# 3. Batch-annotate one GEM4 episode with the Gemma 4 QLoRA adapter
#    (requires unsloth_env; ~2 min for the single-ep slice below)
GPU=0 START=0 END=0 bash scripts/run_4B_gem4.sh open_the_jar

# 4. Launch the review UI to inspect all outputs
bash scripts/start_ui.sh
# Open http://localhost:5173/
```

If all four succeed, the install is healthy. Detailed flags and other
datasets are covered in the next section.

## Quickstart

### 1. Annotate one episode

See the SO101 example in [Demo §2](#demo) — same command, against
`data/SO101/episode_000032`.

Produces `runs/<canonical_name>/{manifest,annotation,boundaries,signals,tracks}.json`. Re-running with the same config and inputs is a no-op.

If you re-run with a different config (different smoother/boundary YAML,
adapter, etc.), a **new** `episode_NNNNNN__<short-hash>/` directory is
created alongside the existing one — old runs are never overwritten.
The viewer then shows a "N runs exist for this episode" chooser banner
and the URL's `&hash=...` pins which version is currently being viewed.
Drop the stale directories under `runs/<set>/` to clear it.

Phases are cumulative: `--target-phase 1` (boundaries only, no VLM/SAM3 needed), `--target-phase 2` (+ VLM), `--target-phase 3` (+ SAM3, requires checkpoint), `--target-phase 4` (+ smoothing).

CPU-only or driver-mismatched? Add `--vlm-device cpu --vlm-timeout-sec 600` (expect ~1 hour on CPU vs ~1 minute on a recent GPU for an 8-segment episode).

### 2. Export to a SARM-trainable dataset

```bash
uv run mimicanno export \
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

### 3. Batch-annotate a GEM4 dataset

"GEM4" here is the dataset family — `open_the_jar`, `pick_up_bottle`,
`replace_the_cookie` — collected for Gemma-4-VLA training. Both
wrappers below load the VLM (Gemma 4 family) **once per process** and
reuse it across episodes, avoiding the ~2 min/ep model-load tax the
single-episode CLI would otherwise pay.

The 4B and 26B Unsloth QLoRA adapters are pulled by
`setup_envs.sh --assets` from
<https://huggingface.co/Gayagaya/gem4_4B_adapter> and
<https://huggingface.co/Gayagaya/gem4_26B_adapter>; manual fetch:

```bash
hf download Gayagaya/gem4_4B_adapter  --local-dir models/gem4_4B_adapter
hf download Gayagaya/gem4_26B_adapter --local-dir models/gem4_26B_adapter
```

**26B QLoRA adapter** (requires the `unsloth_env` conda env):

```bash
# All episodes of one task, one GPU
GPU=0 bash scripts/run_26B_gem4.sh open_the_jar

# Split episode range across two GPUs in parallel
GPU=0 START=0   END=151 bash scripts/run_26B_gem4.sh pick_up_bottle &
GPU=1 START=152 END=303 bash scripts/run_26B_gem4.sh pick_up_bottle
```

Outputs land at `runs/gem4_<task>_26B/`. **Sample outputs** from running
the 26B adapter on SO101 (20 episodes) are published at
<https://huggingface.co/datasets/Gayagaya/MimicAnno-so101-26B-runs>.
Fetch them into `runs/so101_26B/` with:

```bash
hf download Gayagaya/MimicAnno-so101-26B-runs \
  --repo-type dataset \
  --local-dir runs/so101_26B
```

**4B QLoRA adapter** (same `unsloth_env`, faster, lighter footprint):

```bash
GPU=0 bash scripts/run_4B_gem4.sh open_the_jar
GPU=0 START=0 END=103 bash scripts/run_4B_gem4.sh replace_the_cookie &
ADAPTER=/other/path GPU=0 bash scripts/run_4B_gem4.sh open_the_jar
```

Outputs land at `runs/gem4_<task>_4B/`. Both wrappers are thin shells
over `scripts/batch_annotate.py`; for SO101 or anything else not
wrapped, run that directly:

```bash
python scripts/batch_annotate.py --dataset so101 --gpu 0
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

Batch runners for specific tasks/robots live under [`scripts/`](scripts/README.md).

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

## Hand pipeline

Optional sub-pipeline that extracts per-frame 3D hand pose from GoPro Hero 11 Max Lens Mod fisheye footage (2704×1520, 29.97 fps, OPENCV_FISHEYE).

It fuses **MediaPipe Hand Landmarker** (2D keypoints + palm-axis-derived wrist rotation, Apache 2.0) with **UniDAC** monocular depth (MIT) to produce metric wrist position and per-finger distances in the camera frame.

```bash
# Phase A — depth precomputation
conda activate unidac
python scripts/precompute_depth.py --input data/video/<NAME>.MP4

# Phase B — hand pose estimation
python scripts/run_hand_estimation.py --video data/video/<NAME>.MP4

# All phases (A + B + depth-viz C), every fisheye video in data/video/
bash scripts/run_all_pipeline.sh

# Specific video(s) only — accepts both .MP4 and .mp4
bash scripts/run_all_pipeline.sh demo_hand_video_2.7k

# Single GPU (default 0 0) vs 2 GPUs in parallel
bash scripts/run_all_pipeline.sh --gpus 0 1

# Non-default I/O roots (CLI flags or VIDEO_DIR / DEPTH_DIR / HANDS_DIR env)
bash scripts/run_all_pipeline.sh --video-dir data/demo_hand_video

# Skip phases independently
bash scripts/run_all_pipeline.sh --skip-phase-a --skip-phase-b   # depth-viz only
```

Outputs land under `outputs/depth/<NAME>/` and `outputs/hands/<NAME>/`. Schema, field reference, and batch flags: [`docs/hand-pipeline.md`](docs/hand-pipeline.md).

### Third-party data collection (MediaPipe)

This pipeline uses **MediaPipe Solutions** for hand detection. MediaPipe processes video frames entirely on-device — your media is never sent to Google. However, MediaPipe sends **usage and performance metrics** to Google (SDK usage, inference counts, hardware performance, application identifiers, host system version). See Google's [MediaPipe APIs Terms of Service](https://ai.google.dev/edge/mediapipe/legal/tos) for details.

**If you redistribute this software**, you are responsible for informing end users and obtaining consent where required by applicable law (e.g. GDPR, CCPA).

### Offline / air-gapped deployment

For environments without internet access, pre-fetch the MediaPipe model on a machine with connectivity. The `assets` step of `setup_envs.sh` handles it:

```bash
bash scripts/setup_envs.sh --assets
# or, to control the destination:
MIMICANNO_HAND_LANDMARKER_PATH=/path/to/deployment/models/hand_landmarker.task \
    bash scripts/setup_envs.sh --assets
```

Then set `MIMICANNO_HAND_LANDMARKER_PATH=...` in the production environment. The runner's `_resolve_model_path()` resolves the asset in this order:

1. `MIMICANNO_HAND_LANDMARKER_PATH` — explicit override; the file must exist or the runner fails fast.
2. `~/.cache/mimicanno/hand_landmarker.task` — if present and size-verified, used without network access.
3. Pinned URL download into the cache from step 2.

The URL is pinned to the `/1/` revision for byte-identical reproducibility across machines, and step 1 short-circuits both step 2 and step 3 — air-gapped deployments only ever exercise step 1.

## Server

HTTP backend that serves the same JSON shapes as the static `runs/` tree and accepts segment edits with optimistic locking. Installed lazily via the `[server]` optional dependency group.

```bash
uv sync --extra server
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
    --runs-root runs/ \
    --host 127.0.0.1 --port 8000 \
    --cors-origin http://localhost:5173
```

`MIMICANNO_REVIEWER` is captured at startup and stamped as `reviewer_id` on every edit; unset/empty → `reviewer_id=null`.

Endpoints (read):
- `GET /healthz` — liveness probe
- `GET /api/runs/index.json`, `GET /api/runs/<name>/<artifact>` — same shape as the static tree (`manifest`, `annotation`, `boundaries`, `signals`, `tracks`)
- `GET /api/labelset` — `{labels, labels_yaml_sha256}`

Endpoints (edit, `If-Match: "<run_hash>"` required):
- `PATCH /api/runs/<name>/segments/<id>` — change `phase`
- `PATCH /api/runs/<name>/segments/<id>/labels` — set per-segment label list
- `PATCH /api/runs/<name>/segments/<id>/reviewed` — mark reviewed
- `PATCH /api/runs/<name>/boundaries/<id>` — move a boundary

Each successful PATCH atomically rewrites annotation → manifest → index under a `runs/index.json.lock` file lock and returns the new `ETag`. Internal layout, contracts, and test stratification: [`mimicanno/server/README.md`](mimicanno/server/README.md).

Frontend uses `/api/runs/` by default; append `?api=0` to read static `runs/` files instead (read-only, no edit affordances).

## Development

```bash
env -u PYTHONPATH uv run pytest -q                    # full suite (~40 s)
env -u PYTHONPATH uv run mypy --strict mimicanno/     # type check
env -u PYTHONPATH uv run ruff check mimicanno/        # lint
```

`PYTHONPATH=` strips a ROS2 humble path leak that some hosts inject; harmless if you don't have ROS2.

Architecture and design rationale: `docs/superpowers/specs/`. Implementation plans (TDD task lists): `docs/superpowers/plans/`.

## License

MIT (see [`LICENSE`](LICENSE)).
