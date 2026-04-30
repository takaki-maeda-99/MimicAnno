# MimicAnno

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

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv).

```bash
git clone git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno
uv sync                     # core
uv sync --extra dev         # + pytest / mypy / ruff (recommended for development)
uv sync --extra vlm         # + transformers   (Phase 2 — Gemma)
uv sync --extra sam3        # + transformers + torch + torchvision (Phase 3 — SAM3)
```

GPU users with CUDA driver < 13.0 (e.g. Ubuntu 24.04 with driver 12.8) need a matching torch wheel:

```bash
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install transformers Pillow
```

Verify CUDA:

```bash
uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
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
gripper_scale_max:     100.0
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

## Viewer

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:5173/?run=<canonical_name>
```

Read-only timeline / waveform viewer for run directories. Edit affordances are deferred to Phase 5B (not started).

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
