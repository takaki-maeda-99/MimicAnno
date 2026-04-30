# MimicAnno

Offline subtask annotation pipeline for robot imitation-learning episodes. Takes recorded LeRobot v3 episodes (video + robot state + action), automatically segments them into robot-executable subtask phases, and produces SARM-trainable LeRobot datasets augmented with subtask labels and canonical action features.

Designed to be used standalone (`mimicanno annotate`, `mimicanno export`) or embedded in [MimicRec](https://github.com/takaki-maeda-99/MimicRec) as the annotator backend.

## Status

| Phase | What | Status |
|---|---|---|
| **1** | Signal-based boundary detection (gripper / EEF velocity / action-norm transitions) + read-only React/Vite viewer | Shipped on `main` |
| **2** | VLM (Gemma 4) per-segment phase labeling with allowed-label enforcement | Shipped on `main` |
| **3** | SAM3 object tracking + integrated boundary score + object-aware relabeling | Shipped on `main` |
| **4** | Temporal smoothing (same-label merge / min-duration absorb / Viterbi) | Shipped on `main` |
| **5C** | **`mimicanno export`** — SARM-trainable LeRobot v3 export | Branch `phase5-export-impl`, ready for review |
| 5A/B/D/E | Persistence backend / Edit UI / Evaluation harness / MimicRec integration | Not started |

859 tests pass (`uv run pytest`); mypy `--strict` clean for the `mimicanno/exports/` Phase 5 surface.

## What this gives you

Given a LeRobot v3 dataset and a single-line command, you get back a new LeRobot v3 dataset where every frame has a `subtask_index` column pointing into a `meta/subtasks.parquet` registry, every episode metadata row carries `<prefix>_subtask_names` / `_start_frames` / `_end_frames` lists, and every per-frame parquet has additional `mimicanno.ee_delta_6d` / `gripper_normalized` / `gripper_delta` columns suitable for [SARM](https://github.com/takaki-maeda-99/MimicRec/tree/main/lerobot/src/lerobot/policies/sarm) training.

A lossless `meta/mimicanno_segments.parquet` sidecar preserves the full mimicanno schema (verb / object / target / failure_flags / confidences / boundaries / provenance) for evaluation and review tooling.

Verified end-to-end on real SO101 data (`~/MimicRec/datasets/SO101/episode_000000`, "Put the tape into the bottle", 151 frames):

```
seg0 [  0.. 14] approach_object  verb=move   object=tape   target=bottle   conf=0.7
seg1 [ 15.. 30] approach_object  ...
...
seg7 [121..150] grasp_object     verb=grasp  object=bottle target=bottle   conf=0.95
```

## Install

Requires Python 3.11+, [uv](https://github.com/astral-sh/uv), and (for VLM/SAM3) a CUDA-capable GPU with driver ≥ 12.8.

```bash
git clone git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno
uv sync                         # core deps: pyarrow, scipy, typer, ...
uv sync --extra dev             # + pytest, mypy, ruff
uv sync --extra vlm             # + transformers (for Phase 2 Gemma)
uv sync --extra sam3            # + transformers, torch, torchvision (for Phase 3 SAM3)
```

If your CUDA driver is < 13.0, install a matching torch wheel after the sync:

```bash
# driver 12.8 → torch cu128
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install transformers Pillow   # uv pip install can drop these; reinstall
```

## Quickstart: end-to-end annotation + export

### 1. Phase 4 annotation on a single episode

```bash
mimicanno annotate \
  --video    /path/to/dataset/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --parquet  /path/to/dataset/data/chunk-000/episode_000000.parquet \
  --task     "Put the tape into the bottle" \
  --robot    generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it@<sha>" \
  --sam3-checkpoint /path/to/sam3.ckpt \
  --runs-root ./runs
```

Produces a versioned run directory at `runs/<canonical_name>/` with `manifest.json`, `annotation.json`, `boundaries.json`, `signals.json`, `tracks.json`. Re-running with the same config and inputs is a no-op (idempotent).

CPU-only? Add `--vlm-device cpu --vlm-timeout-sec 600` and use `--target-phase 2` (Phase 3 needs SAM3 weights, Phase 4 needs Phase 3). Expect ~1 min per episode on GPU, ~1 hour on CPU.

### 2. Phase 5 export to a SARM-trainable dataset

```bash
mimicanno export \
  --dataset    /path/to/dataset \
  --runs-root  ./runs \
  --target-phase 4 \
  --profile    so101_sarm \
  --out        /path/to/dataset_annotated \
  --episode    0
```

Default mode (`--symlink-data`) creates `dataset_annotated/` with `videos/` symlinked from the source, `data/` rebuilt with subtask annotations, fresh `meta/`, and a `.mimicanno-export.json` provenance manifest. `--copy-data` copies videos instead. `--in-place` (requires `--yes-i-mean-it`) mutates the source dataset, creating a `.mimicanno-backup-<ISO>/` directory for rollback.

Repeated runs with identical args short-circuit (idempotent reuse).

## Supported robots

| Adapter | Layout |
|---|---|
| `aloha` | LeRobot v3 with aggregated `observation.state` (14-D), Cartesian EEF available |
| `koch` | Joint-only, 6-D `observation.state` |
| `so100` | Joint-only, 6-D `observation.state` |
| `generic` | Configurable via YAML — see `tests/exports/fixtures/so101_robot_config.yaml` for the SO101 example (split state columns + rotvec + scaled gripper) |

The `generic` adapter (schema 0.2.0) supports both LeRobot v2-style aggregated state and v3-style split columns (`observation.state.{ee_pos, ee_rotvec, gripper_pos, ...}`), with optional gripper scaling and rotvec passthrough.

To support a new robot, write a YAML config naming the columns and the gripper range. See `mimicanno/adapters/generic.py` for the full schema.

## Export profiles

Three profiles ship under `mimicanno/configs/exports/`:

- `so101_sarm.yaml` — SO101-specific (uses `generic` adapter with the column mapping inlined). Ships ee_delta_6d + gripper extras as per-frame columns and a `mimicanno_*`-prefixed list-column convention.
- `aloha_sarm.yaml` — Aloha. Same structure, dedicated adapter.
- `generic.yaml` — minimal template; user fills in the adapter config. Use this for new datasets.

Profiles are validated against `mimicanno/jsonschemas/export_profile.schema.json`. The export records a SHA256 hash of the resolved profile in `.mimicanno-export.json` so reuse / verification is deterministic.

## Repository layout

```
mimicanno/
  adapters/        # per-robot column accessors (aloha, koch, so100, generic)
  exports/         # Phase 5 export pipeline (this sub-project)
  jsonschemas/     # JSON schemas for manifest / annotation / boundaries / signals / export
  configs/         # default label sets + export profiles
  pipeline.py      # Phase 1-4 orchestrators
  boundaries.py    # signal-based boundary detection
  vlm_labeler.py   # Gemma 4 VLM phase labeling
  vlm_prompt.py    # prompt assembly (legacy build_prompt + chat-template build_messages)
  smoother.py      # Phase 4 temporal smoothing
  schema.py        # SubtaskSegment, AnnotationResult, Manifest, ...
  cli.py           # `mimicanno annotate` + `mimicanno export`

frontend/          # React/Vite read-only viewer (Phase 1)
tests/exports/     # Phase 5 tests including mini_so101 + mini_runs fixtures

docs/superpowers/
  specs/           # design specs (one per phase / sub-project)
  plans/           # implementation plans (TDD-style task lists)
```

The most recent design + plan documents:

- `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md` — parent spec for all phases
- `docs/superpowers/specs/2026-04-30-mimicanno-phase5-export-design.md` — Phase 5 export sub-project
- `docs/superpowers/plans/2026-04-30-mimicanno-phase5-export.md` — TDD plan that built it

## Development

```bash
cd ~/MimicAnno
env -u PYTHONPATH uv run pytest -q                    # full suite, ~40 s
env -u PYTHONPATH uv run mypy --strict mimicanno/     # type check
env -u PYTHONPATH uv run ruff check mimicanno/        # lint
```

`PYTHONPATH=` strips a ROS2 humble pollution that some setups leak.

CI gate (per phase): all tests pass, mypy strict clean for the touched module(s), ruff clean for new code. Spec / plan documents are reviewed via the superpowers `spec-document-reviewer` and `plan-document-reviewer` subagents before code starts; final pre-merge code review uses the `superpowers:code-reviewer` agent.

## Contributing

This codebase uses the [superpowers](https://github.com/anthropics/superpowers) skills workflow:

1. **Brainstorming**: scope and tradeoffs go through `superpowers:brainstorming` (or its plugin equivalent).
2. **Spec**: written design + reviewer approval (`spec-document-reviewer`).
3. **Plan**: TDD task list (`writing-plans`), reviewed by `plan-document-reviewer`.
4. **Implementation**: per-task TDD (failing test → minimal implementation → pass → commit). Subagent-driven for large phases.
5. **Pre-merge**: `superpowers:code-reviewer` final review, address blockers/should-fixes.

See `CLAUDE.md` for project-specific guidance (notably the autonomous-mode directive used during Phase 5 development).

## License

MIT (see `LICENSE`).
