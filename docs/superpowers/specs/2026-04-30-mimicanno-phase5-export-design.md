# MimicAnno Phase 5 — Parquet export design

Status: **draft**, awaiting review (spec-document-reviewer).
Author: brainstorming session 2026-04-30.
Supersedes: nothing — new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§4 run-dir contract, §6 schema, §7 LeRobot parquet read contract, §10 phase decomposition Phase 5, §14 MimicRec integration, §15.4 #17 exit criterion, §16 deferred items).
Sibling: [`2026-04-29-mimicanno-phase4-smoothing-design.md`](./2026-04-29-mimicanno-phase4-smoothing-design.md) (Phase 4 — produces the `annotation.json` Phase 5 export consumes; additive only).

This document covers **only the parquet export sub-project of Phase 5**. The other Phase 5 sub-projects (persistence backend, edit UI, evaluation harness, MimicRec integration) are out of scope here and will get their own specs.

## Reviewer context

(For reviewers unfamiliar with the parent spec — skim if you've already read it.)

### What is MimicAnno?

MimicAnno is a robot-episode subtask annotator: a CLI that ingests `(video, parquet, task_text)` and emits a per-segment subtask labeling under a versioned run directory `runs/<canonical_name>/{manifest, annotation, boundaries, signals[, tracks]}.json`. Phase 1 produces `phase="unlabeled"` skeleton segments from gripper / EEF / action signals; Phase 2 fills each segment with one of a fixed allowed-label set via Gemma; Phase 3 adds SAM3 object tracking + object-aware boundaries + object-aware relabeling; Phase 4 applies temporal smoothing (same-label merge, min-duration absorb, Viterbi).

### Where Phase 5 export fits

```
Phase 1: signals-based boundary detection + read-only viewer        ← SHIPPED
Phase 2: provisional VLM labeling                                   ← SHIPPED
Phase 3: SAM3 + integrated boundary score + object-aware relabel    ← SHIPPED
Phase 4: temporal smoothing                                         ← SHIPPED
Phase 5: human-edit UI + parquet export + evaluation                ← THIS SPEC covers parquet export only
```

The Phase 5 work bucket has 5 independent sub-projects:

| Sub-project | Purpose | Status |
|---|---|---|
| **A. Persistence backend** | FastAPI for the edit UI + `runs/index.json` HTTP contract (parent §4.7) | not started |
| **B. Edit UI** | Boundary drag, relabel, `reviewed`/`reviewer_id` write, low-confidence filter | not started |
| **C. Parquet export** | `mimicanno export` CLI — produces a SARM-trainable LeRobot v3 dataset | **THIS SPEC** |
| **D. Evaluation harness** | `human_edit_time` and label-agreement metrics from B's logs | not started |
| **E. MimicRec integration** | Replay page calls A or reads static `runs/`; `save_annotations` swap-out | not started |

The sub-projects are independent enough to be specced and shipped separately. The parquet export (C) is the smallest and is fully decoupled from A/B/D — it only needs an `annotation.json` on disk and a source LeRobot dataset. It is the highest-value first deliverable because it unblocks SARM training on mimicanno-annotated data without requiring any UI work.

### What this sub-project does

It introduces a `mimicanno export` CLI that reads:
1. A source LeRobot v3 dataset root (the original `~/MimicRec/datasets/<name>/`).
2. A mimicanno runs root (`runs/<canonical_name>/annotation.json` per episode).

…and writes a **new** LeRobot v3 dataset root that is a SARM-trainable copy of the source augmented with subtask annotations. The augmentation has three layers:

- **LeRobot v3 standard:** per-frame `subtask_index` in `data/<chunk>/episode_NNNNNN.parquet`, global `meta/subtasks.parquet` registry, per-episode `subtask_names`/`subtask_start_frames`/`subtask_end_frames` lists in `meta/episodes/<chunk>/file-NNN.parquet` (with optional `<annotation_type>_` prefix).
- **Canonical action representation:** body-frame `ee_delta_6d` (T, 6) + normalized `gripper` + `gripper_delta` as extra per-frame columns, configurable via the export profile.
- **Sidecar parquet `meta/mimicanno_segments.parquet`:** lossless mirror of `annotation.json` segments (phase, verb, object, target, failure_flags, confidences, label_source, reviewed, smoothing_ops, …), one row per segment.

The output is a self-contained LeRobot v3 dataset that the vendored SARM policy in `~/MimicRec/lerobot/src/lerobot/policies/sarm/processor_sarm.py:_load_episode_annotations` can consume directly via the `annotation_type="mimicanno"` branch of its column-name fallback (`<annotation_type>_subtask_*` → `subtask_*`).

### What you should be evaluating

If you're a reviewer, the question is: **could a competent engineering team take this document and produce an implementation that (a) satisfies parent-spec exit criterion §15.4 #17 and the 6 export-specific exit criteria in §13, (b) does not violate the parent-spec invariants on hashing / atomicity / schema versioning / error idiom, (c) preserves Phase 1/2/3/4 behavior unchanged at the byte level, (d) is consumable by SARM training without further glue code, and (e) leaves Phase 5's other sub-projects (A/B/D/E) unobstructed?**

## 0. Scope and intent

In scope:

- New `mimicanno/exports/` sub-package (parent spec §12 layout). Public API surface: `CanonicalEpisode` dataclass, `ExportProfile` dataclass + YAML loader, `SinkWriter` protocol, `LeRobotV3SinkWriter` concrete class, `build_canonical_episode()` builder, `bulk_export()` orchestrator, `mimicanno.export()` programmatic entry point.
- New `mimicanno export` CLI subcommand. Phase 1/2/3/4 invocations unchanged.
- New `mimicanno/configs/exports/` directory with three out-of-the-box profiles (`so101_sarm.yaml`, `aloha_sarm.yaml`, `generic.yaml`).
- New `meta/mimicanno_segments.parquet` sidecar layout (lossless segment mirror).
- Three output destination modes: `--symlink-data` (default), `--copy-data`, `--in-place` (requires explicit confirmation flag).
- Run selection: bulk-by-default with `--target-phase`, optional `--config-hash` / `--run` / `--episode` filters; `EXPORT_RUN_AMBIGUOUS` on under-specification.
- Round-trip property (RT-1 label round-trip + RT-2 action round-trip) as the literal definition of export correctness.
- Test strategy across 4 layers (unit / integration on a checked-in mini fixture / round-trip / error-path).

Non-goals:

- **No edit UI, no backend, no evaluation harness, no MimicRec call-site changes.** Those are sub-projects A/B/D/E and get their own specs.
- **No new annotation logic.** Export is a pure read-side over `annotation.json`; it does not call the VLM, SAM3, or smoother.
- **No re-running of Phase 1–4 from export.** Export consumes a finished run dir; it never triggers annotation.
- **No new run_hash or config_hash.** Export does not affect mimicanno's existing hashing scheme. Profile hash is recorded in the export manifest only, separate from `run_hash` and `config_hash`.
- **No backwards-compat with MimicRec's stub `save_annotations`.** That stub is deprecated by this spec; replacement happens in sub-project E.
- **No new sink format beyond LeRobot v3.** RLDS / ARIO / HDF5 are deferred — the `SinkWriter` protocol leaves them open but no implementation ships in this sub-project.
- **No support for rotation representations other than rotvec.** `quat`/`euler`/`rotmat` are deferred.
- **No support for `delta_basis` other than `body_frame_t`, `world`, and `base`.** `body_frame_{t+1}` and learned-frame variants are out of scope.
- **No automatic dataset version bumping.** `meta/info.json:codebase_version` is preserved as-is from source; we add to `features` and metadata files but do not change the LeRobot dataset version.
- **No `.mimicanno-backup-<timestamp>/` restore command in this spec.** `mimicanno export-undo` is a follow-up task; the backup directory is created and documented but the restore tool is left for sub-project E.

## 1. Architecture

### 1.1 Pipeline

```
mimicanno export --dataset <DS> --runs-root <RUNS> --target-phase <P>
                 --profile <NAME|PATH> --out <OUT> [mode flags]
  │
  ├─ load_profile(<NAME|PATH>)                           → ExportProfile
  ├─ enumerate_episodes(DS, profile.source.robot_adapter) → list[(episode_index, episode_id)]
  ├─ resolve_runs_for_episodes(RUNS, episodes, target_phase, config_hash?)
  │       (uses existing mimicanno/runindex.py lookups)
  │       → dict[episode_index → canonical_name]
  │       (raises EXPORT_RUN_NOT_FOUND / EXPORT_RUN_AMBIGUOUS)
  │
  ├─ for each (episode_index, canonical_name):
  │     ├─ load AnnotationResult, Manifest from runs/<canonical>/
  │     ├─ source_reader.read_episode(DS, episode_index)   (RobotAdapter.read_episode)
  │     ├─ build_canonical_episode(...)                    → CanonicalEpisode
  │     │       (validates frame counts, gates, raw_action presence)
  │     └─ accumulate (episodes are processed sequentially; bulk batches in-memory)
  │
  ├─ create_output_layout(OUT, mode={symlink|copy|in_place})
  │       (allocates OUT.tmp.<pid>/, sets up videos/ symlink|copy, prepares meta/)
  │
  ├─ LeRobotV3SinkWriter.write_all(out_tmp, list[CanonicalEpisode], profile):
  │     ├─ write data/<chunk>/episode_NNNNNN.parquet
  │     │       (source columns + subtask_index + extra per-frame columns)
  │     ├─ write meta/subtasks.parquet
  │     │       (rows = phases observed across all episodes, ordered by first appearance)
  │     ├─ write meta/episodes/<chunk>/file-NNN.parquet
  │     │       (source columns + 3 list columns, with annotation_prefix)
  │     ├─ write meta/mimicanno_segments.parquet  (sidecar, all episodes flat)
  │     ├─ write meta/info.json                   (source + features additions)
  │     └─ copy meta/tasks.parquet (and other meta/* files we don't touch) verbatim
  │
  ├─ write OUT.tmp.<pid>/.mimicanno-export.json
  │       (provenance: profile_hash, runs_used, mimicanno_version, generated_at,
  │        cli_args, output_mode, source_dataset_path)
  │
  └─ atomic publish:
        os.replace(OUT.tmp.<pid>, OUT)            # POSIX atomic
        (--in-place uses per-file os.replace inside DS instead, with backup dir)
```

### 1.2 Package layout (additive)

```
mimicanno/
  exports/                       ← NEW
    __init__.py
    canonical.py                 # CanonicalEpisode, build_canonical_episode
    profile.py                   # ExportProfile + YAML loader + JSON-schema validation
    sink_base.py                 # SinkWriter protocol
    sink_lerobot_v3.py           # LeRobotV3SinkWriter
    output_layout.py             # symlink/copy/in_place destination logic
    bulk.py                      # bulk_export orchestrator
    errors.py                    # EXPORT_* error codes
  configs/
    exports/                     ← NEW
      so101_sarm.yaml
      aloha_sarm.yaml
      generic.yaml
  jsonschemas/
    export_profile.schema.json   ← NEW
    mimicanno_segments.schema.json  ← NEW (parquet column contract)
    export_manifest.schema.json  ← NEW (.mimicanno-export.json)
  cli.py                         ← MODIFIED: add `export` subcommand
  __init__.py                    ← MODIFIED: expose `mimicanno.export(...)` programmatic API

tests/
  exports/                       ← NEW
    __init__.py
    test_canonical.py
    test_profile.py
    test_sink_lerobot_v3.py
    test_output_layout.py
    test_bulk.py
    test_cli_export.py
    test_roundtrip_label.py
    test_roundtrip_action.py
    test_errors.py
    fixtures/
      mini_so101/                # 3 ep × ~20 frames, real LeRobot v3 layout (~50 KB)
      build_mini_so101.py        # reproducible generator (committed)
```

### 1.3 Reuse of existing components

To minimize new code:

- **Source reader = existing `mimicanno/adapters/{so101,aloha,koch,generic}.py`.** Already returns EE pose + gripper in a normalized form. `build_canonical_episode` adds the delta math and gripper_delta on top.
- **Run index lookup = existing `mimicanno/runindex.py`.** `resolve_runs_for_episodes` calls existing `find_runs_for_episode(...)` with target_phase / config_hash filters.
- **Manifest + annotation loaders = existing `mimicanno/io.py`.** No duplication.
- **Atomic-write idiom = existing `mimicanno/writers.py` + `mimicanno/publish.py`.** `.tmp.<pid>` + `os.replace` pattern, also used by Phase 1–4.
- **Error structure = existing `mimicanno/errors.py` `ErrorCode` enum + structured-stderr formatter.** Phase 5 export adds 13 new codes prefixed `EXPORT_*`.
- **JSON schema validation = existing `jsonschema`-based loader pattern from Phase 1–4 manifests.**

The result: new code lives almost entirely under `mimicanno/exports/`, with two single-line additions (`cli.py`, `__init__.py`) outside.

## 2. CanonicalEpisode (intermediate representation)

`CanonicalEpisode` is the central type. It is the **boundary between source-format-aware code and sink-format-aware code**, and it is the **observation point for round-trip equivalence**. The export pipeline is conceptually `Source → CanonicalEpisode → Sink`, and the round-trip property (§10) reads as: re-reading the sink output and re-deriving a `CanonicalEpisode` should yield the same instance up to numerical tolerance and semantic equivalence.

### 2.1 Dataclass shape

```python
# mimicanno/exports/canonical.py
@dataclass(frozen=True)
class CanonicalEpisode:
    # Identity
    episode_index: int           # MimicRec/LeRobot integer ID (FK to data parquet)
    episode_id: str              # mimicanno's stable string ID (used in run_hash)
    fps: float
    num_frames: int              # T

    # Per-frame canonical (T-aligned, dtype=float32)
    ee_pose_world: np.ndarray    # (T, 6): [x, y, z, rx_world, ry_world, rz_world]
                                 #         position + axis-angle rotvec, world frame
    ee_delta_6d: np.ndarray      # (T, 6): [Δx_body, Δy_body, Δz_body,
                                 #          Δrx_body, Δry_body, Δrz_body]
                                 #         body-frame-at-t delta to t+1; ee_delta_6d[T-1] = zeros
    gripper_normalized: np.ndarray  # (T,): [0, 1]; 0 = closed, 1 = open
    gripper_delta: np.ndarray    # (T,): gripper_normalized[t+1] - gripper_normalized[t];
                                 #       gripper_delta[T-1] = 0

    # Per-frame raw (optional pass-through)
    raw_action: np.ndarray | None        # (T, A) or None if pass_through_raw_action=false
    raw_action_columns: list[str] | None # source-parquet column names (only if raw_action != None)

    # Per-segment (mimicanno's full schema, lossless)
    segments: tuple[SubtaskSegment, ...] # frozen tuple for dataclass(frozen=True)

    # Provenance (read from manifest)
    run_hash: str
    config_hash: str
    input_hash: str
    label_version: str
    pipeline_phase: int            # 1..4
    mimicanno_version: str
    generated_at: str              # ISO8601 from manifest
    pipeline_status: PipelineStatus  # parent §4.3 typed dataclass
```

### 2.2 ee_delta_6d math (fixed)

For each frame `t ∈ [0, T-1)`:

```
p_t = ee_pose_world[t, 0:3]        # world position
r_t = ee_pose_world[t, 3:6]        # world rotvec
R_t = exp_so3(r_t)                  # 3x3 rotation matrix (Rodrigues)

p_{t+1} = ee_pose_world[t+1, 0:3]
r_{t+1} = ee_pose_world[t+1, 3:6]
R_{t+1} = exp_so3(r_{t+1})

# delta_basis = body_frame_t (default; profile-overridable)
Δp_body[t]  = R_t.T @ (p_{t+1} - p_t)
ΔR_body[t]  = R_t.T @ R_{t+1}
Δr_body[t]  = log_so3(ΔR_body[t])  # 3-vector rotvec (axis * angle)

ee_delta_6d[t] = concatenate(Δp_body[t], Δr_body[t])  # (6,)
```

Last frame is fixed:

```
ee_delta_6d[T-1] = zeros(6)
```

This is the imitation-learning convention (action = body-frame relative motion at time `t` going to time `t+1`). The body-frame choice removes the dependency on world calibration.

`profile.canonical.delta_basis` can override:
- `body_frame_t` (default): formula above.
- `world`: `Δp_world = p_{t+1} - p_t`, `Δr_world = log_so3(R_t^-1 R_{t+1})` is **wrong** for `world`; for `world` the rotation delta is computed differently. To keep the spec deterministic: for `world`, use `Δp_world = p_{t+1} - p_t` and `Δr_world = log_so3(R_{t+1} @ R_t.T)` (left-invariant world delta).
- `base`: equivalent to `world` since the parent spec assumes the world frame is the robot base.

The ambiguity-free reference implementation lives in `mimicanno/exports/canonical.py`, with each branch covered by a unit test using synthetic poses with known closed-form deltas.

### 2.3 build_canonical_episode

```python
def build_canonical_episode(
    *,
    dataset_root: Path,
    episode_index: int,
    annotation: AnnotationResult,    # from runs/<canonical>/annotation.json
    manifest: Manifest,              # from runs/<canonical>/manifest.json
    profile: ExportProfile,
) -> CanonicalEpisode:
    """Source dataset + mimicanno run → CanonicalEpisode.

    Steps:
      1. Resolve RobotAdapter from profile.source.robot_adapter.
      2. adapter.read_episode(dataset_root, episode_index) → EpisodeRead
         (typed result containing ee_pose_world, gripper_normalized, raw_action,
          fps, num_frames, episode_id; existing Phase 1–4 contract).
      3. Validate annotation.episode_index == episode_index → raise EXPORT_EPISODE_MISMATCH otherwise.
      4. Validate annotation.episode_id == EpisodeRead.episode_id → raise EXPORT_EPISODE_MISMATCH otherwise.
      5. Validate annotation.segments[-1].end_frame == EpisodeRead.num_frames - 1 → raise EXPORT_FRAME_COUNT_MISMATCH otherwise.
      6. Compute ee_delta_6d via the math above (delta_basis from profile).
      7. Compute gripper_delta = diff with zero-padding at T-1.
      8. If profile.source.pass_through_raw_action:
            require EpisodeRead.raw_action != None → raise EXPORT_RAW_ACTION_MISSING otherwise.
            Carry raw_action and raw_action_columns through.
         Else:
            Set raw_action = None.
      9. Apply gates (profile.gates merged with CLI overrides):
         - require_reviewed: any segment with reviewed=False → raise EXPORT_NOT_REVIEWED.
         - forbid_degraded_pipeline: manifest.pipeline_status.degraded_from_phase != None → raise EXPORT_PHASE_DOWNGRADE.
         - forbid_unlabeled_segments: any segment with phase == "unlabeled" → raise EXPORT_UNLABELED_PRESENT.
     10. Construct CanonicalEpisode (frozen=True) and return.
    """
```

Errors raised here propagate up through `bulk_export` and surface at the CLI as structured `error_code` JSON on stderr (existing mimicanno convention).

## 3. Sidecar parquet (`meta/mimicanno_segments.parquet`)

This file is the **lossless mirror of all `annotation.json` segments** for the exported runs, flattened across episodes. It is the source of truth for the label-side round-trip property (RT-1, §10.1).

### 3.1 Row shape

One row per segment. Schema (Arrow logical types):

| Column | Type | Source |
|---|---|---|
| `episode_index` | `int64` | `CanonicalEpisode.episode_index` |
| `segment_index` | `int32` | `0..N-1` per episode (annotation.segments order) |
| `segment_id` | `string` | mimicanno-assigned stable ID (parent §6.1) |
| `phase` | `string` | allowed-labels member or `unlabeled` / `unknown` |
| `verb` | `string` (nullable) | parent §6.1 |
| `object` | `string` (nullable) | parent §6.1 |
| `target` | `string` (nullable) | parent §6.1 |
| `failure_flags` | `list<string>` | empty list = nominal |
| `start_frame` | `int64` | inclusive |
| `end_frame` | `int64` | inclusive |
| `start_time` | `float64` | seconds |
| `end_time` | `float64` | seconds |
| `label_source` | `string` | enum: `signals_only` / `vlm_robot_state_only` / `vlm_with_object_state` / `human_edit` |
| `object_state_unavailable` | `bool` | parent §6.1 |
| `object_track_ids` | `list<string>` | empty list allowed |
| `label_version` | `string` | e.g. `manipulation.v1` |
| `boundary_confidence` | `float32` | derived from start/end BoundaryRef.score |
| `vlm_confidence` | `float32` (nullable) | None for Phase 1 runs |
| `overall_confidence` | `float32` | parent §6.4 (reserved phases = 0.0) |
| `evidence` | `string` (nullable) | parent §6.1 |
| `reviewed` | `bool` | parent §6.1 |
| `reviewer_id` | `string` (nullable) | parent §6.1 |
| `smoothing_ops` | `list<string>` | Phase 4 additive (parent §6.1; Phase 1–3 runs = empty list) |
| `boundary_source_start` | `list<string>` | from `start_boundary.sources` (parent §6.1 BoundaryRef) |
| `boundary_source_end` | `list<string>` | from `end_boundary.sources` |
| `run_hash` | `string` | provenance |
| `config_hash` | `string` | provenance |
| `input_hash` | `string` | provenance |
| `pipeline_phase` | `int8` | 1..4 |
| `mimicanno_version` | `string` | e.g. `0.1.0` |
| `generated_at` | `string` | ISO8601, from manifest |

Provenance fields are **redundant per row** (all rows for the same episode share the same run_hash etc.). Justification: parquet columnar compression makes the storage cost negligible (dictionary-encoded), and this allows readers to skip joining against the export manifest for filtering.

### 3.2 Schema versioning

The sidecar file carries its own `schema_version` outside the parquet (in `meta/mimicanno_segments.schema.json` shipped with the package, and in `meta/.mimicanno-export.json:sidecar_schema_version`). Initial value `"1"`.

The JSON schema for column types lives at `mimicanno/jsonschemas/mimicanno_segments.schema.json`. Loading consumers should perform parent-spec §6.6 consumer-capability check: `if loaded.sidecar_schema_version not in supported_versions: raise`.

### 3.3 Read pattern

```python
import pandas as pd
sidecar = pd.read_parquet("OUT/meta/mimicanno_segments.parquet")
# Filter to one episode
ep_segments = sidecar[sidecar.episode_index == 0].sort_values("segment_index")
# Reconstruct list[SubtaskSegment]
from mimicanno.schema import SubtaskSegment
segments = [SubtaskSegment.from_row(row) for _, row in ep_segments.iterrows()]
```

`SubtaskSegment.from_row` is a classmethod added to `mimicanno/schema.py` that reverses `SubtaskSegment.to_dict()` (the existing serializer used for `annotation.json`). The `start_boundary` / `end_boundary` `BoundaryRef` per-edge structures are reconstructed by joining the sidecar's `boundary_source_*` lists with the segment confidences (the `BoundaryRef.score` is recoverable from `boundary_confidence`; per-source per-edge scores require reading `boundaries.json` from the run dir, which is **not** copied into the export — this is an accepted lossy field for the round-trip; see §10.1 for the precise round-trip equivalence relation).

## 4. LeRobot v3 sink writer

`LeRobotV3SinkWriter` (mimicanno/exports/sink_lerobot_v3.py) writes to a fresh output dataset root (or, in `--in-place` mode, mutates the source). It writes five categories of files:

### 4.1 `data/<chunk>/episode_NNNNNN.parquet`

For each episode:

```
columns_out = original_columns + ["subtask_index"] + extra_per_frame_columns
```

Where:
- `original_columns` = all columns from the source data parquet, preserved byte-for-byte.
- `subtask_index` (`int64`): for each frame `f`, the integer index into `meta/subtasks.parquet` of the segment whose `[start_frame, end_frame]` (inclusive) contains `f`.
- `extra_per_frame_columns`: from `profile.sink.params.extra_per_frame_columns`; each entry maps a `CanonicalEpisode` field (`ee_delta_6d`, `gripper_normalized`, `gripper_delta`) to a target column name with explicit dtype. Default profile uses the `mimicanno.` namespace prefix to avoid collision with source columns.

Frame-coverage assertion: every frame `f ∈ [0, num_frames)` must be covered by exactly one segment. mimicanno's bracketing (parent §5) guarantees this for runs that completed normally; if any segment list has a gap (synthesized, edited, or imported), the frame is assigned the `subtask_index` of the `unlabeled` reserved phase (which is added to `meta/subtasks.parquet` if not already present). **Never** default-pad to `subtask_index=0` (that would silently collide with the legitimate first subtask, repeating MimicRec's stub bug).

