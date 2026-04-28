# MimicAnno Phase 3 — SAM3 + integrated boundary score + relabel with `vlm_with_object_state` design

Status: **draft**, awaiting review (Codex).
Author: brainstorming session 2026-04-28.
Supersedes: nothing — new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§3 Phase 3 deliverable, §4.1 hashing, §4.3 manifest schema, §5.3 Phase 3 boundary sources extension, §6.1 SubtaskSegment Phase 3 fields, §9 SAM3 prompt-generation contract, §11 Phase 3 error rows, §12 package structure, §15.3 Phase 3 exit criteria).
Sibling: [`2026-04-27-mimicanno-phase2-vlm-labeling-design.md`](./2026-04-27-mimicanno-phase2-vlm-labeling-design.md) (Phase 2 — Phase 3 reuses Phase 2's `LocalGemmaVLMLabeler` loader and per-segment labeling helpers; this spec spells out the additive object-state extension).

## Reviewer context

(For reviewers unfamiliar with the parent spec — skip if you've already read it.)

### What is MimicAnno?

MimicAnno is a **robot-episode subtask annotation tool**. Given a robot manipulation episode (video + parquet of action/proprio time series + a natural-language task instruction such as "pick the red block and place it in the bin"), it produces a **structured annotation** that splits the episode into temporal **segments**, each tagged with one of a fixed set of subtask labels (`approach_object`, `grasp_object`, `lift_object`, `move_to_target`, …). The output is consumed downstream by MimicRec (a separate tool for VLA training / replay / evaluation).

MimicAnno is an **independent Python package** (`mimicanno`). Its only persistent contracts with downstream consumers are a versioned **run directory** on disk (`runs/<canonical_name>/{manifest.json, annotation.json, boundaries.json, signals.json, video.mp4, …}`) and a Plan 2 React/Vite read-only viewer.

### How the work is staged

```
Phase 1: signals-based boundary detection + read-only viewer        ← SHIPPED
Phase 2: provisional VLM labeling (no object-tracking)              ← SHIPPED
Phase 3: SAM3 object tracking + object-aware boundaries + relabel   ← THIS SPEC
Phase 4: temporal smoothing / Viterbi
Phase 5: human-edit UI + export to MimicRec + evaluation harness
```

Phase 1 and Phase 2 are in `main`. Phase 1 produced one `phase="unlabeled"` segment per bracketed clip from gripper / EEF / action signals. Phase 2 replaced every `"unlabeled"` with one of the allowed labels (or reserved `"unknown"`) by calling Gemma per segment with `task_text + keyframes + 5-scalar robot-state summary`, stamping `label_source="vlm_robot_state_only"` and `object_state_unavailable=true`.

### What Phase 3 (this spec) does

Phase 3 introduces **SAM3-based object tracking** as a first-class signal source. Three things change:

1. **Boundary detection becomes object-aware.** Two new sources (`gripper_object_distance_threshold_crossing`, `object_motion_start_stop`) join the four Phase 1 sources in the integrated weighted score (parent spec §5.3). Weights are rebalanced to keep the gripper-biased precision intent.
2. **VLM labeling becomes object-aware.** The per-segment `ObjectStateSummary` (object/target/tool prompts, gripper-object distance, primary object motion, object-at-target proxy) extends the Phase 2 prompt. Labels are stamped `label_source="vlm_with_object_state"`.
3. **A new `tracks.json` artifact** records per-track sparse bbox samples with gap events. Per-segment `object_track_ids` (declared in Phase 1 schema as `[]`, parent spec §6.1) is now populated.

Phase 3 is a **separate canonical run directory** from Phase 1/2 (parent spec §4.1: `target_phase` enters `config_hash` → distinct `run_hash` → distinct `canonical_name`). Phase 3 does not consume any Phase 2 artifact at runtime; it re-runs from the original episode inputs.

If you're a reviewer evaluating this spec, the question is: **could a competent engineering team take this document and produce an implementation that (a) satisfies parent-spec exit criteria §15.3 #14 and #15, (b) does not violate the parent-spec invariants on hashing / atomicity / schema versioning / error idiom, (c) preserves Phase 1/2 behavior unchanged, and (d) leaves Phase 4+ work unobstructed?**

## 0. Scope and intent

In scope:

- New `mimicanno/object_tracker/` package wrapping the vendored `sam3/` repo (parent spec §12 layout). Public API surface: `TrackingPlanner`, `SAM3Runtime`, `Propagator`, `compute_object_signals`, plus `Track` / `TrackSample` / `GapEvent` / `BBox` / `TrackingPlan` / `ObjectSignals` dataclasses.
- New `tracks.json` artifact (schema §3) written under each Phase 3 canonical run directory.
- Two new boundary sources with concrete formulae and a Phase 3 weight rebalance (§4) producing distinct `boundaries.json` content but the same schema as Phase 1/2.
- `ObjectStateSummary` dataclass + `build_prompt` extension (§5) producing Phase 3-mode prompts. Phase 2 prompt is unchanged (default-None object-state field).
- Per-segment fallback (§6): when a segment has no usable object track, label that single segment via the Phase 2 path (`vlm_robot_state_only`, `object_state_unavailable=true`) without degrading the run.
- Whole-run degrade (§7) follows parent spec §9.4 verbatim, with one new manifest field (`object_state_segment_coverage`) for observability.
- `mimicanno annotate --target-phase 3 --vlm-model <id> --sam3-checkpoint <path> ...` CLI extension. Phase 1/2 invocations remain identical.
- `[project.optional-dependencies] sam3 = [...]` in `pyproject.toml`. CI does not install this extra; `MIMICANNO_RUN_SAM3_SMOKE=1` + CUDA gates the only test that loads real SAM3 weights.
- Test strategy across 3 layers (unit / integration with `FixtureSAM3Tracker` + `FixtureTrackingPlanner` / gated real-SAM3 smoke).

Non-goals:

- **No viewer changes.** Phase 3 outputs `tracks.json` and populates `object_track_ids` / `pipeline_status.object_state_available`, but no React/Vite component is added. Track overlays / bbox visualizers are Phase 5 work. The existing viewer's pipeline-status banner already surfaces the `object_state_available` flag without code changes.
- **No mask persistence.** SAM3 produces masks internally for propagation; `tracks.json` records bbox + score only. Mask sidecars (`tracks/<track_id>/<frame>.png`) are a deferred extension behind a future `--persist-masks` flag.
- **No multi-camera support.** Single video stream only. Multi-camera tracking is a future extension.
- **No Phase 4 smoothing.** Phase 3 emits boundaries and labels at per-segment granularity exactly as Phase 1/2 did; smoothing/Viterbi is Phase 4.
- **No `failure_flags` auto-inference.** Object-state signals (e.g. dropped grasp = object speed nonzero while gripper still closed) could in principle be used to flag `failed_grasp`; we defer this to Phase 4-5 to keep Phase 3 scoped to "tracking + labeling" rather than "tracking + labeling + failure inference."
- **No HuggingFace transformers integration of SAM3.** SAM3 is not in `transformers` as of 2026-04; we vendor `sam3/` and import directly. The `sam3_runtime.py` wrapper isolates this so a future transformers integration is a swap-out.
- **No SAM3 prompt iteration past Step A retries.** Gemma's entity-extraction call has the same retry budget as Phase 2 (max 3) and the same "fall back to empty list" terminal behavior.
- **No new schema_version bumps.** All Phase 3 changes are additive-or-populate within existing 0.1.x schemas. The new `tracks.json` is a new artifact at `schema_version="0.1.0"`. Existing artifacts (`signals.json`, `boundaries.json`, `annotation.json`, `manifest.json`) get new but optional / already-declared fields populated.

## 1. Architecture

### 1.1 Phase 3 in the pipeline

Phase 3 is a **purely additive** stage on top of the existing Phase 1/2 pipeline. The CLI dispatches by `target_phase`:

```
mimicanno annotate --target-phase 3 --vlm-model <id> --sam3-checkpoint <path> ...
  │
  ├─ inputs validated (video, parquet, task_text, robot_adapter, labels)
  ├─ AnnotationConfig assembled (boundary + vlm + tracking sub-blocks)
  ├─ run_hash computed
  │     - target_phase=3 ∈ config_hash → distinct from any Phase 1/2 run_hash
  │     - model_config.{vlm_model, sam3_model, sam3_checkpoint} included → distinct per model choice
  │     - tracking config (stride, thresholds, weights) included
  │
  ├─ canonical_name resolved
  │
  ├─ [Phase 1 existing]   signals.compute → robot_signals
  │
  ├─ [Phase 3 new — Stage 1b] tracking pipeline:
  │      planner.plan(task_text, initial_frame, allowed_labels)
  │        → if degrade-trigger: hand off to Phase 2 path, return Phase 2 run
  │      sam3_runtime.load(checkpoint) → propagator.run → tracks
  │      compute_object_signals(tracks) → object_signals
  │
  ├─ [Phase 3 new — Stage 2] phase3_boundary_detector.detect(robot_signals, object_signals)
  │      → boundaries (6 sources, Phase 3 weights, score_threshold=0.30)
  │      → segments via Phase 1 bracketing (unchanged algorithm)
  │
  ├─ [Phase 3 new — Stage 3] phase3_labeling:
  │      per-segment compute_object_state_summary(tracks, segment)
  │      apply_phase3_labeling(segments, clip_features_with_object_state, vlm)
  │        → per-segment fallback to Phase 2 path when summary is None
  │      → labeled_segments
  │
  ├─ AnnotationResult assembled (labeled_segments + notes)
  ├─ Manifest assembled (pipeline_phase=3, model_versions.{vlm, sam3},
  │                       pipeline_status.object_state_available=true,
  │                       pipeline_status.object_state_segment_coverage=<float>)
  │
  ├─ [existing] publish transaction (tmp dir → atomic rename → index upsert)
  │   artifacts: video, signals, boundaries, annotation, manifest, **tracks**
  │
  └─ exit 0 (success or degrade-with-Phase-2-output)
```

Phase 3 **does not** modify Phase 1's boundary-detection algorithm (only adds new sources via the existing integrated-score formula), Phase 2's labeling helpers (only extends the prompt with optional object-state), or any of the run-dir / hashing / atomicity / locking / scavenger contracts.

### 1.2 Module map

New package + modules:

```
mimicanno/
  object_tracker/       # NEW package — owns all SAM3 contact
    __init__.py         # re-exports: TrackingPlanner, SAM3Runtime, Propagator,
                        #   Track, TrackSample, GapEvent, BBox, TrackingPlan, ObjectSignals
    track_id.py         # slugify, make_track_id (parent spec §9.5)
    planner.py          # TrackingPlanner protocol; LocalGemmaTrackingPlanner
    sam3_runtime.py     # SAM3Runtime: load() / ground_on_frame() / propagate() / close()
    propagator.py       # Propagator.run(); Track / TrackSample / GapEvent / BBox dataclasses
    signals.py          # compute_object_signals, ObjectSignals dataclass
    fixtures.py         # FixtureTrackingPlanner, FixtureSAM3Tracker
```

Modified modules (Phase 3 additions only; Phase 1/2 behavior unchanged):

```
mimicanno/
  pipeline.py           # branch: when target_phase == 3, run Phase 3 stages 1b/2/3
                        # share Gemma loader between LocalGemmaVLMLabeler and
                        # LocalGemmaTrackingPlanner; close SAM3 before Stage 3
  boundaries.py         # add Phase3BoundaryDetector that wraps the existing
                        # integrated-score machinery with 6 sources + Phase 3 weights
  clip_features.py      # extend ClipFeatures with optional object_state_summary
                        # add compute_object_state_summary
  vlm_labeler.py        # add apply_phase3_labeling (reuses Phase 2 helpers internally)
  vlm_prompt.py         # build_prompt accepts optional object_state_summary;
                        # Phase 2 callsite unchanged
  schema.py             # add ObjectStateSummary, ObjectTrackSummary; (de)serialization
                        # for tracks.json (TracksFile, Track, TrackSample, GapEvent, BBox)
                        # extend SubtaskSegment serialization with object_track_ids
                        # (already declared, populated only in Phase 3)
  config.py             # add TrackingConfig, Phase3BoundaryWeights;
                        # AnnotationConfig.tracking sub-block; BoundaryWeights gains 2 new
                        # fields. Hash backward-compat is enforced at to_dict() time —
                        # see §9.1 (target_phase-gated serialization), NOT by relying on
                        # default values to silently drop out of canonical JSON
  cli.py                # add --sam3-checkpoint, --track-stride-frames flags
                        # add abort path: target_phase == 3 requires --vlm-model and resolvable SAM3
  hashing.py            # no logic change; new TrackingConfig fields enter config_hash
                        # via AnnotationConfig (already covered by recursive serialization)
  io.py                 # add write_tracks_json / read_tracks_json
                        # extend artifact list emitter with tracks.json
  preflight.py          # add SAM3 checkpoint resolution (similar to vlm preflight)
  errors.py             # add SAM3-specific error codes (§7.5)
```

Phase 3 does **not** add a new CLI subcommand. The existing `mimicanno annotate` gets two new flags and one new `--target-phase` value.

### 1.3 Schema versioning impact

| Artifact | Schema bump? | Why |
|---|:---:|---|
| `signals.json` | none | Phase 3 may emit additional channels (`gripper_object_distance`, `primary_object_speed`); the schema's `channels: array` is open-extension — adding a new channel is additive. Viewer ignores unknown channel names today; explicit allowlist deferred to Phase 5. |
| `boundaries.json` | none | New `sources` enum members (`gripper_object_distance_threshold_crossing`, `object_motion_start_stop`) are additive; readers that don't recognize them treat them as opaque strings (parent spec §5.4 already says `sources: list[str]`). |
| `annotation.json` | none | `object_track_ids` / `label_source = "vlm_with_object_state"` / `object_state_unavailable` were declared in the Phase 1 schema (parent spec §6.1) and are now populated. No new fields. |
| `manifest.json` | none | `pipeline_status.object_state_available` was declared in Phase 1. New field `pipeline_status.object_state_segment_coverage: float` is additive (default 1.0 for Phase 1/2 readers; populated only in Phase 3). `model_versions.sam3 = <model_id>` and `model_versions.sam3_checkpoint = <sha256>` are additive entries in the existing dict. `pipeline_params.boundary.weights` gains 2 new keys (additive). `pipeline_params.tracking` is a new sub-block (additive). |
| `tracks.json` | new artifact at `0.1.0` | First introduction of this artifact. Schema in §3. Listed under `manifest.artifacts[]` with `kind="tracks"`, `compat=["0.1"]`. |

The Plan 2 viewer requires no version-handling work for Phase 3:
- `pipeline_status` banner already reads `object_state_available` (Phase 1/2 emit `false`; Phase 3 emits `true`).
- `tracks.json` is a Phase 3-only artifact and the viewer ignores unknown artifact `kind`s today (deferred bbox overlay to Phase 5 per non-goals).

## 2. `object_tracker` package API

All SAM3 contact lives in this package. Downstream code (`pipeline.py`, `boundaries.py`, `clip_features.py`, `vlm_labeler.py`) sees only the dataclasses listed in §2.4.

### 2.1 `track_id.py` — track ID generation

Parent spec §9.5 form: `obj:<role>:<slug>:<index>`.

```python
def slugify(prompt: str) -> str:
    """Lowercase, ASCII-fold, replace runs of non-alnum with single underscore,
    strip leading/trailing underscores. Empty input -> 'unnamed'.

    'Red Block' -> 'red_block'
    'bin A!!'   -> 'bin_a'
    '   '       -> 'unnamed'
    """

def make_track_id(role: Literal["object", "target", "tool"], prompt: str, index: int) -> str:
    """f'obj:{role}:{slugify(prompt)}:{index}'. Index is per-(role, slug) 0-based."""
```

`make_track_id` is the **only** place in Phase 3 code that constructs a track_id string. Tests and viewer parse track_ids by splitting on `:` (4-tuple).

### 2.2 `planner.py` — entity extraction (parent spec §9.1–§9.4)

```python
@dataclass(slots=True, frozen=True)
class TrackingPlan:
    object_prompts: list[str]                # natural-language prompts
    target_prompts: list[str]
    tool_prompts:   list[str]                # typically ["gripper"]; may be []
    initial_detections: dict[str, BBox]      # prompt -> initial bbox (Step B output)
    failed_prompts: list[str]                # Step A succeeded but Step B returned no bbox

class TrackingPlanner(Protocol):
    def plan(
        self,
        *,
        task_text: str,
        initial_frame: np.ndarray,           # H×W×3 RGB uint8
        allowed_labels: LabelSet,
        attempt_max: int = 3,
    ) -> TrackingPlan: ...
```

#### 2.2.1 `LocalGemmaTrackingPlanner`

Implementation that **shares the Gemma model handle** with Phase 2's `LocalGemmaVLMLabeler`. Concrete contract:

- Constructed with `gemma_handle: GemmaHandle` (a thin reference type returned by `LocalGemmaVLMLabeler.shared_handle()`); does not load its own model.
- Step A prompt: a single JSON-output instruction asking Gemma to emit `{"objects": [...], "targets": [...], "tools": [...]}` given task_text + initial_frame. Allowed-label semantic categories are passed as guidance (e.g. labels like `place_object` imply targets exist; tasks without `place_*` labels imply no targets).
- Step A retry: max 3 attempts on JSON parse / schema failure. Each retry appends a stricter amendment (analogous to Phase 2's `_REJECT_AMENDMENT_BY_REASON`). On terminal failure, emit `TrackingPlan(object_prompts=[], target_prompts=[], tool_prompts=[], initial_detections={}, failed_prompts=[])` — caller treats this as the §7.2 `gemma_no_object_prompts` degrade trigger.
- Step B: for each prompt, call `SAM3Runtime.ground_on_frame(initial_frame, prompt)`. Take the highest-scoring bbox. Empty bbox list → prompt added to `failed_prompts`, not to `initial_detections`.

#### 2.2.2 `FixtureTrackingPlanner`

Returns a fixed `TrackingPlan` constructed at instantiation. Used in unit tests and integration tests. Does not depend on Gemma or SAM3.

### 2.3 `sam3_runtime.py` — SAM 3.1 model wrapper

```python
class SAM3Runtime:
    """Wraps the vendored sam3/ package. Owns the SAM 3.1 model lifetime.

    Lazy-loaded on first use. close() releases GPU memory; pipeline.py calls
    close() before invoking Stage 3 (Gemma per-segment labeling) so the two
    models do not co-occupy GPU memory.
    """

    @classmethod
    def load(cls, *, checkpoint: Path, device: str = "cuda") -> "SAM3Runtime": ...

    def ground_on_frame(
        self, frame: np.ndarray, prompt: str
    ) -> list[tuple[BBox, float]]:
        """SAM 3.1 PCS (Promptable Concept Segmentation) on a single frame.
        Returns 0+ (bbox, score) pairs sorted by score desc."""

    def propagate(
        self,
        *,
        frames: Iterator[tuple[int, np.ndarray]],   # (frame_idx, RGB uint8)
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        stride: int,                                # informational only
    ) -> Iterator[FramePropagationResult]: ...

    def close(self) -> None:
        """Release GPU memory. Idempotent."""

@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    frame: int
    detections: dict[str, tuple[BBox, float] | None]   # prompt -> (bbox, score) or None
```

The wrapper's job is to isolate every `import sam3.*` to this file. The choice of which SAM 3.1 entry point to call (model_builder + agent vs. SAM 3.1 video pipeline) is an implementation decision in the writing-plans phase — the contract above is what `Propagator` consumes.

### 2.4 `propagator.py` — propagation + gap detection

```python
@dataclass(slots=True, frozen=True)
class BBox:
    """Normalized image coords. (0,0) = top-left, (1,1) = bottom-right.
    All four floats in [0, 1]; w > 0; h > 0; x + w <= 1; y + h <= 1."""
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def iou(self, other: "BBox") -> float: ...

@dataclass(slots=True)
class TrackSample:
    frame: int                          # actual frame index in the video
    time_sec: float                     # frame / fps
    bbox: BBox
    score: float                        # SAM 3.1 confidence at this sample, [0, 1]

@dataclass(slots=True)
class GapEvent:
    from_frame: int                     # inclusive
    to_frame: int                       # inclusive (single-frame gap: from == to)
    reason: Literal["sam3_lost", "sam3_low_conf", "sam3_reacquired"]

@dataclass(slots=True)
class Track:
    track_id: str                       # parent spec §9.5 form
    role: Literal["object", "target", "tool"]
    prompt: str                         # human-readable, from TrackingPlan
    slug: str                           # slugify(prompt)
    index: int                          # per-(role, slug) 0-based
    samples: list[TrackSample]          # frame ascending strict; sparse (stride-spaced)
    gap_events: list[GapEvent]          # frame ascending; non-overlapping
    primary: bool                       # True for the first track per role

class Propagator:
    def run(
        self,
        *,
        runtime: SAM3Runtime,
        plan: TrackingPlan,
        video_path: Path,
        fps: float,
        n_frames: int,
        stride: int,
        config: TrackingConfig,
    ) -> list[Track]: ...
```

#### 2.4.1 Algorithm

1. Iterate video frames with `stride` step (frame indices `0, stride, 2*stride, …`). Always include the last frame (`n_frames - 1`) if not already aligned.
2. Per frame, call `runtime.propagate(...)`. For each prompt in `plan.{object,target,tool}_prompts ∪ plan.initial_detections.keys()`, receive `(bbox, score) | None`.
3. Per prompt, build samples:
   - If `score >= config.min_track_score` and bbox is valid, emit a `TrackSample`.
   - If `score < config.min_track_score` or bbox is missing, do not emit a sample. Track the gap.
4. Gap consolidation: between two non-adjacent emitted samples `s_i.frame` and `s_{i+1}.frame`, the inclusive frame range `[s_i.frame + 1, s_{i+1}.frame - 1]` is a `GapEvent` with `reason="sam3_lost"` if no SAM3 result, or `"sam3_low_conf"` if SAM3 returned bbox below threshold. Single-stride gaps (i.e. one missed sub-sample) are still recorded — caller may filter by `to_frame - from_frame >= stride`.
5. Re-acquisition: when a track has been in gap for `gap_frames > config.max_gap_frames`, the next emitted sample is checked against the last pre-gap sample's bbox via `iou(...)`:
   - `iou >= config.reacquisition_iou_threshold` → same `track_id`, append `GapEvent(reason="sam3_reacquired", from_frame=current_frame, to_frame=current_frame)` immediately before this sample.
   - `iou < config.reacquisition_iou_threshold` → start a new `Track` with index incremented (`obj:object:red_block:1`).
6. Track ID assignment: `make_track_id(role, prompt, index)` where `index` increments across re-acquisition splits within the same (role, prompt).
7. Primary marking: per role, the first track for `plan.{role}_prompts[0]` (i.e. the index=0 occurrence of the role's first prompt) gets `primary=True`. Non-primary tracks get `primary=False`. Roles with no tracks → no primary.

#### 2.4.2 Output guarantees

- All tracks are returned even if `samples == []` (degenerate, but possible if SAM3 lost the prompt immediately after grounding). Such tracks have `gap_events` covering `[0, n_frames - 1]`. Callers filter as needed.
- Stable ordering: tracks sorted by `(role_order, slug, index)` where `role_order = {"object": 0, "target": 1, "tool": 2}`.
- Determinism: given the same `runtime`, `plan`, `video_path`, `fps`, `n_frames`, `stride`, `config`, `Propagator.run` returns byte-identical `list[Track]`. SAM 3.1 internal stochasticity (if any) is seeded via `config` (see §8.1).

### 2.5 `signals.py` — derived signals from tracks

```python
@dataclass(slots=True)
class ObjectSignals:
    """Frame-aligned (length = n_frames) derived signals.
    Frames inside any source track's gap_events are NaN."""

    gripper_object_distance: dict[str, np.ndarray]
    """object_track_id -> per-frame distance (normalized image diag).
    NaN where either gripper or object bbox is missing at that frame.
    Dict is empty if no gripper tool track exists."""

    object_speed: dict[str, np.ndarray]
    """object_track_id -> per-frame speed (normalized image diag / sec).
    NaN where bbox is missing at that frame.
    Computed as central-difference on bbox-center after linear interp
    between non-NaN sub-sampled frames inside a non-gap region."""

    primary_object_track_id: str | None
    primary_target_track_id: str | None
    gripper_tool_track_id: str | None


def compute_object_signals(
    tracks: list[Track],
    *,
    fps: float,
    n_frames: int,
    image_aspect_ratio: float,
) -> ObjectSignals: ...
```

#### 2.5.1 Distance computation

For each `(object_track, gripper_tool_track)` pair where `gripper_tool_track is not None`:

1. Linear-interpolate each track's bbox-center across non-gap regions (one sub-sample to the next; do **not** interpolate across `gap_events`).
2. At each frame `t`, both centers exist (non-NaN) iff `t ∉ gap_events(object_track) ∪ gap_events(gripper_tool_track)` and `t` is within the interpolation domain of both tracks.
3. `gripper_object_distance[object_track_id][t]` = `sqrt((dx)² + (dy / image_aspect_ratio)²)` where `(dx, dy) = center_object - center_gripper`. Division by aspect ratio re-isotropizes to image-diag-normalized units.
4. Frames where either side is in a gap: `NaN`.

#### 2.5.2 Speed computation

For each object track:

1. Linear-interpolate bbox-center across non-gap regions (same rule).
2. At each frame `t` in the interpolation domain: with `(dx, dy) = center(t+1) - center(t-1)` and inter-frame spacing `Δt = 1/fps`, define `vx = dx * fps / 2`, `vy = dy * fps / 2`. Then `object_speed[track_id][t] = sqrt(vx² + (vy / image_aspect_ratio)²)`. Aspect-ratio division re-isotropizes to image-diag-normalized units / sec.
3. Boundary frames (`t = 0`, `t = n_frames - 1`, frames adjacent to a gap) use forward/backward difference. Frames inside a gap: `NaN`.

#### 2.5.3 Primary track resolution

- `primary_object_track_id` = track_id of the unique track with `role="object" and primary=True` if one exists, else `None`.
- `primary_target_track_id`, `gripper_tool_track_id`: analogous.

### 2.6 `fixtures.py` — test doubles

```python
class FixtureTrackingPlanner(TrackingPlanner):
    """Returns a fixed TrackingPlan. Constructed with all fields explicit."""
    def __init__(self, plan: TrackingPlan): ...

class FixtureSAM3Tracker:
    """Drop-in for SAM3Runtime in tests. Constructed with a per-frame fixture
    of detections. ground_on_frame returns the fixture's initial detections;
    propagate yields per-frame results from the fixture.

    Does not load any model; safe to use without CUDA, without sam3/ extras."""
```

Fixtures are Phase 3's primary test surface. The CI pipeline runs the entire integration test suite using only fixtures; the real-SAM3 smoke test is gated behind `MIMICANNO_RUN_SAM3_SMOKE=1` and CUDA, mirroring Phase 2's `MIMICANNO_RUN_VLM_SMOKE=1` pattern.

## 3. `tracks.json` schema

### 3.1 Full example

```jsonc
{
  "schema_version": "0.1.0",
  "episode_id": "episode_000",
  "fps": 30.0,
  "n_frames": 1275,
  "image_size": { "width": 1280, "height": 720 },
  "track_stride_frames": 10,

  "tracking_plan": {
    "task_text": "pick up the red block and place it in bin A",
    "object_prompts":  ["red block"],
    "target_prompts":  ["bin A"],
    "tool_prompts":    ["gripper"],
    "failed_prompts":  []
  },

  "tracks": [
    {
      "track_id": "obj:object:red_block:0",
      "role":     "object",
      "prompt":   "red block",
      "slug":     "red_block",
      "index":    0,
      "primary":  true,
      "samples": [
        { "frame":   0, "time_sec": 0.000000, "bbox": [0.412, 0.530, 0.085, 0.072], "score": 0.91 },
        { "frame":  10, "time_sec": 0.333333, "bbox": [0.418, 0.531, 0.084, 0.073], "score": 0.93 },
        { "frame":  20, "time_sec": 0.666667, "bbox": [0.430, 0.527, 0.084, 0.071], "score": 0.88 }
      ],
      "gap_events": [
        { "from_frame": 320, "to_frame": 360, "reason": "sam3_lost" },
        { "from_frame": 370, "to_frame": 370, "reason": "sam3_reacquired" }
      ]
    },
    {
      "track_id": "obj:target:bin_a:0",
      "role":     "target",
      "prompt":   "bin A",
      "slug":     "bin_a",
      "index":    0,
      "primary":  true,
      "samples":  [ /* ... */ ],
      "gap_events": []
    },
    {
      "track_id": "obj:tool:gripper:0",
      "role":     "tool",
      "prompt":   "gripper",
      "slug":     "gripper",
      "index":    0,
      "primary":  true,
      "samples":  [ /* ... */ ],
      "gap_events": []
    }
  ],

  "stats": {
    "n_tracks": 3,
    "n_samples_total": 384,
    "mean_track_score": 0.87,
    "tracking_wall_time_sec": 38.4
  }
}
```

### 3.2 Field contracts

| Field | Required | Type | Rule |
|---|:---:|---|---|
| `schema_version` | ✓ | semver string | `"0.1.0"` for first release; major bump on breaking change |
| `episode_id` | ✓ | string | Equals `manifest.episode_id` |
| `fps` | ✓ | float > 0 | Equals `manifest.fps` |
| `n_frames` | ✓ | int ≥ 1 | Equals video frame count |
| `image_size.width` | ✓ | int > 0 | Pixels |
| `image_size.height` | ✓ | int > 0 | Pixels |
| `track_stride_frames` | ✓ | int ≥ 1 | Effective stride used in propagation |
| `tracking_plan.task_text` | ✓ | string | Original task text (debug / reproducibility) |
| `tracking_plan.object_prompts` | ✓ | `list[str]` | Gemma planner output, may be empty (see §4.4) |
| `tracking_plan.target_prompts` | ✓ | `list[str]` | Gemma planner output |
| `tracking_plan.tool_prompts` | ✓ | `list[str]` | Gemma planner output |
| `tracking_plan.failed_prompts` | ✓ | `list[str]` | Step-B-failed prompts; subset of `object/target/tool_prompts` |
| `tracks` | ✓ | array of objects | 0+ tracks; `failed_prompts` are not present here |
| `tracks[].track_id` | ✓ | string | Form `obj:role:slug:index`; unique within the file |
| `tracks[].role` | ✓ | enum | `"object" | "target" | "tool"` |
| `tracks[].prompt` | ✓ | string | Original prompt from `tracking_plan` |
| `tracks[].slug` | ✓ | string | `slugify(prompt)`; consistent with `track_id` |
| `tracks[].index` | ✓ | int ≥ 0 | Per-`(role, slug)` 0-based |
| `tracks[].primary` | ✓ | bool | At most one true per role; corresponds to `*_prompts[0]` index 0 |
| `tracks[].samples` | ✓ | array | Strict frame ascending; no duplicate frames |
| `tracks[].samples[].frame` | ✓ | int | `[0, n_frames)` |
| `tracks[].samples[].time_sec` | ✓ | float | `frame / fps`, 6 sig fig |
| `tracks[].samples[].bbox` | ✓ | `[x, y, w, h]` floats | All in `[0, 1]`; `w > 0`; `h > 0`; `x + w ≤ 1`; `y + h ≤ 1` |
| `tracks[].samples[].score` | ✓ | float | `[0, 1]` |
| `tracks[].gap_events` | ✓ | array | Frame ascending; non-overlapping |
| `tracks[].gap_events[].from_frame` | ✓ | int | `[0, n_frames)`; `≤ to_frame` |
| `tracks[].gap_events[].to_frame` | ✓ | int | `[0, n_frames)` |
| `tracks[].gap_events[].reason` | ✓ | enum | `"sam3_lost" | "sam3_low_conf" | "sam3_reacquired"` |
| `stats.n_tracks` | ✓ | int | Equals `len(tracks)` |
| `stats.n_samples_total` | ✓ | int | Sum of `len(t.samples)` over `tracks` |
| `stats.mean_track_score` | ✓ | float | NaN if `n_samples_total == 0`; serialize as `null` |
| `stats.tracking_wall_time_sec` | ✓ | float ≥ 0 | Wall clock for the propagation stage |

`stats` is observability — schema validation rejects only missing fields, not value drift.

### 3.3 Cross-artifact integrity (read-time checks)

- `tracks.episode_id` / `tracks.fps` / `tracks.n_frames` must equal `manifest.episode_id` / `manifest.fps` / `manifest.n_frames`. Mismatch → reader raises `ArtifactIntegrityError`.
- Every `track_id` referenced in any `annotation.json` segment's `object_track_ids` must exist in `tracks.tracks[].track_id`. Mismatch → reader raises.
- Boundary-detector-internal cross-checks (e.g. all candidate `frame`s within `[0, n_frames)`) are unchanged from Phase 1.

### 3.4 Shape under degrade

Three cases:

| Case | `tracks.json` written? | `tracking_plan` content | `tracks` content |
|---|:---:|---|---|
| Phase 3 success (no degrade) | yes | full | one entry per (role, prompt) - failed_prompts |
| Whole-run degrade — `gemma_no_object_prompts` (§7.2) | **no** | n/a | n/a |
| Whole-run degrade — `sam3_no_initial_detection` (§7.2) | **no** | n/a | n/a |
| Whole-run degrade — `sam3_init_failed` (§7.2) | **no** | n/a | n/a |
| Per-segment fallback (§6) | yes | full | unchanged from success |

The whole-run degrade path produces a Phase 2-equivalent run: no `tracks.json`, `manifest.pipeline_status.object_state_available = false`, `degraded_from_phase = 3`, `degrade_reason` populated. Per-segment fallback does not affect `tracks.json`; it is recorded only on the affected `SubtaskSegment`.

### 3.5 File output

- Path: `runs/<canonical_name>/tracks.json`
- Atomic write via existing `mimicanno.io.write_json_atomic`
- Listed in `manifest.artifacts[]` as `{"kind": "tracks", "url": "tracks.json", "schema_version": "0.1.0", "compat": ["0.1"]}`

## 4. Boundary score Phase 3 changes

Parent spec §5.3 announced that Phase 3 adds `gripper_object_distance_threshold_crossing` and `object_motion_start_stop` to the integrated weighted score and rebalances weights. This section pins the formulae and defaults.

### 4.1 Two new boundary sources

#### 4.1.1 `gripper_object_distance_threshold_crossing`

- **Input:** `ObjectSignals.gripper_object_distance[object_track_id]` for each `object_track_id`.
- **Per-frame signal:** `d(t) = gripper_object_distance[object_track_id][t]`. NaN frames are skipped (no event emitted).
- **Crossing detection:** at each frame `t` where both `d(t-1)` and `d(t)` are non-NaN, emit a candidate iff `sign(d(t-1) - threshold) != sign(d(t) - threshold)` where `threshold = config.tracking.gripper_object_distance_threshold` (default `0.05` of image diagonal).
- **`source_score`:** `clip(|d(t + w) - d(t - w)| / threshold, 0, 1)` where `w = max(1, round(0.10 * fps))`. The window is clipped to `[0, n_frames)`; **if either side of the windowed delta is undefined (i.e. `t - w < 0` or `t + w >= n_frames`), do NOT emit the event** (the windowed-delta is undefined; falling back to a sentinel score risks polluting boundary candidates at the episode edges where the bracketing already creates implicit cuts).
- **Multi-object aggregation:** events from different `(object_track_id, gripper_tool_track_id)` pairs at the same effective `time` are merged at the integrated-score stage via §5.3 max rule (parent spec).
- **Source identifier in `boundaries.json`:** `"gripper_object_distance_threshold_crossing"`

#### 4.1.2 `object_motion_start_stop`

- **Input:** `ObjectSignals.object_speed[object_track_id]` for each `object_track_id`.
- **Per-frame signal:** `v(t) = object_speed[object_track_id][t]`. NaN frames skip.
- **Sustained transition detection:** maintain a sliding `window = round(config.tracking.object_motion_min_sec * fps)` (default `object_motion_min_sec = 0.10`).
  - **Start event** at frame `t` iff `v(t - window) … v(t - 1)` are all `< threshold` and `v(t) … v(t + window - 1)` are all `≥ threshold`.
  - **Stop event** at frame `t` iff the inverse transition holds.
  - `threshold = config.tracking.object_motion_threshold` (default `0.02` image-diag/sec).
- **`source_score`:** `clip(max(mean(v[t-window:t]), mean(v[t:t+window])) / threshold, 0, 1)`.
- **Multi-object aggregation:** as above.
- **Source identifier in `boundaries.json`:** `"object_motion_start_stop"`

### 4.2 Phase 3 weight rebalance

Default weights (sum = 1.00):

| Source | Phase 1 weight | Phase 3 weight |
|---|---:|---:|
| `gripper_transition` | 0.50 | **0.45** |
| `gripper_object_distance_threshold_crossing` | — | **0.25** |
| `eef_velocity_valley` | 0.25 | **0.15** |
| `object_motion_start_stop` | — | **0.10** |
| `eef_acceleration_peak` | 0.15 | **0.03** |
| `action_norm_change` | 0.10 | **0.02** |
| **Sum** | **1.00** | **1.00** |

`score_threshold` remains `0.30`. `merge_window_sec` remains `0.10`.

These weights are encoded as `Phase3BoundaryWeights` in `config.py` and selected when `target_phase == 3`. Phase 1/2 continue to use the existing `Phase1BoundaryWeights` (untouched). All weights are user-overridable via `--boundary-config <yaml>` (parent spec §11 behavior, unchanged).

### 4.3 Default-policy intent (Phase 3)

Per parent spec §5.3 wording (gripper-biased precision) for Phase 3:

- **Single-source promote:** `gripper_transition = 0.45 > 0.30` → still promotes alone (matches Phase 1 character). No other single source promotes alone.
- **Two-source promote:** `gripper_transition + gripper_object_distance_threshold_crossing = 0.70` (canonical grasp/release event); `gripper_object_distance_threshold_crossing + eef_velocity_valley = 0.40`; `gripper_object_distance_threshold_crossing + object_motion_start_stop = 0.35` (object enters/leaves gripper region, both signals fire).
- **Object-only paths do NOT promote:** `object_motion_start_stop + eef_velocity_valley = 0.25`, `object_motion_start_stop + eef_acceleration_peak + action_norm_change = 0.15`. Intent: object signals augment gripper signals; purely visual handoffs without gripper involvement are out of Phase 3 boundary scope (Phase 4-5 manual edit).

This intent is documented in `Phase3BoundaryWeights` docstring and replayable via the integration test `test_phase3_weights_intent.py`.

### 4.4 `disabled_sources` rules

The `pipeline_params.boundary.disabled_sources` list (parent spec §5.3, §11) gains Phase 3 entries:

| Condition | Source disabled |
|---|---|
| `ObjectSignals.gripper_tool_track_id is None` (no gripper tool track) | `gripper_object_distance_threshold_crossing` |
| `tracks` contains no `role="object"` track | `gripper_object_distance_threshold_crossing` and `object_motion_start_stop` |
| Both Phase 1 conditions for `eef_*` (parent spec §11) | `eef_velocity_valley`, `eef_acceleration_peak` (unchanged from Phase 1) |
| Both Phase 1 conditions for `action_norm_change` (parent spec §11) | `action_norm_change` (unchanged) |

A disabled source contributes 0 to the integrated score; weights are NOT renormalized (parent spec §5.3 invariant). `disabled_sources` ends up serialized to `manifest.pipeline_params.boundary.disabled_sources` exactly as in Phase 1/2.

### 4.5 Boundary candidates with object sources

Per parent spec §5.4 `boundaries.json` schema, new candidates look like:

```jsonc
{
  "id": "b_007",
  "frame": 312,
  "time": 10.4,
  "sources": ["gripper_transition", "gripper_object_distance_threshold_crossing"],
  "scores": {
    "gripper_transition": 0.92,
    "gripper_object_distance_threshold_crossing": 0.71
  },
  "score": 0.592
}
```

Schema is unchanged from parent spec §5.4 (sources is `list[str]` open-extension).

## 5. `ObjectStateSummary` and prompt extension

### 5.1 Dataclass

```python
@dataclass(slots=True)
class ObjectStateSummary:
    """Per-segment object/target/tool state derived from SAM3 tracks.
    Used as the Phase 3 add-on to ClipFeatures and the VLM prompt."""

    object_prompts: list[str]                       # visible >= visibility_threshold of seg
    target_prompts: list[str]
    tool_prompts:   list[str]                       # may be []

    gripper_object_distance_at_start: float | None  # primary pair, normalized image diag
    gripper_object_distance_at_end:   float | None
    gripper_object_distance_min:      float | None

    primary_object_displacement: float | None       # normalized image diag
    primary_object_max_speed:    float | None       # normalized image diag / sec

    primary_object_at_target_at_end: bool | None    # bbox-IoU(obj_0, tgt_0) at last frame > 0.05
```

### 5.2 `compute_object_state_summary` algorithm

```python
def compute_object_state_summary(
    tracks: list[Track],
    *,
    segment_start_frame: int,
    segment_end_frame: int,        # inclusive
    object_signals: ObjectSignals,
    config: TrackingConfig,
) -> ObjectStateSummary | None:
    ...
```

Algorithm:

1. **Visibility filter.** For each track, count frames in `[segment_start_frame, segment_end_frame]` that lie outside any `gap_events`. If this count divided by segment length `>= config.visibility_threshold` (default `0.5`), include the prompt in the corresponding `*_prompts` list.
2. **Primary tracks.** Identify `primary_object_track = next(t for t in tracks if t.role == "object" and t.primary)`, `primary_target_track`, `gripper_tool_track` analogously.
3. **No primary object → return None.** If `primary_object_track` is None or `primary_object_track.prompt` is not in the visibility-filtered `object_prompts` list, return `None`. The caller treats this as a per-segment fallback trigger (§6).
4. **Gripper-object distances.** From `object_signals.gripper_object_distance[primary_object_track.track_id]`:
   - `gripper_object_distance_at_start` = first non-NaN value in segment (or None if all NaN or no gripper track).
   - `gripper_object_distance_at_end` = last non-NaN value in segment (or None).
   - `gripper_object_distance_min` = min of non-NaN values in segment (or None).
5. **Primary object motion.** From `object_signals.object_speed[primary_object_track.track_id]` over segment (NaN-skipped):
   - `primary_object_max_speed` = max (or None if all NaN).
   - `primary_object_displacement` = sum of `|center_diff(t)|` for adjacent non-gap frame pairs in segment, normalized by image-diag (or None if all NaN).
6. **Object-at-target proxy.**
   - Define `bbox_at_frame(track, t)`: linearly interpolate `(x, y, w, h)` between the two bracketing samples of `track` whose frames sandwich `t`, **iff `t` is not inside any `gap_event` for that track and at least one sample exists at frame `<= t` and one at frame `>= t`** (no extrapolation past the first or last sample). Returns `None` otherwise.
   - Compute `obj_bbox = bbox_at_frame(primary_object_track, segment_end_frame)` and `tgt_bbox = bbox_at_frame(primary_target_track, segment_end_frame)`. **Both are evaluated at the same exact frame `segment_end_frame`** — IoU between bboxes from different frames is geometrically meaningless and is explicitly rejected.
   - If `obj_bbox is None` or `tgt_bbox is None` or `primary_target_track is None`: `primary_object_at_target_at_end = None`.
   - Otherwise: `primary_object_at_target_at_end = obj_bbox.iou(tgt_bbox) > 0.05`.

### 5.3 Primary pair convention

- `primary` is set on `*_prompts[0]` in §2.4 step 7 (the first prompt of each role from `TrackingPlan`).
- `compute_object_state_summary` only uses the primary tracks. Non-primary tracks (e.g. multiple "red block" instances) influence the visibility-based `*_prompts` list but not the scalar fields.
- Roles with no track: corresponding `*_prompts` list is empty.

### 5.4 Prompt extension (Phase 3 mode)

`build_prompt(request, attempt, last_reject_reason)` accepts `request["object_state_summary"]: ObjectStateSummary | None` (added to `VLMRequest` typed dict). Behavior:

- **Phase 2 callsite** (`object_state_summary is None`): prompt body is **byte-identical** to Phase 2's. No new sections. Snapshot tests pinning Phase 2 prompts continue to pass.
- **Phase 3 callsite** (`object_state_summary is not None`): two new SYSTEM sub-sections appear after the "Robot-state summary" block, before the USER block:

```
Tracked entities in this scene:
  objects: ["red block"]
  targets: ["bin A"]
  tools:   ["gripper"]

Object-state summary for this segment:
  gripper_object_distance_at_start: 0.42
  gripper_object_distance_min:      0.03
  gripper_object_distance_at_end:   0.41
  primary_object_displacement:      0.18
  primary_object_max_speed:         0.32
  primary_object_at_target_at_end:  true
  (Prefer one of the listed objects/targets in the "object" / "target" output fields.)
```

Formatting:

- Float values: `{:.6g}`. `None` values render as `null`. Booleans render as `true` / `false`.
- Empty `*_prompts` list renders as `[]`.
- The "(Prefer …)" advisory line is always present in Phase 3 mode (even when lists are empty — VLM is informed that none were tracked).
- When `last_reject_reason` triggers a retry amendment, the retry block is appended after both new sub-sections (existing Phase 2 amendment placement unchanged).

### 5.5 `label_source` switching

Per-segment provenance:

- Segment where Phase 3 labeling succeeded with `object_state_summary is not None` → `label_source = "vlm_with_object_state"`, `object_state_unavailable = False`, `object_track_ids = [<all visibility-filtered track_ids covering this segment>]`.
- Segment where per-segment fallback (§6) ran → `label_source = "vlm_robot_state_only"`, `object_state_unavailable = True`, `object_track_ids = []`.
- Whole-run degrade: every segment is labeled by Phase 2 path; same as a Phase 2 run except `notes` records the degrade reason.

`object_track_ids` is the visibility-filtered set: track_ids whose non-gap samples cover `>= visibility_threshold * segment_length` frames in the segment. This matches the `*_prompts` filter in §5.2 step 1 — a segment lists every track that contributed to its prompt.

### 5.6 Soft constraint on `object` / `target` fields

- The advisory "(Prefer one of the listed …)" tells the VLM which strings are preferred but does not constrain JSON validation.
- Existing Phase 2 validation (short noun, ≤ 64 chars, or null) applies unchanged.
- No new `reject_reason` ("object_not_in_tracked") is added. Rationale: a hard constraint would inflate `unknown` rates on tracking-degraded segments and complicate Phase 2 fallback. Soft is the right balance for a provisional labeler.

## 6. Per-segment fallback

### 6.1 Trigger

A segment falls back to Phase 2 path iff `compute_object_state_summary(...)` returns `None`, which happens when:
- The primary object track does not exist, OR
- The primary object track's visibility in the segment is below `config.visibility_threshold`.

### 6.2 Behavior

For a fallback segment:

1. Build `VLMRequest` with `object_state_summary = None` (Phase 2 mode).
2. Call the same `vlm.label_segment(...)` (Phase 2's labeler), but flagged as fallback in `LabelAttempt.notes`.
3. Set per-segment fields:
   - `label_source = "vlm_robot_state_only"`
   - `object_state_unavailable = True`
   - `object_track_ids = []`
   - `LabelAttempt.notes` includes `"phase3_per_segment_fallback"`.

### 6.3 Per-segment vs run-level provenance

- `manifest.pipeline_status.object_state_available` is **true** for any Phase 3 run that did not take the whole-run degrade path (i.e. `tracks.json` was written), regardless of how many segments fell back per-segment.
- `manifest.pipeline_status.object_state_segment_coverage` (new field, see §1.3) is the fraction `n_segments_with_object_state / n_segments_total`. Phase 1/2 readers default this to `1.0` (parent spec §6.6 compat allowance).
- The viewer can use `object_state_segment_coverage < 1.0` to render a softer "partial coverage" indicator (Phase 5 work; not required for Phase 3 to ship).

### 6.4 No new degrade trigger

Per-segment fallback is **not a degrade**. The run is considered successful. The intent is that a 30-segment episode where 1 segment lost its primary object track for 60% of its frames should still be a Phase 3 run (with one fallback segment), not a whole-run Phase 2 retreat.

## 7. Pipeline orchestrator (`target_phase == 3`)

### 7.1 Stage sequence

```python
def annotate_episode_phase3(inputs, config):
    # Stage 0: Phase 1/2 preflight extended with SAM3 checkpoint resolution
    preflight_phase3(inputs, config)

    # Stage 1a: signals (Phase 1, unchanged)
    robot_signals = compute_robot_signals(inputs)

    # Stage 1b: tracking
    initial_frame = extract_initial_frame(inputs.video_path)   # frame 0; retry @5%
    vlm = LocalGemmaVLMLabeler.load(config.vlm)                # shared Gemma instance
    planner = LocalGemmaTrackingPlanner(vlm.shared_handle())
    plan = planner.plan(
        task_text=inputs.task_text,
        initial_frame=initial_frame,
        allowed_labels=inputs.allowed_labels,
    )

    if not plan.object_prompts or all(p in plan.failed_prompts for p in plan.object_prompts):
        # Whole-run degrade per §7.2
        reason = (
            "gemma_no_object_prompts" if not plan.object_prompts
            else "sam3_no_initial_detection"
        )
        return _degrade_to_phase2(inputs, config, vlm, robot_signals, reason)

    try:
        sam3_runtime = SAM3Runtime.load(checkpoint=config.tracking.sam3_checkpoint)
    except SAM3InitFailedError as e:
        return _degrade_to_phase2(inputs, config, vlm, robot_signals, "sam3_init_failed", cause=e)

    try:
        tracks = Propagator().run(
            runtime=sam3_runtime,
            plan=plan,
            video_path=inputs.video_path,
            fps=inputs.fps,
            n_frames=inputs.n_frames,
            stride=config.tracking.effective_stride(inputs.fps),
            config=config.tracking,
        )
    finally:
        sam3_runtime.close()                   # free GPU before Stage 3

    object_signals = compute_object_signals(
        tracks, fps=inputs.fps, n_frames=inputs.n_frames,
        image_aspect_ratio=inputs.image_size.width / inputs.image_size.height,
    )

    # Stage 2: integrated boundary score with 6 sources
    detector = Phase3BoundaryDetector(config.boundary)
    boundaries = detector.detect(robot_signals, object_signals, tracks)
    segments = bracket_segments(boundaries, fps=inputs.fps, duration_sec=inputs.duration_sec)

    # Stage 3: Phase 3 labeling
    annotation, attempts = apply_phase3_labeling(
        segments=segments,
        video=inputs.video,
        robot_state=inputs.robot_state,
        tracks=tracks,
        object_signals=object_signals,
        vlm=vlm,
        config=config,
    )

    # Publish
    manifest = build_manifest_phase3(
        inputs, config, model_versions={"vlm": vlm.model_id, "sam3": config.tracking.sam3_model_id},
        pipeline_status=PipelineStatus(
            object_state_available=True,
            object_state_segment_coverage=_coverage(annotation),
            degraded_from_phase=None,
            degrade_reason=None,
        ),
    )
    publish_run(
        canonical_name=compute_canonical_name(config, inputs),
        artifacts=[
            ("video.mp4",      inputs.video_path),
            ("signals.json",   build_signals_json(robot_signals, object_signals)),
            ("boundaries.json", boundaries),
            ("annotation.json", annotation),
            ("tracks.json",    build_tracks_json(tracks, plan, inputs)),
            ("manifest.json",  manifest),
        ],
    )
```

### 7.2 Whole-run degrade trigger and behavior

`_degrade_to_phase2(...)`:
- Runs Phase 2's existing `compute_robot_state_signals → bracket_segments → apply_phase2_labeling` against the same inputs (no SAM3 calls; no `tracks.json`).
- Stamps every segment with `label_source = "vlm_robot_state_only"`, `object_state_unavailable = True`, `object_track_ids = []`.
- Sets `manifest.pipeline_status`:
  - `object_state_available = False`
  - `object_state_segment_coverage = 0.0`
  - `degraded_from_phase = 3`
  - `degrade_reason ∈ {"gemma_no_object_prompts", "sam3_no_initial_detection", "sam3_init_failed"}`
- Adds a `notes` entry to `annotation.json` mirroring the same string (parent spec §9.4 wording).
- The run is **published successfully** to its Phase 3 canonical directory (`target_phase=3` ∈ `config_hash`). It is not a Phase 2 run despite using the Phase 2 labeling path: hashes differ from a literal Phase 2 invocation.

### 7.3 Resource handoff

- `LocalGemmaVLMLabeler` and `LocalGemmaTrackingPlanner` share one in-memory Gemma model. `vlm.shared_handle()` returns a thin reference; `LocalGemmaTrackingPlanner` holds it for the duration of `plan(...)` and releases.
- `SAM3Runtime.close()` is called immediately after `Propagator.run` returns, before Stage 3. This is a hard contract: Stage 3 must not depend on SAM3 still being loaded. Tests assert this via a `with pytest.raises(RuntimeError)` against using the closed runtime.
- Initial-frame extraction is done synchronously in the orchestrator (not inside `planner`). Failure raises immediately per parent spec §11 (retry @5%, then abort).

### 7.4 Configuration plumbing

`AnnotationConfig` gains:

```python
@dataclass(slots=True, frozen=True)
class TrackingConfig:
    sam3_model_id: str = "facebook/sam3.1"               # informational; encoded in config_hash
    sam3_checkpoint: Path | None = None                  # required for Phase 3; CLI validates
    track_stride_frames: int | None = None               # None -> max(1, round(fps / 3))
    min_track_score: float = 0.30
    max_gap_frames: int | None = None                    # None -> round(fps * 1.0)
    reacquisition_iou_threshold: float = 0.30
    visibility_threshold: float = 0.5                    # for ObjectStateSummary
    gripper_object_distance_threshold: float = 0.05
    object_motion_threshold: float = 0.02                # image diag / sec
    object_motion_min_sec: float = 0.10
    image_aspect_ratio_default: float = 16.0 / 9.0       # used when video lacks SAR

    def effective_stride(self, fps: float) -> int:
        return self.track_stride_frames if self.track_stride_frames else max(1, round(fps / 3))


@dataclass(slots=True, frozen=True)
class Phase3BoundaryWeights:
    gripper_transition: float = 0.45
    gripper_object_distance_threshold_crossing: float = 0.25
    eef_velocity_valley: float = 0.15
    object_motion_start_stop: float = 0.10
    eef_acceleration_peak: float = 0.03
    action_norm_change: float = 0.02


@dataclass(slots=True, frozen=True)
class AnnotationConfig:
    # … existing fields …
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    # boundary.weights becomes union: Phase 1/2 use Phase1BoundaryWeights;
    # Phase 3 uses Phase3BoundaryWeights — selected by target_phase
```

`AnnotationConfig.tracking` enters `config_hash` via the existing recursive serialization (no new hashing logic). Phase 1/2 invocations leave `tracking` at default but `target_phase=1|2` keeps the Phase 1 weights and ignores the new sources, so `tracks.json`-like artifacts never form.

## 8. Errors and degrade table (Phase 3 additions)

Extends parent spec §11. Phase 3-specific rows:

| Failure | Detection | Action |
|---|---|---|
| `--target-phase 3` without `--vlm-model` or unresolvable SAM3 checkpoint | CLI preflight | Abort with `MissingDependencyError`; non-zero exit |
| sam3 extras not installed but `--target-phase 3` | `import sam3` raises `ModuleNotFoundError` | Abort with hint to install `pip install '.[sam3]'`; exit 2 |
| Initial frame extraction fails at frame 0 and 5% (parent spec §11) | ffmpeg | Abort (already in parent table) |
| Gemma planner JSON parse fail × 3 | Step A retries exhausted | `TrackingPlan(object_prompts=[], …)`; whole-run degrade `gemma_no_object_prompts` |
| Gemma planner returns valid JSON but `objects: []` | Step A semantic check | Whole-run degrade `gemma_no_object_prompts` |
| Step B: SAM3 returns no detections for any object_prompt | `ground_on_frame` returns `[]` for all | Whole-run degrade `sam3_no_initial_detection` |
| Step B: SAM3 returns detections for some but not all object_prompts | partial | Continue with detected prompts; failed ones go to `tracking_plan.failed_prompts`. No degrade. |
| `SAM3Runtime.load(...)` raises during Stage 1b | constructor exception (CUDA OOM, missing checkpoint, …) | Whole-run degrade `sam3_init_failed`. The chained `cause` is recorded in the Phase 2 `notes` entry (NOT to stderr — degrade exits 0). |
| Propagation runtime error mid-episode | `propagate(...)` exception | Abort with non-zero exit. Stderr JSON has `error_code="sam3_runtime_failed"` and `frame_index` at which it occurred. The orchestrator MUST `rm -rf` the in-flight `*.tmp.<pid>/` directory synchronously before exit (best effort; failures logged but ignored). The parent §4.4 / §6.5 stale-tmp scavenger remains the safety net for crash-during-rm cases. |
| Per-segment: `compute_object_state_summary` returns None | `primary_object_track` invisible / missing in segment | Per-segment fallback (§6); no abort, no degrade |
| `tracks.json` cross-artifact mismatch on read | Reader integrity check | Reader raises `ArtifactIntegrityError` (read path; not produced at write time by a sound implementation) |

All non-zero-exit aborts emit a structured stderr JSON identical in shape to Phase 1/2:
```jsonc
{"error_code": "...", "message": "...", "context": {...}, "ts": "<ISO-8601>"}
```

New error codes (defined in `mimicanno.errors`):
- `sam3_init_failed` — degrade reason; **never goes to stderr** (degrade exits 0)
- `sam3_runtime_failed` — abort code; **goes to stderr**, exits non-zero
- `sam3_extras_missing` — abort code; **goes to stderr**, exits non-zero
- `gemma_planner_no_objects` — degrade reason; **never goes to stderr** (degrade exits 0)
- `sam3_initial_detection_failed` — degrade reason; **never goes to stderr** (degrade exits 0)

**Channel assignment is exclusive:** every Phase 3 error code is either a degrade reason (logged to `notes`, exits 0) or an abort code (stderr JSON, non-zero exit). No code uses both channels. The whole-run degrade path (§7.2) writes the chained `cause` from any underlying exception into the `notes` entry text; it does NOT also emit stderr JSON for the same event.

## 9. Configuration hashing

Per parent spec §4.1, `config_hash = sha256(canonical_json(AnnotationConfig + target_phase + model_config))`.

### 9.1 Hash payload gating for Phase 1/2 backward compatibility

**Critical invariant:** the canonical JSON payload that feeds `config_hash` MUST be byte-identical to the Phase 1/2 payload when `target_phase ∈ {1, 2}`. Adding a new field to `AnnotationConfig` or to `BoundaryWeights` and relying on Python's default value to silently disappear from the canonical JSON output **does not work**: dataclass-derived `to_dict()` emits explicitly declared fields regardless of value. Without explicit gating, Phase 1/2 hashes computed against the post-Phase-3-merge code would not match hashes computed against the pre-merge code, invalidating every existing `runs/<canonical_name>/` directory.

**Gating rule:** `AnnotationConfig.to_dict()` (and any nested `*.to_dict()` it composes) accepts an explicit `target_phase: int` argument and emits Phase-3-only fields **iff `target_phase >= 3`**. Specifically:

```python
def to_dict(self, *, target_phase: int) -> dict[str, Any]:
    payload = {
        "boundary": self.boundary.to_dict(target_phase=target_phase),
        # vlm sub-block only when target_phase >= 2 (existing Phase 2 gate)
    }
    if target_phase >= 2:
        payload["vlm"] = self.vlm.to_dict()
    if target_phase >= 3:
        payload["tracking"] = self.tracking.to_dict()
    return payload

# In BoundaryConfig.to_dict:
def to_dict(self, *, target_phase: int) -> dict[str, Any]:
    weights = self.weights.to_dict(target_phase=target_phase)
    # weights.to_dict omits the 2 Phase 3 keys when target_phase < 3
    return {"weights": weights, "thresholds": self.thresholds.to_dict(), ...}
```

`model_config` is similarly gated:

```python
def build_model_config(config, *, target_phase: int) -> dict[str, Any]:
    payload = {
        "vlm_model":       config.vlm.model_id       if target_phase >= 2 else None,
        "vlm_checkpoint":  config.vlm.checkpoint_sha256 if target_phase >= 2 else None,
    }
    if target_phase >= 3:
        payload["sam3_model"]      = config.tracking.sam3_model_id
        payload["sam3_checkpoint"] = _sha256_of_path(config.tracking.sam3_checkpoint)
    return payload
```

Phase 1/2 payloads omit the `sam3_*` keys entirely (NOT serialize them as `null`). The parent spec §4 manifest example showing `"sam3": null` refers to the **manifest** field for downstream observability, NOT the hash payload. The Phase 1/2 manifest will continue to display `model_versions.sam3 = null` for human readability while the hash payload omits the key.

`tracks.json` follows the same omit-when-not-applicable rule for any future field additions.

### 9.2 Canonicalization

Within a payload, key ordering is sorted ascending; floats are formatted with `repr()` (or equivalent that round-trips); `None` values for keys that ARE present in the payload are serialized as JSON `null` (the gate is on key presence, not on `null` rendering).

### 9.3 Hash isolation test

`tests/test_phase3_hash_isolation.py` MUST pin Phase 1 and Phase 2 hash values for one canonical `(AnnotationConfig, episode_inputs)` pair, computed against both pre-Phase-3 and post-Phase-3 code paths. Both code paths must produce the same hash. The test fails if either Phase 1 or Phase 2 hash drifts from its pinned value.

`tracking` config differences (under `target_phase=3`) → different `config_hash` → different `canonical_name` (parent spec §4.1 invariant, preserved).

## 10. Testing strategy

Three layers, mirroring Phase 2:

### 10.1 Unit tests

Per-module unit tests with no external dependencies:

- `tests/object_tracker/test_track_id.py` — `slugify` corner cases, `make_track_id` round trip, parse-by-split.
- `tests/object_tracker/test_bbox.py` — `BBox.iou`, `BBox.center`, validation.
- `tests/object_tracker/test_propagator.py` — gap consolidation, re-acquisition IoU branch, primary marking, deterministic ordering. Driven via `FixtureSAM3Tracker`.
- `tests/object_tracker/test_signals.py` — `compute_object_signals` distance + speed, NaN handling at gaps and episode boundaries, primary track resolution.
- `tests/test_object_state_summary.py` — `compute_object_state_summary` visibility-threshold filter, primary-pair distance extraction, IoU-at-end proxy, None return on missing primary.
- `tests/test_phase3_boundary_detector.py` — new sources fire under crafted signals; weight rebalance produces expected scores; `disabled_sources` rules; `Phase3BoundaryWeights` defaults.
- `tests/test_vlm_prompt_phase3.py` — `build_prompt` byte-equality with Phase 2 when `object_state_summary is None`; snapshot tests for the two new SYSTEM sub-sections; advisory line always present.
- `tests/test_tracks_json_schema.py` — round-trip serialization, schema validation, cross-artifact integrity rule positives and negatives.
- `tests/test_phase3_hash_isolation.py` — Phase 1/2 hashes unchanged after Phase 3 schema additions; Phase 3 hash differs from Phase 1/2 on identical episode inputs.
- `tests/test_phase3_weights_intent.py` — encodes the §4.3 single/two-source promotion truth table.

### 10.2 Integration tests (with fixtures)

Driven by `FixtureTrackingPlanner` + `FixtureSAM3Tracker`. No GPU, no SAM3 weights, no Gemma weights. Each test asserts on the resulting run directory artifacts.

- `tests/integration/test_phase3_smoke.py` — happy-path episode: tracking succeeds, all 6 boundary sources potentially fire, all segments have `object_state_available`. Artifacts: video, signals (with object channels), boundaries, annotation, tracks, manifest.
- `tests/integration/test_phase3_per_segment_fallback.py` — fixture configured so one segment's primary object is in gap. That segment uses Phase 2 path (`vlm_robot_state_only`); other segments use Phase 3 path. `pipeline_status.object_state_segment_coverage < 1.0`; `object_state_available = True`.
- `tests/integration/test_phase3_degrade_gemma_no_objects.py` — `FixtureTrackingPlanner` returns empty plan. Run succeeds with Phase 2 output, `degrade_reason = "gemma_no_object_prompts"`, no `tracks.json` written.
- `tests/integration/test_phase3_degrade_sam3_no_initial.py` — `FixtureSAM3Tracker.ground_on_frame` returns `[]` for all object prompts. Run degrades with `degrade_reason = "sam3_no_initial_detection"`.
- `tests/integration/test_phase3_degrade_sam3_init_failed.py` — `FixtureSAM3Tracker` raises on `load`. Degrades with `sam3_init_failed`.
- `tests/integration/test_phase3_idempotency.py` — same inputs + config produce byte-identical artifacts and identical `config_hash` / `run_hash` / `canonical_name`.
- `tests/integration/test_phase3_distinctness.py` — Phase 1, Phase 2, Phase 3 of the same episode produce three different `canonical_name`s and three different run directories.
- `tests/integration/test_phase3_no_phase12_regression.py` — running Phase 1 and Phase 2 against a curated fixture episode produces byte-identical output as before Phase 3 was merged.
- `tests/integration/test_tracks_json_cross_artifact.py` — corrupted `tracks.episode_id` triggers `ArtifactIntegrityError` on read.

### 10.3 Real-SAM3 smoke (gated)

`tests/test_phase3_real_sam3_smoke.py`, gated by `MIMICANNO_RUN_SAM3_SMOKE=1` and CUDA availability (mirroring Phase 2's `MIMICANNO_RUN_VLM_SMOKE=1` pattern):

- Loads a small fixture episode (existing `lerobot/svla_so100_pickplace` ep0 used in Phase 1 verification).
- Runs end-to-end with real `LocalGemmaVLMLabeler`, real `LocalGemmaTrackingPlanner` (sharing the Gemma instance), real `SAM3Runtime` from a checkpoint at `${MIMICANNO_SAM3_CHECKPOINT}`.
- Asserts: `tracks.json` exists; at least 1 object track has `>= 10` samples; `manifest.pipeline_status.object_state_available is True`; `object_state_segment_coverage >= 0.5`.
- Not part of CI gate. Documented in the writing-plans phase as a manual verification step before milestone commit.

### 10.4 Snapshot tests

- `tests/snapshots/phase2_prompt.txt` — pinned Phase 2 prompt body. Phase 3 must not change this when `object_state_summary is None`.
- `tests/snapshots/phase3_prompt.txt` — pinned Phase 3 prompt body for a canonical `(VLMRequest, ObjectStateSummary)` pair.

## 11. Exit criteria

Phase 3 is complete when:

1. `mimicanno annotate --target-phase 3 --vlm-model <id> --sam3-checkpoint <path> ...` produces a complete run directory with `tracks.json` and `pipeline_status.object_state_available = true` on at least one real episode (parent spec §15.3 #14 satisfied).
2. A synthetic broken episode (or fixture-driven test) triggering each of the three whole-run degrade reasons (`gemma_no_object_prompts`, `sam3_no_initial_detection`, `sam3_init_failed`) produces a Phase 2-equivalent run with `pipeline_status.degraded_from_phase = 3` and the matching `degrade_reason` (parent spec §15.3 #15 satisfied).
3. All Phase 1 and Phase 2 tests pass without modification (no regression).
4. `mypy --strict` clean across `mimicanno/`, including the new `mimicanno.object_tracker` package.
5. `ruff check` clean (parity with Phase 2's accepted-warning baseline).
6. Per-segment fallback (§6) demonstrably works: an integration test with a fixture-induced single-segment gap produces `object_state_segment_coverage < 1.0` while keeping `object_state_available = true`.
7. Gemma loader is shared between `LocalGemmaVLMLabeler` and `LocalGemmaTrackingPlanner` (single in-memory model). Verified by integration test asserting `id(planner.gemma_handle.model) == id(vlm.model)` (or equivalent identity-based check inside the test fixture).
8. SAM3 GPU memory is released before Stage 3. Verified by a unit test that calls `runtime.close()` then asserts `propagate(...)` raises.
9. Phase 1/2 `config_hash` is unchanged by Phase 3 schema additions (test `test_phase3_hash_isolation.py`).
10. Smoke test (gated by `MIMICANNO_RUN_SAM3_SMOKE=1`) passes manually on `lerobot/svla_so100_pickplace` ep0 before milestone commit.

Out-of-scope items remain the same as §0 non-goals; explicit non-completion is acceptable for those.