### 4.2 `meta/subtasks.parquet`

Mirrors the structure of the existing `meta/tasks.parquet`:

| Column | Type | Value |
|---|---|---|
| `subtask` | `string` | label name (e.g. `grasp_object`, `unlabeled`) |
| `subtask_index` | `int64` | `0..K-1` in stable first-appearance order across the export |
| `description` | `string` | empty string default; profile may inject from a label-spec YAML |

Rows = the set of distinct phases observed across all exported episodes' `segments[*].phase`, plus reserved phases (`unlabeled`, `unknown`) if they appear OR if needed for gap-filling. Order is **first appearance, stable**: deterministic given the same input set.

### 4.3 `meta/episodes/<chunk>/file-NNN.parquet`

For each per-episode metadata row, three list columns are added (with `<annotation_prefix>_` prefix from profile):

| Column | Type | Value |
|---|---|---|
| `mimicanno_subtask_names` | `list<string>` | `[seg.phase for seg in segments]` in segment order |
| `mimicanno_subtask_start_frames` | `list<int64>` | inclusive |
| `mimicanno_subtask_end_frames` | `list<int64>` | inclusive |

If `profile.sink.params.annotation_prefix` is `null`, the columns use the bare `subtask_names` / `subtask_start_frames` / `subtask_end_frames` names instead. The SARM `_load_episode_annotations` `col(...)` fallback reads either form.

### 4.4 `meta/info.json`

Read source `meta/info.json` verbatim. Update only the `features` section by **adding** entries for new columns:

```json
{
  ...,
  "features": {
    ...,
    "subtask_index": {
      "dtype": "int64",
      "shape": [1],
      "names": null
    },
    "mimicanno.ee_delta_6d": {
      "dtype": "float32",
      "shape": [6],
      "names": ["dx", "dy", "dz", "drx", "dry", "drz"]
    },
    "mimicanno.gripper_normalized": {
      "dtype": "float32",
      "shape": [1],
      "names": null
    },
    "mimicanno.gripper_delta": {
      "dtype": "float32",
      "shape": [1],
      "names": null
    }
  }
}
```

`codebase_version`, `total_episodes`, `total_frames`, `chunks_size`, `fps`, `splits`, `data_path`, `video_path`, and all other top-level keys are preserved verbatim.

### 4.5 Other meta/ files

Files in `<DS>/meta/` that are not touched (`tasks.parquet`, `stats.parquet`, etc.) are copied verbatim into `<OUT>/meta/`. In `--symlink-data` mode they are still copied (small files), not symlinked, to keep `meta/` self-contained and editable.

## 5. ExportProfile

### 5.1 YAML schema

```yaml
# example: mimicanno/configs/exports/so101_sarm.yaml
schema_version: "1"          # ExportProfile schema version (this spec defines "1")
name: so101_sarm
description: |
  Default SO101 → LeRobot v3 SARM-trainable export.
  Body-frame ee_delta_6d + gripper, mimicanno-prefixed annotation columns.

source:
  robot_adapter: so101                # so101 | aloha | koch | generic
  pass_through_raw_action: true       # write raw action.* columns through to OUT
  generic_adapter_config: null        # required when robot_adapter == "generic"

canonical:
  delta_basis: body_frame_t           # body_frame_t | world | base
  rotation_repr: rotvec               # rotvec only in v1
  gripper_source: observation         # observation | action

sink:
  writer: lerobot_v3                  # only writer in v1
  params:
    annotation_prefix: mimicanno      # null = bare subtask_names columns
    subtask_registry_path: meta/subtasks.parquet
    extra_per_frame_columns:
      - { name: mimicanno.ee_delta_6d, source: ee_delta_6d, dtype: float32 }
      - { name: mimicanno.gripper_normalized, source: gripper_normalized, dtype: float32 }
      - { name: mimicanno.gripper_delta, source: gripper_delta, dtype: float32 }

sidecar:
  enabled: true
  path: meta/mimicanno_segments.parquet

gates:
  require_reviewed: false
  forbid_degraded_pipeline: false
  forbid_unlabeled_segments: false
```

Validated against `mimicanno/jsonschemas/export_profile.schema.json`.

### 5.2 ExportProfile dataclass

```python
@dataclass(frozen=True)
class SourceConfig:
    robot_adapter: Literal["so101", "aloha", "koch", "generic"]
    pass_through_raw_action: bool
    generic_adapter_config: dict | None

@dataclass(frozen=True)
class CanonicalConfig:
    delta_basis: Literal["body_frame_t", "world", "base"]
    rotation_repr: Literal["rotvec"]
    gripper_source: Literal["observation", "action"]

@dataclass(frozen=True)
class ExtraColumn:
    name: str
    source: Literal["ee_delta_6d", "gripper_normalized", "gripper_delta", "ee_pose_world"]
    dtype: Literal["float32", "float64"]

@dataclass(frozen=True)
class SinkConfig:
    writer: Literal["lerobot_v3"]
    params: dict   # writer-specific; for lerobot_v3:
                   #   annotation_prefix: str | None
                   #   subtask_registry_path: str
                   #   extra_per_frame_columns: list[ExtraColumn]

@dataclass(frozen=True)
class SidecarConfig:
    enabled: bool
    path: str

@dataclass(frozen=True)
class GatesConfig:
    require_reviewed: bool
    forbid_degraded_pipeline: bool
    forbid_unlabeled_segments: bool

@dataclass(frozen=True)
class ExportProfile:
    schema_version: Literal["1"]
    name: str
    description: str
    source: SourceConfig
    canonical: CanonicalConfig
    sink: SinkConfig
    sidecar: SidecarConfig
    gates: GatesConfig

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ExportProfile": ...
    def to_dict(self) -> dict: ...
    def hash(self) -> str:
        """sha256 of canonical JSON of to_dict(); recorded in .mimicanno-export.json."""
        ...
```

### 5.3 Profile resolution

`--profile <X>` resolves as:

1. If `X` ends in `.yaml` or `.yml` and is an absolute or `./`-prefixed path → load from that path.
2. Otherwise treat `X` as a name → load from `mimicanno/configs/exports/<X>.yaml` (package data, force-included via hatch).
3. If neither matches → `EXPORT_PROFILE_NOT_FOUND`.

CLI `gates` flags (`--require-reviewed`, `--allow-degraded`, `--allow-unlabeled`) merge with the profile via OR-on-strict / AND-on-allow:

```
effective.require_reviewed       = profile.gates.require_reviewed       OR cli.--require-reviewed
effective.forbid_degraded_pipeline = profile.gates.forbid_degraded_pipeline AND NOT cli.--allow-degraded
effective.forbid_unlabeled_segments = profile.gates.forbid_unlabeled_segments AND NOT cli.--allow-unlabeled
```

This means CLI can only **tighten** require_reviewed and **loosen** forbid_*. Loosening of require_reviewed via CLI is intentionally not provided — `reviewed=False` content should never reach a SARM training run silently.

## 6. CLI

```
mimicanno export
  --dataset <root>              [required] source LeRobot v3 dataset root
  --runs-root <path>            [optional] mimicanno runs/ root (default: $CWD/runs)
  --target-phase <1|2|3|4>      [required] which phase to export
  --profile <name|path>         [required] profile YAML
  --out <path>                  [required, unless --in-place] output dataset root

  # Run selection
  [--config-hash <hex>]         filter to a specific config_hash when phase has multiple
  [--run <canonical>]...        explicit canonical_name(s); overrides target-phase + episode auto-discovery
  [--episode <int>]...          restrict to specific episode_index(es)

  # Output mode (mutually exclusive)
  [--symlink-data]              [default] symlink videos/, rebuild data/, fresh meta/
  [--copy-data]                 full copy of videos/ as well
  [--in-place]                  mutate <dataset> in-place (requires --yes-i-mean-it)
  [--yes-i-mean-it]             confirms --in-place

  # Behavior
  [--force]                     replace existing OUT
  [--require-reviewed]          gate: refuse runs with reviewed=False segments
  [--allow-degraded]            accept manifests with degraded_from_phase != None
  [--allow-unlabeled]           accept segments with phase="unlabeled"
  [--skip-missing]              warn instead of fail-fast on missing run for an episode
  [--dry-run]                   plan only; print machine-readable JSON of intended writes; exit 0
```

Exit codes:
- `0`: success (or `--dry-run`)
- `1`: I/O failure (filesystem error, parquet corruption, etc.)
- `2`: structured error with `EXPORT_*` code; JSON written to stderr per existing mimicanno error idiom

stdout (success): single-line JSON summary `{"out": "...", "episode_count": N, "manifest_path": "..."}`.

stderr: progress lines (per-episode) at INFO level by default; structured error JSON at exit 2.

### 6.1 `--dry-run` output

```json
{
  "dry_run": true,
  "profile": {"name": "so101_sarm", "hash": "<sha256-12>"},
  "output_mode": "symlink",
  "out": "/path/SO101_annotated",
  "episodes": [
    {"episode_index": 0, "canonical_name": "ep0__abc123def456", "run_hash": "<sha256-12>"},
    ...
  ],
  "would_write": [
    "OUT/data/chunk-000/episode_000000.parquet",
    "OUT/meta/subtasks.parquet",
    "OUT/meta/episodes/chunk-000/file-000.parquet",
    "OUT/meta/mimicanno_segments.parquet",
    "OUT/meta/info.json",
    "OUT/.mimicanno-export.json"
  ],
  "would_symlink": ["OUT/videos -> /path/SO101/videos"]
}
```

## 7. Output destination model

### 7.1 `--symlink-data` (default)

```
OUT.tmp.<pid>/
  videos/        → symlink (relative) to <DATASET>/videos/
  data/          (new directory)
    chunk-000/
      episode_000000.parquet  (new file: source columns + subtask_index + extras)
      ...
  meta/
    info.json                 (source merged with features additions)
    tasks.parquet             (verbatim copy)
    subtasks.parquet          (new file)
    episodes/<chunk>/file-NNN.parquet  (source + 3 list columns)
    mimicanno_segments.parquet (new sidecar file)
    [other meta/* files copied verbatim]
  .mimicanno-export.json      (provenance manifest)

→ os.replace(OUT.tmp.<pid>, OUT)
```

Symlinks are **relative** by default for portability (e.g., across mount points). `--absolute-symlinks` flag is **not provided** in v1; if needed, can be added later.

### 7.2 `--copy-data`

Same as `--symlink-data` but `videos/` is recursively copied (`shutil.copytree`) instead of symlinked. Use when the consumer cannot follow symlinks.

### 7.3 `--in-place`

Requires `--yes-i-mean-it` co-flag → otherwise `EXPORT_INPLACE_NO_CONFIRM`.

```
<DATASET>/
  .mimicanno-backup-<ISO8601>/
    data/<chunk>/episode_NNNNNN.parquet      (verbatim copy of pre-export state)
    meta/info.json                            (verbatim copy)
    meta/episodes/<chunk>/file-NNN.parquet   (verbatim copy)
    [no copy of meta/subtasks.parquet, since it's a new file]
  data/<chunk>/episode_NNNNNN.parquet         (per-file os.replace from .tmp.<pid>)
  meta/info.json                              (atomic write)
  meta/subtasks.parquet                       (new file, atomic write)
  meta/episodes/<chunk>/file-NNN.parquet     (per-file os.replace)
  meta/mimicanno_segments.parquet             (new file, atomic write)
  .mimicanno-export.json                      (atomic write)
```

If any per-file write fails partway: backup remains, partially-written data files are reverted from backup if possible, error is raised with the backup path.

`mimicanno export-undo --dataset <DATASET> --backup <ISO8601>` is **deferred** to sub-project E. The backup directory is created and documented in this spec, but the restore tool is out of scope.

### 7.4 Atomicity

All writes go through `<final>.tmp.<pid>` and `os.replace`. The bulk export's transaction boundary is the final `os.replace(OUT.tmp.<pid>, OUT)` (or, for `--in-place`, the per-file rename loop completes successfully).

If the process crashes mid-bulk:
- For `--symlink-data` / `--copy-data`: `OUT.tmp.<pid>/` is left behind. A subsequent run with the same `--out` and matching profile_hash + runs_used can short-circuit (idempotency, §9.1); otherwise `--force` is required.
- For `--in-place`: backup directory is left behind. Manual recovery: `rm -rf data/ meta/ && cp -r .mimicanno-backup-<ISO>/{data,meta} .` Document this in the CLI error message.

The scavenger pattern from parent spec §4.4 (PID-based stale-tmp cleanup) is **not** applied to export `.tmp.<pid>` directories in v1 — that's an opt-in concern for higher-volume operations and can be added later.

## 8. Provenance manifest (`.mimicanno-export.json`)

Written at the root of the output dataset. Schema:

```json
{
  "schema_version": "1",
  "kind": "mimicanno.export",
  "profile": {
    "name": "so101_sarm",
    "hash": "sha256-12-hex",
    "schema_version": "1"
  },
  "source_dataset_path": "/abs/path/SO101",
  "runs_root": "/abs/path/runs",
  "target_phase": 4,
  "config_hash_filter": null,
  "output_mode": "symlink",
  "runs_used": {
    "0": "ep0__abc123def456",
    "1": "ep1__abc123def456",
    "2": "ep2__abc123def456"
  },
  "run_hashes": {
    "0": "sha256-12",
    "1": "sha256-12",
    "2": "sha256-12"
  },
  "episode_count": 3,
  "subtask_count": 11,
  "sidecar_schema_version": "1",
  "mimicanno_version": "0.1.0",
  "generated_at": "2026-04-30T12:34:56Z",
  "cli_args": ["--dataset", "/abs/path/SO101", "--target-phase", "4", "..."],
  "host": {
    "platform": "linux",
    "python": "3.11.7"
  }
}
```

Validated against `mimicanno/jsonschemas/export_manifest.schema.json`.

## 9. Idempotency

### 9.1 Reuse short-circuit

When `--out` already exists and contains a `.mimicanno-export.json`:

1. Load `existing.profile.hash` and `existing.runs_used`.
2. Compute `current.profile.hash` from the resolved profile.
3. Compute `current.runs_used` from the resolved canonical_names.
4. If both match exactly: log `INFO: existing export matches current request; no-op` and exit 0 with the same stdout summary as a fresh run. (This is reuse, not replacement.)
5. If they differ and `--force` is set: replace via the standard `.tmp.<pid>` + `os.replace` flow.
6. If they differ and `--force` is not set: raise `EXPORT_OUT_EXISTS` with both manifests printed in the error JSON for diff.

This mirrors parent spec §4.4's reuse-vs-replace policy for run dirs.

### 9.2 Profile hash stability

`profile.hash()` = sha256 of canonicalized JSON of `to_dict()` (sorted keys, no whitespace, UTF-8). This must be stable across mimicanno minor versions for the same input YAML. Adding optional fields with explicit defaults to `ExportProfile` is a major-version change and bumps `schema_version`.

### 9.3 Output determinism

For a fixed `(dataset, runs_used, profile)` triple:

- `data/<chunk>/episode_NNNNNN.parquet` rows are deterministic byte-for-byte (frame order is preserved from source; new columns are deterministic functions of source + annotation).
- `meta/subtasks.parquet` rows are deterministic — first-appearance order across episodes processed in episode_index order.
- `meta/episodes/...` list columns are deterministic.
- `meta/mimicanno_segments.parquet` row order is deterministic — sorted by `(episode_index, segment_index)`.
- `.mimicanno-export.json` `generated_at` and `host.*` are the only non-deterministic fields; all others are reproducible.

Tests verify byte-equivalence across two runs except for the documented non-deterministic fields.

## 10. Round-trip property (parent §15.4 #17)

The parent spec's exit criterion #17 states: "Edit UI persists changes via backend; export to parquet matches the round-trip schema." This sub-project covers the export side. Round-trip is split into two formal properties.

### 10.1 RT-1: label round-trip

```
Given: an annotation.json A with segments S = [s_1, ..., s_n].
Run:  export → meta/mimicanno_segments.parquet + meta/subtasks.parquet.
Read: reconstruct list[SubtaskSegment] S' from those two files.

Property: S ≡ S'  (semantic equivalence)

where ≡ means equality on all fields except:
  - start_boundary.per_source_scores  (lossy: only aggregate score recoverable)
  - end_boundary.per_source_scores    (same)
  - any field added in a future SubtaskSegment schema version not represented in
    sidecar v1 (forward-compat hatch; raises a sidecar_schema_version warning)
```

Tested via `tests/exports/test_roundtrip_label.py` with 3+ fixture annotation.json files (one per phase 1/3/4) ranging in segment count 1..30.

### 10.2 RT-2: action round-trip

```
Given: a CanonicalEpisode C with arrays (ee_pose_world, ee_delta_6d, gripper_normalized, gripper_delta).
Run:  export → data/<chunk>/episode_NNNNNN.parquet  (with extra_per_frame_columns enabled).
Read: read parquet → reconstruct CanonicalEpisode' C'.

Property:
  np.allclose(C.ee_delta_6d,         C'.ee_delta_6d,         atol=1e-6, rtol=1e-5)
  np.allclose(C.gripper_normalized,  C'.gripper_normalized,  atol=1e-6, rtol=1e-5)
  np.allclose(C.gripper_delta,       C'.gripper_delta,       atol=1e-6, rtol=1e-5)

  ee_pose_world is NOT round-tripped through the data parquet by default
  (it's not in the default extra_per_frame_columns); profiles that opt in
  via { source: ee_pose_world } in extra_per_frame_columns get RT-2 extended.
```

Tested via `tests/exports/test_roundtrip_action.py`.

## 11. Error handling

Errors raise `MimicAnnoError` (existing) with structured `error_code` and JSON details. CLI exit 2.

| `error_code` | Trigger |
|---|---|
| `EXPORT_PROFILE_INVALID` | YAML fails JSON-schema validation; field-level details in error JSON |
| `EXPORT_PROFILE_NOT_FOUND` | `--profile <X>` resolves to no file under names or paths |
| `EXPORT_DATASET_NOT_FOUND` | `--dataset <root>` does not exist or lacks `meta/info.json` |
| `EXPORT_RUNS_ROOT_NOT_FOUND` | `--runs-root <path>` does not exist or lacks `index.json` |
| `EXPORT_RUN_NOT_FOUND` | No run for episode E matches (target_phase, config_hash); error JSON lists candidates and reasons |
| `EXPORT_RUN_AMBIGUOUS` | ≥ 2 runs match for episode E; error JSON lists candidates with their config_hash; suggests `--config-hash` or `--run` |
| `EXPORT_EPISODE_MISMATCH` | `annotation.episode_index` ≠ requested episode, or `annotation.episode_id` ≠ source-derived episode_id |
| `EXPORT_PHASE_DOWNGRADE` | `manifest.pipeline_status.degraded_from_phase` is set and `forbid_degraded_pipeline` is effective |
| `EXPORT_UNLABELED_PRESENT` | Any segment has `phase="unlabeled"` and `forbid_unlabeled_segments` is effective |
| `EXPORT_NOT_REVIEWED` | Any segment has `reviewed=False` and `require_reviewed` is effective |
| `EXPORT_OUT_EXISTS` | OUT already exists, `--force` not set, idempotency short-circuit conditions not met |
| `EXPORT_OUT_PARENT_MISSING` | Parent directory of OUT does not exist |
| `EXPORT_RAW_ACTION_MISSING` | `pass_through_raw_action=true` but source parquet has no action.* columns matching adapter contract |
| `EXPORT_FRAME_COUNT_MISMATCH` | Annotation's last segment.end_frame ≠ source num_frames - 1; error JSON shows both numbers and mode (typical cause: source dataset edited after annotation) |
| `EXPORT_INPLACE_NO_CONFIRM` | `--in-place` without `--yes-i-mean-it` |
| `EXPORT_INPLACE_BACKUP_FAILED` | Backup dir creation or copy failed before any in-place mutation; abort cleanly |
| `EXPORT_SINK_VALIDATION_FAILED` | Post-write parquet schema validation failed (corrupt write or env disk-fill); leaves `.tmp.<pid>` for inspection |

`--skip-missing` downgrades `EXPORT_RUN_NOT_FOUND` to a per-episode warning (logged) and excludes that episode from the export. All other errors remain hard.

## 12. Testing

### 12.1 Unit tests

`tests/exports/test_canonical.py`:
- `ee_delta_6d` math:
  - identity rotation across all frames → all delta rotvecs are zeros
  - pure translation → Δp_body matches expected; Δr_body is zeros
  - pure rotation around z by π/4 per frame → Δr_body is `[0, 0, π/4]` for body_frame_t basis
  - mixed translation + rotation → matches closed-form computed in test
  - last frame padded to zeros
- `gripper_delta`: `[0.1, 0.3, 0.7, 0.7, 0.2]` → `[0.2, 0.4, 0.0, -0.5, 0.0]`
- Edge cases: T=1 (all deltas zero), T=2

`tests/exports/test_profile.py`:
- All three default profiles load without error
- Invalid YAML raises `EXPORT_PROFILE_INVALID` with field path
- `from_yaml` is hash-stable across two loads of the same file
- CLI gates merge with profile gates per §5.3 rules

`tests/exports/test_output_layout.py`:
- `--symlink-data`: `videos/` is a relative symlink; `data/` is a fresh directory
- `--copy-data`: `videos/` files exist as regular files
- `--in-place`: backup directory created before any write; matches pre-export state
- `.tmp.<pid>` cleanup on success; left-behind on failure
- POSIX `os.replace` atomicity via concurrent-reader simulation (writer thread + reader thread)

### 12.2 Integration tests (mini fixture dataset)

`tests/exports/fixtures/mini_so101/`: a real LeRobot v3 dataset with 3 episodes × ~20 frames each, ~50 KB total, checked into git. Generated by `tests/exports/fixtures/build_mini_so101.py` (also committed) for reproducibility.

The fixture contains:
- `data/chunk-000/episode_000000.parquet`, `episode_000001.parquet`, `episode_000002.parquet`
- `videos/observation.images.front/chunk-000/episode_*.mp4` (placeholder 1×1 videos for path validity)
- `meta/info.json`, `tasks.parquet`, `episodes/chunk-000/file-000.parquet`
- Parquet schemas mirror SO101 (joint_pos, ee_pos, ee_rotvec, gripper_pos, action.*)

Plus `tests/exports/fixtures/mini_runs/`: corresponding mimicanno runs with `annotation.json` files for each episode at Phase 4.

`tests/exports/test_sink_lerobot_v3.py`:
- Full sink writer over the fixture
- Validate output `data/<chunk>/episode_*.parquet` schema matches expected: original columns + `subtask_index` + extras
- Validate `subtask_index` per frame matches the expected segment assignment (closed-closed inclusive)
- Validate `meta/subtasks.parquet` rows are first-appearance order
- Validate `meta/episodes/<chunk>/file-NNN.parquet` has the 3 list columns with correct prefix
- Validate `meta/mimicanno_segments.parquet` schema and row count = sum of segments

`tests/exports/test_bulk.py`:
- End-to-end `bulk_export()` over the fixture
- Three episodes, each with its own canonical_name
- Verify episode count, subtask count, manifest contents
- Idempotency: second run with same params is a no-op

`tests/exports/test_cli_export.py`:
- Subprocess invocation: `uv run mimicanno export ...`
- Exit code 0 on success; exit 2 with structured JSON on each error
- `--dry-run` output schema validates against a JSON schema
- `--in-place` without `--yes-i-mean-it` → `EXPORT_INPLACE_NO_CONFIRM`

### 12.3 Round-trip tests

`tests/exports/test_roundtrip_label.py`:
- Three fixture annotation.json files (Phase 1, Phase 3, Phase 4) with 1, ~10, ~25 segments
- Export → read sidecar → reconstruct → assert byte-equivalent (modulo per-source boundary scores, which are documented lossy)

`tests/exports/test_roundtrip_action.py`:
- Synthesize CanonicalEpisode with known arrays
- Export → read parquet → reconstruct → `np.allclose(orig, atol=1e-6, rtol=1e-5)`
- Test all three `delta_basis` modes

### 12.4 Error-path tests

`tests/exports/test_errors.py`: one test per `EXPORT_*` code, asserting:
- Exit code 2 (or 0 for `--skip-missing` warning case)
- `error_code` field in stderr JSON matches expected
- `error_code`-specific fields are populated (e.g., `EXPORT_RUN_AMBIGUOUS` includes `candidates` array)

### 12.5 Test count target

≥ 50 new tests. Existing 668 tests must stay green:

- Run `uv run pytest` → 668 + ≥ 50 pass
- Run `uv run mypy --strict mimicanno/exports/` → clean
- Run `uv run ruff check mimicanno/exports/` → clean

## 13. Exit criteria

1. `mimicanno export --dataset DS --target-phase 4 --profile so101_sarm --out OUT` succeeds on the SO101 dataset and produces:
   - `OUT/data/chunk-000/episode_NNNNNN.parquet` with `subtask_index` and the three extra `mimicanno.*` columns
   - `OUT/meta/subtasks.parquet` with rows for every observed phase
   - `OUT/meta/episodes/chunk-000/file-000.parquet` with `mimicanno_subtask_names` / `_start_frames` / `_end_frames` lists
   - `OUT/meta/mimicanno_segments.parquet` with one row per segment across all episodes
   - `OUT/meta/info.json` updated with new `features` entries; all other keys verbatim
   - `OUT/videos/` as a relative symlink to `DS/videos/`
   - `OUT/.mimicanno-export.json` with full provenance
2. Re-running with the same `(dataset, runs_used, profile)` is idempotent: no rewrite, log message "existing export matches current request; no-op", exit 0.
3. `--force` re-publishes byte-equivalent output (modulo `generated_at` and `host.*` in the export manifest).
4. RT-1 (label round-trip) and RT-2 (action round-trip) tests pass on at least 3 fixture annotation.json files spanning Phase 1, 3, 4.
5. `--in-place` succeeds, creates `.mimicanno-backup-<ISO>/` containing a verbatim copy of pre-export `data/<chunk>/*.parquet` + `meta/info.json` + `meta/episodes/<chunk>/*.parquet`, and leaves the source dataset readable as a valid LeRobot v3 dataset post-export.
6. `~/MimicRec/lerobot/src/lerobot/policies/sarm/processor_sarm.py:_load_episode_annotations(episode_index, episodes_df, "mimicanno", global_names)` returns non-None lists for an exported dataset (smoke test in `test_bulk.py` reads the output episodes parquet and exercises `_load_episode_annotations` against it).
7. All 13 `EXPORT_*` error codes have at least one test that triggers them and validates the structured error output.
8. `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` are all green.
9. Phase 1/2/3/4 invocations of `mimicanno annotate` produce byte-identical run dirs to before this sub-project (no regression on the existing 668 tests).

## 14. Open items (deferred, not blocking this sub-project)

- `mimicanno export-undo --dataset <root> --backup <ISO>`: in-place restore tool. Manual restore is documented; tool is sub-project E.
- Sink writers other than `lerobot_v3` (RLDS, ARIO, raw HDF5). `SinkWriter` protocol leaves the door open.
- Rotation representations other than `rotvec` (quat / euler / rotmat). Profile schema `rotation_repr` field is `Literal["rotvec"]` in v1.
- `delta_basis` variants beyond `body_frame_t` / `world` / `base` (e.g., `body_frame_{t+1}`, learned reference frame). Currently only the three are supported.
- Per-segment per-source boundary scores in the sidecar (parent §6.1's full `BoundaryRef.per_source_scores` is currently lossy in RT-1; if sub-project D's evaluation harness needs them, sidecar schema bumps to v2).
- Streaming export (current implementation buffers all episodes in memory; not a concern at typical dataset sizes < 1 GB / 1000 episodes).
- Automatic SARM `processor_sarm.py:dense_subtask_names` config generation from the exported `meta/subtasks.parquet` (sub-project E concern).
- `--absolute-symlinks` flag for cross-mount-point export.
- Scavenger for stale `OUT.tmp.<pid>` directories (parent §4.4 has the pattern but we don't apply it here in v1).
- Multiple-annotation-prefix coexistence in a single dataset (e.g., `mimicanno_*` and `gemini_baseline_*` columns side-by-side). Currently each `mimicanno export` invocation overwrites the prefix it writes; multi-annotator merging is a future tool.

## 15. Acknowledgments and references

- Parent spec: `2026-04-25-mimicanno-design-brushup.md` (§4 run dir, §6 schema, §7 LeRobot read contract, §10 phase decomposition, §14 MimicRec integration, §15.4 #17).
- Sibling spec: `2026-04-29-mimicanno-phase4-smoothing-design.md` (Phase 4 — produces the input).
- LeRobot v3 reference: `~/MimicRec/lerobot/src/lerobot/datasets/{dataset_metadata.py, dataset_reader.py, io_utils.py, utils.py}`.
- SARM consumer reference: `~/MimicRec/lerobot/src/lerobot/policies/sarm/processor_sarm.py:_load_episode_annotations`.
- Existing MimicRec stub (to be replaced in sub-project E): `~/MimicRec/backend/mimicrec/annotator/subtask.py`.
