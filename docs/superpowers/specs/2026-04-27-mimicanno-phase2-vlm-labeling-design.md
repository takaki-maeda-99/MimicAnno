# MimicAnno Phase 2 — VLM labeling design

Status: **draft**, awaiting review (Codex).
Author: brainstorming session 2026-04-27.
Supersedes: nothing — new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§3 Phase 2 deliverable, §4.1 hashing, §4.3 manifest schema, §6.1–§6.4 SubtaskSegment / confidence, §8.1–§8.4 allowed-labels enforcement, §11 error handling, §12 package structure, §15.2 Phase 2 exit criteria).
Sibling: [`2026-04-26-mimicanno-plan2-viewer-design.md`](./2026-04-26-mimicanno-plan2-viewer-design.md) (Plan 2 viewer; Phase 2 changes are purely semantic — see §1.3 — and require no viewer-side version-handling work).

## Reviewer context

(For reviewers unfamiliar with the parent spec — skip if you've already read it.)

### What is MimicAnno?

MimicAnno is a **robot-episode subtask annotation tool**. Given a robot manipulation episode (video + parquet of action/proprio time series + a natural-language task instruction such as "pick the red block and place it in the bin"), it produces a **structured annotation** that splits the episode into temporal **segments**, each tagged with one of a fixed set of subtask labels (`approach_object`, `grasp_object`, `lift_object`, `move_to_target`, …). The output is consumed downstream by MimicRec (a separate tool for VLA training / replay / evaluation), where the segment labels become supervision signals or replay markers.

MimicAnno is an **independent Python package** (`mimicanno`), not coupled to any particular VLA model or training framework. Its only persistent contract with downstream consumers is a versioned **run directory** on disk (`runs/<canonical_name>/{manifest.json, annotation.json, boundaries.json, signals.json, video.mp4}`) and a Plan 2 React/Vite read-only viewer that renders those artifacts for human inspection.

### How the work is staged

The full pipeline is split into 5 phases — each phase produces a runnable, testable artifact, and Phase N+1 is allowed to *change* (not just add) Phase N's contract under explicit schema versioning:

```
Phase 1: signals-based boundary detection + read-only viewer        ← SHIPPED
Phase 2: provisional VLM labeling (no object-tracking)              ← THIS SPEC
Phase 3: SAM3 object tracking + object-aware boundaries + relabel
Phase 4: temporal smoothing / Viterbi
Phase 5: human-edit UI + export to MimicRec + evaluation harness
```

Phase 1 is in `main` (commit `3312547`) — the CLI detects segment boundaries from gripper / EEF / action signals and emits one `phase="unlabeled"` segment per bracketed clip; the viewer renders video + waveforms + boundary markers. Phase 1 produced no semantic labels — every segment is `"unlabeled"`.

### What Phase 2 (this spec) does

Phase 2 replaces every `"unlabeled"` segment with **one of the allowed labels** (or the reserved `"unknown"` if labeling fails) by calling a **VLM** (vision-language model) with `task_text + keyframes + a robot-state summary` per segment. SAM3-based object tracking is **not yet** in scope (that's Phase 3); Phase 2 deliberately works without object identity.

Phase 2's deliverable is **the contract** — the VLM-call protocol, the JSON output schema, the allowed-label enforcement rule, the retry / fallback / degrade contract — *not* the labeling quality. Quality is a Phase 3+ concern. The chosen VLM (a Gemma 4-family multimodal instruction-tuned model) is treated as a pluggable adapter; the specific model identifier is configuration, not contract, and is pinned during the implementation-plan phase that follows this spec.

If you're a reviewer evaluating this spec, the question is: **could a competent engineering team take this document and produce an implementation that (a) satisfies parent-spec exit criteria §15.2 #12 and #13, (b) does not violate the parent-spec invariants on hashing / atomicity / schema versioning / error idiom, and (c) leaves Phase 3+ work unobstructed?**

## 0. Scope and intent

This spec covers **Phase 2**: the **provisional VLM labeling** stage that converts every Phase 1 `unlabeled` segment into one of the allowed labels (or the reserved `"unknown"`), without object-state tracking (SAM3 enters in Phase 3).

Phase 2's purpose, from parent spec §3, is to **lock the VLM JSON schema and allowed-label enforcement** — not to evaluate VLM intelligence. The label quality is a Phase 3+ concern; Phase 2 is the contract, and the contract must survive model swaps.

In scope:

- Single-CLI integration: `mimicanno annotate --target-phase 2 --vlm-model <id> ...` extends the existing entry point.
- Pluggable `VLMLabeler` protocol with two implementations: `FixtureVLMLabeler` (test/CI) and `LocalGemmaVLMLabeler` (default real impl; concrete `model_id` deferred to writing-plans).
- Per-segment, single-call VLM labeling with `K=4` keyframes + 5-scalar robot-state summary + episode-level context.
- Validation, retry (max 3), segment-level fallback to `phase="unknown"`, and run-level degrade triggers/reasons.
- No `schema_version` bumps. Phase 2 only starts populating fields already declared in the Phase 1 schemas; the existing Plan 2 viewer needs no version-handling changes (per-field justification in §1.3).
- Test strategy across 3 layers (unit / integration with `FixtureVLMLabeler` / gated real-VLM smoke).

Non-goals:

- Concrete `vlm_model` HF model_id pinning. The default real adapter targets "Gemma 4 family multimodal IT" but the specific model_id is configuration, not contract; pinned in the writing-plans phase that follows this spec.
- VLM accuracy evaluation, calibration, prompt iteration past validation correctness, multi-frame strategy beyond uniform-K. These are Phase 3+ work.
- Reusing `vla-gemma-4` backbone weights for Phase 2 labeling. The current vla-gemma-4 architecture (Gemma 4 E2B + DINO+SigLIP + SoftPromptLibrary + ActionHead) is purpose-built for action prediction and would require a separate text-generation path; revisit as Phase 5 consolidation work, not Phase 2.
- Whole-episode batched VLM calls. Per-segment, 1 call per segment. Cross-segment continuity is Phase 4 smoothing's job.
- Multi-modal calibration (log-probs, ensembling, chain-of-thought). VLM emits `vlm_confidence` self-reported; producer records `attempt_count` separately. Calibration is a Phase 4/5 concern.
- Per-frame independent labeling. Granularity is per-segment; per-frame labels are derived as "frame ∈ segment ⇒ frame.label = segment.phase" (parent spec §6.1 SubtaskSegment span semantics).
- New viewer features. Plan 2 viewer already renders `pipeline_status` banner + `label_source` field via existing chooser-banner code path; Phase 2 surfaces in the existing UI without code changes.
- VLA / MimicRec downstream consumer changes. The annotation.json schema bump is MINOR (additive); consumers that read `phase` and ignore unknown fields keep working.

## 1. Architecture

### 1.1 Phase 2 in the pipeline

Phase 2 is a **purely additive** stage on top of the existing Phase 1 pipeline. The CLI dispatches by `target_phase`:

```
mimicanno annotate --target-phase 2 --vlm-model <id> ...
  │
  ├─ inputs validated (video, parquet, task_text, robot_adapter, labels)
  ├─ AnnotationConfig assembled (boundary + vlm sub-block)
  ├─ run_hash computed
  │     - target_phase=2 ∈ config_hash → distinct from any Phase 1 run_hash
  │     - model_config.vlm_model included → distinct per VLM choice
  │
  ├─ canonical_name resolved
  │
  ├─ [Phase 1 existing] BoundaryDetector → cuts → bracketing → unlabeled segments[N]
  │
  ├─ [Phase 2 new] vlm_labeler.label_run(segments, signals, video, vlm_config)
  │                  → labeled_segments[N], attempts_log[N]
  │
  ├─ AnnotationResult assembled (labeled_segments + notes from attempts_log)
  ├─ Manifest assembled (pipeline_phase=2, model_versions.vlm=<id>, pipeline_status)
  │
  ├─ [existing] publish transaction (tmp dir → atomic rename → index upsert)
  │
  └─ exit 0 (success or degrade)
```

Phase 2 **does not** modify Phase 1's boundary detection, bracketing, run-dir layout, hashing, atomicity, locking, or scavenger contracts. The Phase 1 modules (`boundaries.py`, `bracketing.py`, `signals.py`, `rundir.py`, `publish.py`, `runindex.py`, `scavenger.py`, `locks.py`, `hashing.py`, `io_parquet.py`, `io_video.py`) are read-only from Phase 2's perspective.

### 1.2 Module map

New modules:

```
mimicanno/
  clip_features.py      # NEW: SubtaskSegment + video + signals + parquet → ClipFeatures
  vlm_labeler.py        # NEW: VLMLabeler protocol, FixtureVLMLabeler, LocalGemmaVLMLabeler,
                        #      label_run orchestrator (retry/fallback/degrade)
```

Modified modules (Phase 2 additions only; Phase 1 behavior unchanged):

```
mimicanno/
  pipeline.py           # branch: when target_phase >= 2, append vlm_labeler.label_run step
  schema.py             # extend: vlm_confidence (de)serialization, attempts_log notes format
  config.py             # extend: AnnotationConfig.vlm sub-block (VLMConfig dataclass)
  cli.py                # extend: --vlm-model / --vlm-keyframes / --vlm-max-retries flags
                        #         + abort path for missing --vlm-model when target_phase >= 2
  hashing.py            # extend: VLMConfig fields enter config_hash via AnnotationConfig
                        #         (no change to hashing logic itself; just by inclusion)
```

Untouched (read-only from Phase 2):

```
boundaries.py, bracketing.py, signals.py, rundir.py, publish.py,
runindex.py, scavenger.py, locks.py, io_parquet.py, io_video.py, errors.py
```

### 1.3 External-facing surface diff

| Surface | Phase 1 | Phase 2 |
|---|---|---|
| CLI flag `--target-phase` | accepts `1` | accepts `1` or `2` (3+ defined later) |
| CLI flag `--vlm-model` | absent | required when `--target-phase ≥ 2` |
| CLI flag `--vlm-keyframes` | absent | optional override (default 4) |
| CLI flag `--vlm-max-retries` | absent | optional override (default 3) |
| `manifest.generator.pipeline_phase` | `1` | `2` |
| `manifest.model_versions.vlm` | `null` | `"<vlm_model>:<vlm_checkpoint>"` |
| `manifest.pipeline_params.vlm` | absent | new sub-block (on-disk shape: §2.6) |
| `manifest.pipeline_status.degrade_reason` value space | `null` only | adds `vlm_init_failed` / `vlm_unreachable` / `vlm_runtime_failed` |
| `annotation.segments[].phase` | `"unlabeled"` | allowed_labels member or `"unknown"` (degrade: still `"unlabeled"`) |
| `annotation.segments[].label_source` | `"signals_only"` | `"vlm_robot_state_only"` (degrade: `"signals_only"`) |
| `annotation.segments[].vlm_confidence` | `null` | float ∈ [0.0, 1.0] (degrade: `null`) |
| `annotation.segments[].verb / object / target` | `null` | str or `null` (VLM free-form, no enforcement) |
| `annotation.segments[].overall_confidence` | `boundary_confidence` | `sqrt(boundary_confidence × vlm_confidence)` per parent §6.4 |
| `annotation.notes` | `null` | aggregate 1-line summary (e.g. `"vlm_labeler: 8/8 segments labeled; 2 needed retry; 0 fell back to unknown."`) |

**Schema versioning: NO bumps required.** Current artifact `schema_version`s in the repo are all `0.1.0` (`mimicanno/schema_versions.py`). Phase 2 changes are entirely **semantic** — every field listed above is **already declared** in the Phase 1 schema:

- `SubtaskSegment.phase`, `verb`, `object`, `target`, `evidence`, `failure_flags` — parent §6.1 schema declares them with permissive types; Phase 2 only changes the value space (e.g., `"unlabeled"` → allowed-labels member).
- `SubtaskSegment.label_source` — parent §6.1 already lists `"vlm_robot_state_only"` in the `Literal` set; Phase 2 just starts emitting that value.
- `SubtaskSegment.vlm_confidence` — already typed as `float | None`; Phase 2 fills the float case.
- `SubtaskSegment.overall_confidence` — formula in parent §6.4 already handles the `vlm_confidence != None` branch.
- `manifest.pipeline_params` — declared as a free-form nested dict in parent §4.3; the new `vlm` sub-key (§2.6) is opaque-dict content, not a schema-level addition.
- `manifest.pipeline_status.degrade_reason` — already typed as `string | null` in parent §4.3; new enum values (`vlm_init_failed` / `vlm_unreachable` / `vlm_runtime_failed`) are content, not schema.

Therefore `schema_version` stays `0.1.0` for `manifest.json`, `annotation.json`, `boundaries.json`, `signals.json`, and `COMPAT_BLOCK` is unchanged. Plan 2 viewer requires no version-handling changes.

If a future change forces a structural schema modification (rename, type change, removed field), parent §6.6 mandates a MAJOR bump (independent per artifact). This spec does not introduce any such structural change.

### 1.4 Why per-segment, not whole-episode batched

Per-segment, 1 call per segment is chosen for:

1. **Contract clarity.** 1 call = 1 segment = 1 schema-validated JSON. Retry/fallback boundaries align with the contract boundary.
2. **Local-VLM context budget.** Whole-episode batched packing of `K × N` images into a single call (K=4, typical N=8 ⇒ 32 images) would saturate Gemma 4-class context windows.
3. **Failure isolation.** A single bad segment retries 3 times and falls back to `"unknown"` without contaminating other segments. Whole-episode retry would re-emit all N segments.
4. **No loss of cross-segment information.** Phase 4 smoothing/Viterbi is the designated stage for inter-segment continuity (parent spec §3 phase plan, §10 smoothing). Phase 2 anticipating Phase 4 violates the decoupling principle in core principle #2.

The trade-off: per-segment loses cross-segment context (e.g., "previous segment was `grasp_object`, so this is more likely `lift_object` than `grasp_object` again"). This is intentionally deferred to Phase 4.

### 1.5 Why pluggable interface, not pinned model

The `VLMLabeler` protocol is the spec contract; the model_id is a runtime configuration. Reasons:

1. Parent spec §4.1 already routes `model_config.vlm_model` and `model_config.vlm_checkpoint` into `config_hash`. A model swap produces a distinct `run_hash`, so model versions cannot silently corrupt a run.
2. Phase 2's deliverable is the contract (#12, #13). Model-id pinning belongs to the implementation plan that follows this spec.
3. The Local Gemma 4 IT family is evolving. Pinning a specific HF model_id in this spec would risk staleness; instead, the writing-plans phase pins it against current state.
4. Test/CI cannot depend on a real VLM (GPU, weight downloads, network). `FixtureVLMLabeler` is a first-class implementation, not a test fixture-of-convenience.

## 2. Component contracts

### 2.1 `VLMLabeler` protocol

```python
# mimicanno/vlm_labeler.py

from typing import Protocol, TypedDict, Literal
import numpy as np


class RobotStateSummary(TypedDict):
    duration_sec: float
    mean_eef_speed_mps: float | None  # null when adapter has no EEF (e.g., Koch)
    gripper_open_fraction: float       # [0.0, 1.0], time-weighted average of (gripper_signal >= gripper_open_threshold)
    gripper_transitions: int           # count of threshold crossings of gripper_open_threshold (open↔closed)
    dwell_fraction: float | None       # fraction of segment time where ‖eef_velocity‖ < dwell_speed_threshold_mps;
                                       # null when mean_eef_speed_mps is null (no EEF data)


class VLMRequest(TypedDict):
    """1-call input to the VLM. Episode-level + Segment-level."""
    # Episode-level (constant across segments in a run)
    task_text: str
    allowed_labels: list[str]          # user-supplied set (MUST NOT include reserved "unknown"; see §3.4)
    label_version: str                 # e.g. "manipulation.v1"
    robot_type: str                    # adapter name, e.g. "aloha"
    fps: float
    episode_duration_sec: float
    segment_index: int                 # 1-based
    segment_total: int
    segment_id: str                    # SubtaskSegment.segment_id (e.g. "s_007"), needed by
                                       # FixtureVLMLabeler for routing and by structured logs
    # Segment-level (per call)
    keyframes: list[np.ndarray]        # K_effective images, 1 ≤ len ≤ keyframes_per_segment;
                                       # RGB uint8, long edge resized to image_size_px
    keyframe_offsets_sec: list[float]  # same length as keyframes
    robot_state_summary: RobotStateSummary


class VLMResponse(TypedDict):
    """Validated VLM output. Schema violations raise LabelerError instead."""
    phase: str                         # ∈ allowed_labels ∪ {"unknown"}
    verb: str | None                   # free-form; not validated against any vocabulary
    object: str | None                 # free-form
    target: str | None                 # free-form
    vlm_confidence: float              # ∈ [0.0, 1.0], VLM-self-reported
    evidence: str | None               # ≤ ~80 chars; free-form rationale for human reviewers


class ModelIdentity(TypedDict):
    vlm_model: str                     # e.g. "google/gemma-4-...-it" or "fixture"
    vlm_checkpoint: str | None         # checkpoint hash / revision, or null


RejectReason = Literal[
    "json_parse_error",
    "schema_violation",
    "invalid_label",
    "out_of_range_confidence",
    "timeout",
]

RuntimeFaultReason = Literal[
    "model_unreachable",
    "device_unavailable",
    "cuda_oom",
    "inference_timeout",
]


class LabelerError(Exception):
    """Raised by VLMLabeler.label_segment on VLM **output** rejection
    (parse/schema/range failures). The orchestrator MAY retry."""
    reject_reason: RejectReason


class LabelerRuntimeError(Exception):
    """Raised by VLMLabeler.label_segment on **inference-infrastructure**
    failures (network/device/OOM). The orchestrator MAY retry but counts
    consecutive occurrences against runtime_failure_threshold (§4.3).

    Generic Python RuntimeError is NOT caught by the orchestrator — it is
    treated as an implementation bug and propagated. LocalGemmaVLMLabeler
    is responsible for classifying low-level PyTorch / HF exceptions and
    wrapping them in LabelerRuntimeError with the correct reason."""
    reason: RuntimeFaultReason


class VLMLabeler(Protocol):
    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse:
        """One VLM invocation. Returns a schema-valid VLMResponse or raises:
          - LabelerError(reject_reason)        — recoverable, retry-eligible (Tier 4 → Tier 3)
          - LabelerRuntimeError(reason)        — infra fault (counts toward Tier 2 threshold)
          - any other Exception                — implementation bug, propagated and aborts the run

        `attempt` is the 1-based attempt counter; on attempts > 1 the orchestrator
        passes `last_reject_reason` (the reason of the most recent rejection in
        this segment's loop) so the labeler can apply the stricter-prompt
        amendment from §3.3. `last_reject_reason` is `None` when `attempt == 1`
        or after a `LabelerRuntimeError` (which is not a rejection)."""
        ...

    def model_identity(self) -> ModelIdentity:
        """Returns (config.model_id, config.resolved_checkpoint) — the tuple
        that already entered config_hash at pre-flight (§2.5). The constructor
        MUST NOT re-resolve to a possibly-different revision."""
        ...
```

**Design note: retry/fallback in the orchestrator, not the labeler.** `label_segment` does one call and either succeeds (returns valid response) or raises one of two classified exceptions (or — very rarely — a generic exception that aborts). The retry loop, segment-level fallback to `"unknown"`, run-level degrade thresholding, and observation-log emission live in `vlm_labeler.label_run`. Rationale: keeps the protocol thin and identical for fixture vs real impls; centralizes the policy.

### 2.2 Implementations

```python
class FixtureVLMLabeler:
    """Test/CI implementation. Reads a JSON fixture file and replays canned
    responses (or raises) per segment scenario. Used to deterministically
    exercise retry / fallback / degrade paths without a real model."""

    def __init__(self, fixture_path: Path) -> None: ...
    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity:
        # vlm_model = "fixture"
        # vlm_checkpoint = sha256 of the fixture file content (set by pre-flight, §2.5)
        ...


class LocalGemmaVLMLabeler:
    """Default real-implementation **class** for production runs. Loads a
    Gemma 4-family multimodal IT model via HuggingFace transformers and emits
    structured JSON.

    The CLI does NOT supply a default `model_id` value; users MUST pass
    `--vlm-model <id>` (or supply `VLMConfig.model_id` via a config file)
    when target_phase ≥ 2. This spec does not pin a concrete `model_id`.

    The constructor performs model + processor load against the
    pre-flight-resolved revision (§2.5); failures raise and are converted
    to vlm_init_failed run-level degrade by the labeler factory wrapper
    in label_run (§2.3)."""

    def __init__(self, config: VLMConfig) -> None: ...
    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity:
        # vlm_model = config.model_id
        # vlm_checkpoint = config.resolved_checkpoint (set by pre-flight, §2.5)
        ...
```

`LocalGemmaVLMLabeler` internals (prompt assembly, image preprocessing, JSON parse, validation) are implementation details of writing-plans; this spec only fixes the protocol and prompt skeleton (§3.3). The implementation MUST run the validation pipeline (§3.4) on every response regardless of any model-side structured-output features, so that the contract holds across model swaps.

### 2.3 Orchestrator contract: `label_run`

```python
from typing import Callable

LabelerFactory = Callable[[VLMConfig], VLMLabeler]


def label_run(
    segments: list[SubtaskSegment],
    signals: SignalsBundle,
    video_path: Path,
    parquet_path: Path,
    config: VLMConfig,
    labeler_factory: LabelerFactory,
) -> tuple[list[SubtaskSegment], list[LabelAttempt], RunOutcome]:
    """Owns the full Phase 2 labeling lifecycle, including labeler construction:

    1. Snapshot a Phase 1 baseline copy of `segments` (deep, immutable).
    2. Try `labeler = labeler_factory(config)`.
       - If the constructor raises any exception:
         return (baseline, [], RunOutcome(kind="degraded",
                                          degrade_reason="vlm_init_failed",
                                          underlying_error=repr(e)))
    3. For each segment, run the per-segment retry loop (§3.1) against `labeler`.
       Mutations are made on a working copy of `segments`, NOT the baseline.
    4. If a run-level degrade trigger fires mid-run (vlm_unreachable on the first
       call, or consecutive runtime faults reaching the threshold):
         return (baseline, attempts_log_so_far, RunOutcome(kind="degraded", ...))
       — the working copy is **discarded**; partial Phase 2 labels never leak out.
    5. On full success: return (working_copy, attempts_log, RunOutcome(kind="ok", ...)).

    Transactional invariant: the returned `segments` list is either
    Phase-1-baseline (degraded) or fully Phase-2-labeled (ok). It is never
    a partial mix."""
```

`LabelAttempt` records per-segment retry observability:

```python
@dataclass
class LabelAttempt:
    segment_id: str
    attempt_count: int                       # number of VLM calls made on this segment (1..max_retries)
    final_status: Literal["ok", "unknown_fallback"]
    reject_reasons: list[RejectReason]       # one per failed VLM-output rejection; uses §2.1 enum
    runtime_errors: list[RuntimeFaultReason] # one per infra fault during this segment's attempts
    response: VLMResponse                    # final response (fallback => phase="unknown", confidence=0.0)


@dataclass
class RunOutcome:
    kind: Literal["ok", "degraded"]
    degrade_reason: Literal[
        "vlm_init_failed", "vlm_unreachable", "vlm_runtime_failed",
    ] | None
    underlying_error: str | None             # exception repr — emitted ONLY to stderr JSONL log
                                             # (§4.6); MUST NOT be written into persisted artifacts
                                             # (manifest.json, annotation.notes, etc.) because it can
                                             # contain local paths, env state, or secrets.
```

### 2.4 `VLMConfig` (sub-block of `AnnotationConfig`)

```python
@dataclass(frozen=True)
class ClipFeatureConfig:
    """Thresholds used by clip_features.py to derive the 5-scalar
    robot_state_summary. All fields enter config_hash via VLMConfig."""
    gripper_open_threshold: float = 0.5           # gripper signal value ≥ threshold = "open";
                                                  # signal is the [0,1]-normalized output of the
                                                  # robot adapter's gripper_signal()
    dwell_speed_threshold_mps: float = 0.01       # ‖eef_velocity‖ < threshold = "dwelling";
                                                  # ignored when EEF data is unavailable


@dataclass(frozen=True)
class VLMConfig:
    # User-supplied (set from CLI args / config file)
    model_id: str                                  # e.g. "google/gemma-4-...-it" (may include "@<rev>")
    keyframes_per_segment: int = 4
    keyframe_strategy: Literal["uniform"] = "uniform"  # extension point; only "uniform" in Phase 2
    image_size_px: int = 224                       # long-edge resize before VLM
    max_retries: int = 3
    temperature: float = 0.0                       # deterministic decode for JSON stability
    max_output_tokens: int = 256
    timeout_sec: float = 30.0                      # one call's wall-clock cap; counts as 1 retry
    runtime_failure_threshold: int = 3             # consecutive runtime exceptions → run-level degrade
    device: str = "cuda"                           # informational; LocalGemmaVLMLabeler honors it
    dtype: Literal["bfloat16", "float16", "float32"] = "bfloat16"
    clip_features: ClipFeatureConfig = ClipFeatureConfig()

    # Pre-flight resolved (populated during CLI argument validation per §2.5;
    # MUST be set before AnnotationConfig is hashed; SerDe-visible).
    resolved_checkpoint: str | None = None         # canonical commit sha (or sha256 of fixture file)


@dataclass(frozen=True)
class AnnotationConfig:
    boundary: BoundaryConfig                       # existing
    vlm: VLMConfig | None = None                   # required when target_phase >= 2; null otherwise
```

Hash inclusion: every `VLMConfig` field — including `resolved_checkpoint` — enters `config_hash` (via canonical-JSON serialization of `AnnotationConfig`). Changing `keyframes_per_segment` or `image_size_px` produces a distinct `run_hash` and therefore a distinct run directory — runs cannot silently mix VLM configurations. The `resolved_checkpoint` is populated **before** hashing per the pre-flight contract (§2.5); attempting to hash with `resolved_checkpoint=None` while `target_phase >= 2` is a producer bug.

Note: `resolved_checkpoint` lives on `VLMConfig` for two reasons. (1) `config_hash` covers `AnnotationConfig` end-to-end, and `resolved_checkpoint` MUST be in the hash per parent §4.1's `(vlm_model+checkpoint)` rule. (2) Keeping it on the config (rather than in a side-channel structure) makes the data-flow auditable: every artifact written by the run sees the same `resolved_checkpoint`, and `model_versions.vlm` (§2.6) is the canonical projection `f"{model_id}:{resolved_checkpoint}"`.

### 2.5 Pre-flight model resolution and hashing lifecycle

Parent spec §4.1 pins `model_config (vlm_model+checkpoint)` into `config_hash`. Phase 2 must resolve `vlm_checkpoint` **before** hashing — otherwise the hash and the actually-loaded model can diverge. Resolution happens in a dedicated **pre-flight** step during CLI argument validation:

```
mimicanno annotate --target-phase 2 --vlm-model <id_or_id@rev> [--offline] ...
  │
  ├─ [Pre-flight, Tier-1-eligible]
  │     1. Parse --vlm-model: split on "@" → (model_id, revision_or_None).
  │
  │     2. Resolve revision to a canonical commit sha:
  │
  │        Case A: revision matches /^[0-9a-f]{40}$/ (full HF/git sha)
  │          → accept as-is, no HF API lookup needed (offline-safe).
  │
  │        Case B: revision is a tag/branch name OR revision is None
  │          → must call huggingface_hub.HfApi.model_info(model_id, revision=...)
  │            to resolve to commit sha.
  │            - If --offline is set: Tier 1 abort with error_code=
  │              "vlm_model_not_found" and message "explicit 40-hex commit sha
  │              required after '@' for --offline runs".
  │            - If network failure or 404: Tier 1 abort with same error_code.
  │
  │        Case C (FixtureVLMLabeler, --vlm-model fixture://<path>):
  │          → no HF lookup. resolved_checkpoint = sha256(fixture file content).
  │            Missing fixture file → Tier 1 abort, "vlm_model_not_found".
  │
  │     3. Fix the resolved tuple as VLMConfig.{model_id, resolved_checkpoint}.
  │
  ├─ AnnotationConfig assembled — VLMConfig.model_id and
  │     VLMConfig.resolved_checkpoint both enter the canonical-JSON
  │     serialization that drives config_hash.
  │
  ├─ run_hash, canonical_name resolved.
  │
  └─ ... (rest of pipeline as in §1.1)
```

**Offline / air-gapped operation.** Case A above is the primary offline path: the user pins `--vlm-model google/gemma-4-...-it@<40-hex-sha>` and pre-flight succeeds without any network call. This is the recommended form for reproducibility-critical runs. `--offline` exists as a defense-in-depth flag that forbids any HF API call during pre-flight (fail-fast if the user accidentally omits the `@<sha>`).

**Hash-input contract:** the pair `(VLMConfig.model_id, VLMConfig.resolved_checkpoint)` is fed into `config_hash`. Both are user-determined-at-config-time (after pre-flight); neither depends on the actual model load succeeding. A `VLMLabeler.__init__` failure (CUDA OOM at weight load, transient device fault, etc.) does **not** change the already-computed hash — the run dir is keyed by the configuration the user requested, not by whether the model successfully loaded. This is what allows §4.3 run-level degrade to publish a hash-stable run dir even on init failure.

**`model_identity()` consistency:** `LocalGemmaVLMLabeler.model_identity()` returns the same `(vlm_model, vlm_checkpoint)` that pre-flight wrote into `VLMConfig`. The constructor MUST NOT re-resolve to a possibly-different revision; it loads the pre-resolved sha. If HF API has changed the model between pre-flight and load (rare, but possible), the constructor either succeeds against the resolved sha or raises (which becomes Tier 2 `vlm_init_failed`).

**`FixtureVLMLabeler` lifecycle:** pre-flight runs for fixture URIs (`fixture://<path>`) but takes the dedicated **Case C** path — no HF API call, the fixture file is read from disk and `resolved_checkpoint = sha256(file content)`. The resolved `(model_id="fixture", resolved_checkpoint=<sha>)` then enters `config_hash` exactly like a real model. Fixture file not found → Tier 1 abort with `error_code="vlm_model_not_found"`. The fixture file path itself is carried out-of-band on the runtime-only `VLMConfig.fixture_path` field (excluded from `to_dict` / hash) so identical fixture content at different absolute paths produces identical run hashes.

### 2.6 `manifest.pipeline_params.vlm` on-disk shape

The `vlm` sub-block written into `manifest.json` is a JSON object containing every `VLMConfig` field — including `resolved_checkpoint` so the on-disk form mirrors the dataclass exactly (one source of truth):

```jsonc
"pipeline_params": {
  "boundary": { ... existing Phase 1 sub-block ... },
  "vlm": {
    "clip_features": {
      "dwell_speed_threshold_mps": 0.01,
      "gripper_open_threshold": 0.5
    },
    "device": "cuda",
    "dtype": "bfloat16",
    "image_size_px": 224,
    "keyframe_strategy": "uniform",
    "keyframes_per_segment": 4,
    "max_output_tokens": 256,
    "max_retries": 3,
    "model_id": "google/gemma-4-...-it",
    "resolved_checkpoint": "abc123def456...",
    "runtime_failure_threshold": 3,
    "temperature": 0.0,
    "timeout_sec": 30.0
  }
}
```

Field order is canonical-JSON sorted (lexicographic by key) at write time so byte-equivalent re-emission per parent §6.5 holds. `manifest.model_versions.vlm` is the canonical human-readable projection — `f"{model_id}:{resolved_checkpoint}"` — provided for parent-spec §4.3 alignment and for log/diff convenience; the authoritative copy of `resolved_checkpoint` for hashing and audit purposes is in `pipeline_params.vlm`.

When `target_phase == 1`, `pipeline_params.vlm` is **absent** (not `null`) — preserving Phase 1 manifest byte-equivalence.

### 2.7 `ClipFeatures` (output of `clip_features.py`)

```python
@dataclass
class ClipFeatures:
    keyframes: list[np.ndarray]                    # len ≤ K (auto-reduced for short segments)
    keyframe_offsets_sec: list[float]              # 0.0..(end-start), uniform spacing
    robot_state_summary: RobotStateSummary
```

`ClipFeatureExtractor` is a pure function over `(SubtaskSegment, video_path, signals, parquet)`. No new event detectors, no smoothing — only Phase 1 signals aggregation and frame extraction. EEF unavailability surfaces as `mean_eef_speed_mps=None`, which the prompt instruction handles ("if null, treat as no EEF data").

Keyframe selection rule:

```python
K_effective = min(config.keyframes_per_segment, end_frame - start_frame + 1)
if K_effective == 1:
    offsets_frames = [start_frame]
else:
    offsets_frames = [
        start_frame + round(i * (end_frame - start_frame) / (K_effective - 1))
        for i in range(K_effective)
    ]
```

`K_effective = 1` arises only for sub-frame-resolution segments which Phase 1 already drops via `epsilon_sec` (parent spec §5.6 step 5); the explicit branch is defense-in-depth (the formula is undefined for `K_effective = 1` because the denominator is 0).

## 3. Data flow

### 3.1 Per-segment flow

The orchestrator (§2.3) holds a Phase 1 baseline copy and a working copy of `segments`; the per-segment loop mutates only the working copy.

```
segment ─┬─→ ClipFeatureExtractor.extract(segment, video, signals, parquet) → ClipFeatures
         │
         ├─→ VLMRequest assembled (episode-level + ClipFeatures)
         │
         ├─→ for attempt in 1..max_retries:
         │     │
         │     ├─ try: response = labeler.label_segment(
         │     │       request, attempt, last_reject_reason=last_reject)
         │     │   ├─ consecutive_runtime_failures = 0   (success resets the streak)
         │     │   └─ break (final_status="ok")
         │     │
         │     ├─ except LabelerError as e:
         │     │   reject_reasons.append(e.reject_reason)
         │     │   last_reject = e.reject_reason   # passed to next attempt's label_segment
         │     │   continue                          # so the labeler can apply §3.3 amendment
         │     │
         │     └─ except LabelerRuntimeError as e:
         │         runtime_errors.append(e.reason)
         │         consecutive_runtime_failures += 1
         │         if consecutive_runtime_failures >= config.runtime_failure_threshold:
         │             raise RunDegrade("vlm_runtime_failed", underlying_error=repr(e))
         │             # bubbles to label_run, which DISCARDS the working copy and
         │             # returns the baseline (§2.3 transactional invariant)
         │         else:
         │             continue   # retry within this segment's max_retries budget
         │
         │     # Note: any other Exception (incl. plain RuntimeError) propagates
         │     # without being caught. The orchestrator does NOT swallow generic
         │     # runtime errors — those are implementation bugs and abort the run.
         │
         └─→ if all attempts exhausted (attempt_count == max_retries and no break):
               response = VLMResponse(phase="unknown", verb=None, object=None, target=None,
                                      vlm_confidence=0.0, evidence=None)
               final_status = "unknown_fallback"
```

A successful call in any attempt resets `consecutive_runtime_failures` to 0. Only **consecutive** `LabelerRuntimeError` instances trigger run-level degrade — a run that recovers between flaky infra calls completes normally.

**Special case (`vlm_unreachable`):** if the **first** `label_segment` call across the entire run raises `LabelerRuntimeError(reason="model_unreachable" or "device_unavailable")`, the orchestrator immediately escalates to run-level degrade with `degrade_reason="vlm_unreachable"` (rather than counting toward the `runtime_failure_threshold`). The intent is to fail fast when the inference path is fundamentally unreachable, before consuming retries on every segment.

### 3.2 Segment merge

After the per-segment loop, the orchestrator merges the response into the segment:

```python
segment.phase           = response["phase"]
segment.verb            = response["verb"]
segment.object          = response["object"]
segment.target          = response["target"]
segment.label_source    = "vlm_robot_state_only"
segment.vlm_confidence  = response["vlm_confidence"]
segment.evidence        = response["evidence"]
segment.overall_confidence = (
    0.0 if response["phase"] in {"unlabeled", "unknown"}
    else sqrt(segment.boundary_confidence * response["vlm_confidence"])
)   # parent spec §6.4
segment.object_state_unavailable = True   # Phase 2 invariant
segment.object_track_ids = []             # Phase 2 invariant
```

The reserved-phase rule (parent §6.4) guarantees `overall_confidence == 0.0` for `"unknown"` segments regardless of `vlm_confidence`. The fallback also sets `vlm_confidence = 0.0` defensively, so the formula and the rule agree.

### 3.3 Prompt skeleton

`LocalGemmaVLMLabeler.label_segment` constructs a prompt of this form (writing-plans pins the exact text and image placement; this spec fixes the **information set** and the **output JSON schema**):

```
SYSTEM:
You are labeling a segment of a robot manipulation episode.
Task instruction: "{task_text}"
Robot type: {robot_type}, FPS: {fps}, Episode duration: {episode_duration_sec}s.
This is segment {segment_index} of {segment_total}.

Allowed phase labels (label_version={label_version}):
  {allowed_labels joined with comma}

Robot-state summary for this segment:
  duration_sec: {duration_sec}
  mean_eef_speed_mps: {mean_eef_speed_mps}     # null = no EEF data, ignore
  gripper_open_fraction: {gripper_open_fraction}
  gripper_transitions: {gripper_transitions}
  dwell_fraction: {dwell_fraction}             # null when mean_eef_speed_mps is null

USER:
{K_effective keyframes inline, in temporal order, captioned with offset_sec}

ASSISTANT response MUST be a single JSON object, no prose, no markdown fences:
{
  "phase":          "<one of allowed labels, or 'unknown'>",
  "verb":           "<short verb or null>",
  "object":         "<short noun or null>",
  "target":         "<short noun or null>",
  "vlm_confidence": <float in [0.0, 1.0]>,
  "evidence":       "<≤80 chars, or null>"
}
```

On retry (`attempt > 1`), an additional instruction is appended:

```
Your previous response was rejected: reject_reason={reject_reason}.
Re-emit the JSON exactly per the schema. No prose, no markdown fences, no extra fields.
The "phase" field MUST be one of: {allowed_labels} or "unknown".
```

### 3.4 Validation pipeline

```python
EVIDENCE_DISPLAY_HINT_CHARS = 80  # SOFT — see truncation note below


def parse_and_validate(raw_text: str, user_allowed_labels: set[str]) -> VLMResponse:
    # 1. Strip optional markdown fences ```json ... ```
    text = strip_markdown_fences(raw_text)

    # 2. JSON parse
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise LabelerError("json_parse_error") from e

    # 3. Required fields exist with correct types
    for field, ty in [("phase", str), ("vlm_confidence", (int, float))]:
        if field not in obj or not isinstance(obj[field], ty):
            raise LabelerError("schema_violation")
    for field in ("verb", "object", "target", "evidence"):
        if field in obj and obj[field] is not None and not isinstance(obj[field], str):
            raise LabelerError("schema_violation")

    # 4. phase ∈ user_allowed_labels ∪ {"unknown"}
    #    The reserved "unknown" is appended INTERNALLY here. Callers MUST NOT
    #    include "unknown" in user_allowed_labels (parent §8.4); the labels
    #    YAML loader rejects any user file that defines an id of "unknown" or
    #    "unlabeled" at load time. Ditto for "unlabeled" — neither reserved
    #    phase is ever a valid Phase 2 VLM output (see also §3.2 segment merge
    #    invariants).
    if obj["phase"] not in user_allowed_labels | {"unknown"}:
        raise LabelerError("invalid_label")

    # 5. vlm_confidence ∈ [0.0, 1.0]
    if not 0.0 <= float(obj["vlm_confidence"]) <= 1.0:
        raise LabelerError("out_of_range_confidence")

    # 6. Truncate evidence at write time (SOFT contract — see note).
    evidence = obj.get("evidence")
    if isinstance(evidence, str) and len(evidence) > EVIDENCE_DISPLAY_HINT_CHARS:
        evidence = evidence[:EVIDENCE_DISPLAY_HINT_CHARS]

    # 7. Coerce missing optional fields to None; ignore unknown extra fields (forwards-compat)
    return VLMResponse(
        phase=obj["phase"],
        verb=obj.get("verb"),
        object=obj.get("object"),
        target=obj.get("target"),
        vlm_confidence=float(obj["vlm_confidence"]),
        evidence=evidence,
    )
```

**Length contract for `evidence`:** `EVIDENCE_DISPLAY_HINT_CHARS = 80` is a **soft** cap. Over-length evidence is **truncated at validation**, not rejected — rejecting on length would burn retries for a purely cosmetic problem. The prompt asks for `≤80 chars` as guidance to keep the field usable in viewer chooser banners; the validator enforces the bound by truncation so consumers see at most 80 chars regardless. Producers MAY choose to log the original length to stderr for diagnostics.

**Allowed-labels enforcement:** the producer accepts the user's labels YAML (parent §8.1) and constructs the validator's check set as `user_allowed_labels ∪ {"unknown"}`. Per parent §8.4, the labels YAML loader rejects user-supplied `unknown` / `unlabeled` ids at load time; the spec relies on that pre-condition rather than re-checking it here.

The spec mandates running this validator on every VLM response, regardless of any model-side structured-output enforcement (HF `response_schema`, JSON mode, grammar-constrained decoding, etc.). Model-side enforcement is an implementation optimization — it MAY reduce the retry rate, but MUST NOT replace producer-side validation, because the contract must hold across model swaps with potentially different enforcement capabilities.

### 3.5 Notes aggregation

After all segments are processed, the orchestrator constructs `AnnotationResult.notes`:

```
"vlm_labeler: {N_ok}/{N} segments labeled; {N_retried} needed retry; {N_fallback} fell back to unknown."
```

On run-level degrade:

```
"vlm_labeler: degraded to Phase 1 output (degrade_reason={reason}); 0/{N} segments labeled."
```

Per-attempt detail and the `underlying_error` exception repr go to structured **stderr logs only** (§4.6); `notes` carries the aggregate and `degrade_reason` only. Exception reprs MUST NOT be persisted into any artifact (manifest, annotation, index) because they may contain local file paths, environment state, HF tokens, or CUDA device strings.

## 4. Error and degrade contract

### 4.1 Four-tier error classification

```
Tier 1: CLI / config errors             → abort, exit non-zero, no run dir
Tier 2: Run-level degrade triggers      → Phase 1 output + degrade flag, exit 0
Tier 3: Segment-level fallback          → "unknown" for that segment, run completes, exit 0
Tier 4: Per-attempt rejection           → 1 retry consumed, prompt strict-ified
```

Tiers 1–4 are mutually exclusive per event; an error escalates from Tier 4 → Tier 3 → Tier 2 only when its respective threshold is reached.

### 4.2 Tier 1 — CLI / config (abort)

Tier 1 covers errors detectable **before** any model weight is loaded into memory or any segment is processed. These reflect user / configuration mistakes that the system can identify deterministically and report cleanly.

| Condition | exit | `error_code` |
|---|---|---|
| `--target-phase ≥ 2` and `--vlm-model` not provided | 2 | `vlm_model_required` |
| `target_phase ≥ 2` and `AnnotationConfig.vlm` is `None` or invalid (e.g., `keyframes_per_segment < 1`) | 2 | `vlm_config_invalid` |
| Pre-flight model lookup fails (HF API 404, network unreachable, fixture file missing) | 2 | `vlm_model_not_found` |

Structured stderr per parent §11:

```json
{"error_code": "vlm_model_required",
 "message": "target_phase=2 requires --vlm-model",
 "context": {"target_phase": 2}}
```

No run directory is created. Idempotent re-run with the same broken config produces the same abort.

### 4.3 Tier 2 — Run-level degrade

Tier 2 covers failures **after** pre-flight passes — i.e., the configuration was valid, but the actual VLM execution could not proceed. Per parent spec §11 ("Degrade to Phase N mode for the whole run"), these failures degrade the run to **Phase 1-equivalent output** with degrade flags set in `pipeline_status`.

| Trigger | Detection | `degrade_reason` |
|---|---|---|
| Labeler factory (constructor) raises any exception | `labeler_factory(config)` call inside `label_run` raises (caught at the factory boundary per §2.3) | `vlm_init_failed` |
| Inference path is fundamentally unreachable on the **very first call** | first `label_segment` raises `LabelerRuntimeError(reason ∈ {"model_unreachable", "device_unavailable"})` | `vlm_unreachable` |
| Consecutive `LabelerRuntimeError` instances during inference | `consecutive_runtime_failures >= runtime_failure_threshold` (default 3) | `vlm_runtime_failed` |

**Note:** video decode failures are governed by the existing parent spec §11 row ("Video decode error | abort with the failing path; no partial run directory") — they remain a **Tier 1 abort**, not a Phase 2 degrade. Phase 2 inherits this behavior unchanged from Phase 1.

**Tier 1 vs Tier 2 boundary, in one sentence:** if the failure is detectable from configuration alone (without loading model weights or executing inference) it is Tier 1 abort; once weights begin to load or `label_segment` is first invoked, in-process failures become Tier 2 degrade.

Run-level degrade output:

- `manifest.generator.pipeline_phase = 2` (target was 2)
- `manifest.pipeline_status.degraded_from_phase = 2`
- `manifest.pipeline_status.degrade_reason = <reason>`
- `manifest.pipeline_status.object_state_available = false`
- `manifest.model_versions.vlm = "<vlm_model>:<resolved_checkpoint_sha>"` (always populated; resolved at pre-flight per §2.5)
- `manifest.pipeline_params.vlm = { ... }` (the configured `VLMConfig` per §2.6, regardless of degrade — the run was *configured* for Phase 2)
- Every `annotation.segments[*]`:
  - `phase = "unlabeled"` (Phase 1 baseline)
  - `label_source = "signals_only"`
  - `vlm_confidence = null`
  - `verb = object = target = evidence = null`
  - `overall_confidence = boundary_confidence` (parent §6.4 Phase 1 branch)
- `annotation.notes = "vlm_labeler: degraded to Phase 1 output (degrade_reason=...); 0/N segments labeled."` (`underlying_error` MUST NOT appear here — see §3.5)
- exit 0

**Why segment-level fields revert to Phase 1 baseline on degrade:** the parent spec §11 idiom is explicit — "Degrade to Phase N mode for the whole run". Phase 2-specific values (`label_source="vlm_robot_state_only"`, `vlm_confidence=0.0`, `phase="unknown"`) signal *attempted Phase 2 labeling* on a per-segment basis; degrade signals *no Phase 2 labeling occurred at all*. Mixing the two would make `label_source` ambiguous between "VLM ran on this segment but failed" and "VLM never ran". The unambiguous-meaning rule: **`label_source="vlm_robot_state_only"` ⟺ `VLMLabeler.label_segment` was invoked at least once on this segment**.

The run dir IS published — reusable, discoverable, and visible in the viewer's `pipeline_status` banner. Re-running the same command after fixing the underlying issue produces a different `run_hash` only if the user changed the configuration; otherwise the existing degraded run is short-circuited per parent §4.4 step 2 (so the user must pass `--force` to re-attempt).

### 4.4 Tier 3 — Segment-level fallback

When a segment exhausts `max_retries` with all attempts rejected (any combination of `LabelerError` reasons or non-degrade-threshold runtime errors), the segment falls back to `"unknown"`:

```python
segment.phase                = "unknown"
segment.verb = object = target = None
segment.label_source         = "vlm_robot_state_only"   # Phase 2 was attempted
segment.vlm_confidence       = 0.0
segment.evidence             = None
segment.overall_confidence   = 0.0                       # parent §6.4 reserved-phase rule
```

The run completes normally; `pipeline_status.degraded_from_phase = null`. `label_source` remains `"vlm_robot_state_only"` (not downgraded to `"signals_only"`) to record that VLM labeling was attempted on this run; downstream filters distinguishing "Phase 1 baseline" vs "Phase 2 attempted-and-failed" rely on this.

### 4.5 Tier 4 — Per-attempt rejection

| `reject_reason` | Detection | Retry-prompt amendment |
|---|---|---|
| `json_parse_error` | `json.loads` raises | "Re-emit JSON only, no markdown fences" |
| `schema_violation` | required field missing or type wrong | enumerate required fields and types |
| `invalid_label` | `phase ∉ allowed_labels ∪ {"unknown"}` | re-list `allowed_labels` |
| `out_of_range_confidence` | `vlm_confidence` outside `[0.0, 1.0]` | restate the range constraint |
| `timeout` | `vlm.timeout_sec` exceeded | none (retry as-is) |

Attempts are tracked in `LabelAttempt.reject_reasons` (uses the `RejectReason` enum from §2.1). Infrastructure faults are tracked **separately** in `LabelAttempt.runtime_errors` (uses the `RuntimeFaultReason` enum from §2.1) and counted toward the run-level threshold (§4.3). Implementation note: the two lists are intentionally disjoint by type so consumers can filter "VLM-output rejections" vs "infra incidents" without parsing strings.

### 4.6 Structured observation log (stderr JSONL)

Per attempt:

```jsonl
{"event":"vlm_attempt","segment_id":"s_003","attempt":1,"status":"rejected","reject_reason":"invalid_label","model_id":"google/gemma-4-...","ts":"2026-04-27T..."}
{"event":"vlm_attempt","segment_id":"s_003","attempt":2,"status":"rejected","reject_reason":"schema_violation","ts":"..."}
{"event":"vlm_attempt","segment_id":"s_003","attempt":3,"status":"ok","vlm_confidence":0.62,"ts":"..."}
```

On segment-level fallback:

```jsonl
{"event":"vlm_segment_fallback","segment_id":"s_005","attempts":3,"reject_reasons":["schema_violation","invalid_label","schema_violation"],"ts":"..."}
```

On segment infra-fault (separate from rejection):

```jsonl
{"event":"vlm_runtime_fault","segment_id":"s_007","attempt":2,"reason":"cuda_oom","ts":"..."}
```

On run-level degrade (the **only** place `underlying_error` exception repr is written; never persisted to artifacts):

```jsonl
{"event":"vlm_run_degrade","degrade_reason":"vlm_init_failed","trigger_segment":null,"underlying_error":"<exception repr>","ts":"..."}
```

These events satisfy parent §15.2 exit criterion #12 ("rejection retries are observable in logs") with a machine-checkable signal.

## 5. Test strategy

### 5.1 Three layers

| Layer | Scope | Count target | CI gate |
|---|---|---|---|
| Unit | Pure functions, classes in isolation | ~50+ | always |
| Integration | CLI / pipeline / run-dir, with `FixtureVLMLabeler` | ~10 | always |
| Real-VLM smoke | `LocalGemmaVLMLabeler` with a real model | 1–2 | env-gated, skipped by default |

### 5.2 Unit (Layer 1)

Targets:

- `clip_features.py` scalar computation: each of the 5 scalars on synthetic `SignalsBundle` fixtures (gripper open, gripper closed, mid-transition, no-EEF case for Koch-like adapter).
- `parse_and_validate` — one test per `reject_reason` enum value (positive and each rejection path), plus extra-field tolerance, plus markdown-fence stripping.
- Prompt assembly — snapshot test on the constructed prompt string with a fixed `VLMRequest`. Tests catch any silent prompt-text drift.
- `(de)serialization` of `VLMRequest`, `VLMResponse`, `LabelAttempt`, `RunOutcome` — snapshot-based.
- Orchestrator (`label_run`) with `FixtureVLMLabeler`:
  - all-ok path
  - 1 segment needs 2 retries
  - 1 segment falls back to `"unknown"`
  - 3 consecutive runtime errors → `RunOutcome.kind == "degraded"` with `degrade_reason == "vlm_runtime_failed"`
  - non-consecutive runtime errors (e.g., on segment 2 then 5) → run completes normally
- `model_identity()` plumbing: `FixtureVLMLabeler` returns `("fixture", sha256-of-fixture-file)`.

### 5.3 Integration (Layer 2)

Driven by the existing pytest harness pattern (`env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH`):

- `mimicanno annotate --target-phase 2 --vlm-model fixture://<fixture-path> ...` end-to-end:
  - run dir is published with `pipeline_phase=2`, `model_versions.vlm` non-null.
  - `annotation.segments[*].phase ∈ allowed_labels ∪ {"unknown"}`.
  - `annotation.segments[*].label_source == "vlm_robot_state_only"`.
  - `annotation.notes` matches the aggregate format.
- Degrade integration test — `FixtureVLMLabeler.__init__` raises → run dir still published with `degraded_from_phase=2`, `degrade_reason="vlm_init_failed"`; all segments retain `phase="unlabeled"`, `label_source="signals_only"`.
- Rerun idempotency — running the same command twice produces the same `run_hash` and short-circuits per parent spec §4.4 step 2 (no rewrite). `--force` re-publishes byte-equivalent artifacts modulo `generated_at` and degrade observability fields.
- Hash distinctness — running with `--vlm-keyframes 4` then `--vlm-keyframes 6` produces two different run dirs in the same `runs/index.json`.
- CLI abort test — `--target-phase=2` without `--vlm-model` exits non-zero with structured `error_code=vlm_model_required` JSON on stderr; no run dir.

The `fixture://<path>` URI scheme is a **test-only** URI scheme accepted by the CLI parser. It is **not** part of the stable public CLI contract — it is documented here for implementer / test-author awareness but MUST NOT be referenced from user-facing documentation, MimicRec integration, or any persisted artifact (the fixture's resolved checkpoint = `sha256(file content)` does end up in `model_versions.vlm`, but a downstream consumer encountering that string can simply treat it as opaque).

### 5.4 Real-VLM smoke (Layer 3)

```bash
MIMICANNO_RUN_VLM_SMOKE=1 \
  env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/test_phase2_real_vlm.py
```

Loads `LocalGemmaVLMLabeler` with the writing-plans-pinned default `model_id`, runs labeling on 1 short pre-canned segment, asserts the response is schema-valid. Skipped when `MIMICANNO_RUN_VLM_SMOKE` is unset. Not a CI gate.

### 5.5 `FixtureVLMLabeler` fixture format

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto: sha256 of this file>"},
  "init_should_raise": null,
  "segments": {
    "s_000": {
      "scenario": "ok_first_try",
      "responses": [{
        "phase": "approach_object", "verb": "approach", "object": "red_block",
        "target": null, "vlm_confidence": 0.85,
        "evidence": "gripper open, EEF moving toward block"
      }]
    },
    "s_001": {
      "scenario": "ok_after_2_retries",
      "responses": [
        {"_emit_raw": "garbage not json"},
        {"_emit_raw": "{\"phase\":\"made_up_label\",\"vlm_confidence\":0.5}"},
        {
          "phase": "grasp_object", "verb": "grasp", "object": "red_block",
          "target": null, "vlm_confidence": 0.72, "evidence": "gripper closing"
        }
      ]
    },
    "s_002": {
      "scenario": "fallback_to_unknown",
      "responses": [
        {"_emit_raw": "broken"},
        {"_emit_raw": "broken"},
        {"_emit_raw": "broken"}
      ]
    },
    "s_003": {
      "scenario": "runtime_error",
      "_raise_each_attempt": "LabelerRuntimeError(reason=\"cuda_oom\", message=\"fake OOM\")"
    }
  }
}
```

`FixtureVLMLabeler` interprets each entry's `responses[attempt - 1]`:

- A dict with a top-level `_emit_raw` key — the implementation passes that string directly into `parse_and_validate`, exercising the validator's reject paths (this raises `LabelerError` with the correct `RejectReason`).
- A dict matching `VLMResponse` shape — returned as-is (after passing validation).
- A scenario with `_raise_each_attempt` — the implementation parses the spec-defined exception form and raises the corresponding `LabelerRuntimeError(reason=...)` (or `LabelerError(reject_reason=...)`) on every attempt. The fixture deliberately exercises classified exceptions only; uncaught generic `RuntimeError` is not a fixture-supported scenario (those represent implementation bugs, not infra failures, and are the responsibility of LocalGemmaVLMLabeler unit tests).

The `init_should_raise` field, when non-null, makes `FixtureVLMLabeler.__init__` raise the named exception, exercising the `vlm_init_failed` degrade path.

### 5.6 Snapshot policy

Snapshots live at `tests/snapshots/phase2/` and are JSON pretty-printed for diff readability. Snapshots covered:

- Prompt text for a representative `VLMRequest`.
- `LabelAttempt` JSON for ok / retried / fallback shapes.
- `manifest.json` and `annotation.json` excerpts (Phase 2 fields only) for a fixture-driven smoke run.

Snapshot updates are reviewed manually; CI fails on drift. This guards against silent schema or prompt-text regressions.

## 6. Exit criteria mapping (parent spec §15.2)

**Scope of "Phase 2 exit criteria":** parent §15.2 #12 and #13 describe what a **completed Phase 2 run** must look like. By parent §11 idiom ("Degrade to Phase N mode for the whole run"), a degraded run is **not a Phase 2 run** for purposes of these criteria — it is a Phase-1-equivalent run published with degrade flags so the failure is observable. Exit criteria therefore apply to runs where `manifest.pipeline_status.degraded_from_phase == null` AND `manifest.generator.pipeline_phase == 2`. This split is consistent with how parent §15.3 phrases SAM3's Phase 3 criteria (#14 success vs #15 the explicit synthetic-degrade test).

| Parent criterion | Phase 2 spec satisfaction |
|---|---|
| #12 — VLM labels every Phase 1 clip with one of the allowed labels | §3.2 segment merge invariant; §4.4 segment-level fallback to the reserved `"unknown"` (parent §8.4 explicitly admits `unknown` as a valid label-set member for Phase 2/3). §5.3 integration test asserts `phase ∈ allowed_labels ∪ {"unknown"}` for every segment of every non-degraded run. |
| #12 — rejection retries are observable in logs | §4.6 structured `event=vlm_attempt` JSONL on stderr; §5.3 integration test asserts these events appear for the `ok_after_2_retries` fixture scenario. |
| #13 — `label_source = "vlm_robot_state_only"` on all segments | §3.2 segment merge sets this on the success path; §4.4 keeps it on the segment-level fallback path. Equivalent rule (parent's intent): for any non-degraded Phase 2 run, every segment had `VLMLabeler.label_segment` called on it. Degraded runs are out of scope per the section header above; they emit Phase 1 baseline (`label_source="signals_only"`) and are observed via `pipeline_status.degraded_from_phase=2`. The §5.3 integration test asserts the criterion conditional on non-degrade; the degrade integration test asserts the **negation** path explicitly (so the dual is also verified). |

## 7. Future work / explicitly out of scope

- **VLM accuracy and calibration** (Phase 4 smoothing, Phase 5 evaluation): includes log-prob extraction, ensemble decoding, retry-attenuated confidence, calibration curves, etc.
- **vla-gemma-4 backbone consolidation** (Phase 5): shared Gemma 4 instance between MimicAnno labeling and MimicRec VLA inference. Requires the action head to be detachable and a generic text-generation path on the same backbone. The current vla-gemma-4 architecture (DINO+SigLIP + SoftPromptLibrary + ActionHead, frozen vision backbone, LoRA-adapted Gemma 4) is too specialized to repurpose without extensive rewiring; defer until SAM3 (Phase 3) and smoothing (Phase 4) are stable.
- **Multi-frame strategies beyond uniform-K**: motion-adaptive selection, optical-flow-weighted sampling, keyframe quality scoring. Phase 2 ships uniform-K; the `keyframe_strategy: Literal["uniform"]` field is an extension point for these without breaking the contract.
- **Whole-episode batched VLM calls**: see §1.4. Could become a Phase 4/5 optimization once the per-segment contract is locked and validated, but never in Phase 2.
- **Free-form `verb`/`object`/`target` normalization**: Phase 2 accepts whatever the VLM emits. Normalization (e.g., "red block" / "the red block" → "red_block") happens at Phase 5 export to MimicRec.
- **Concurrent VLM calls**: the per-segment loop is sequential. Parallelism is a Phase 4/5 throughput optimization that does not change the contract.

## 8. Open questions deferred to writing-plans

The following are explicit "decide-during-implementation-plan" items, NOT under-specified:

1. **`LocalGemmaVLMLabeler.__init__` model_id default.** The writing-plans phase pins one HF model_id (Gemma 4 family multimodal IT) as the documented default for the `--vlm-model` flag and the manual smoke test. This spec only requires "Gemma 4 family multimodal IT", not a specific identifier.
2. **Image preprocessing details.** Resize algorithm (bicubic vs lanczos), color space handling, normalization mean/std, and processor/tokenizer wiring are implementation details. The `image_size_px` long-edge target is fixed in the config.
3. **Retry-prompt copy.** §3.3 fixes the retry-prompt structure; the exact wording for each `reject_reason` is for writing-plans to fix once and snapshot-test.
4. **Performance tuning** — batch decoding, KV cache reuse across calls, `torch.compile`. None are required by this spec; all are post-spec optimizations.
5. **Concrete `runtime_failure_threshold` value if 3 turns out to be wrong on the chosen model.** The default 3 is a starting point.
6. **Logging library** (stdlib `logging` vs `structlog`). The on-stderr JSONL **format** is contract; the **library** is not.
7. **Whether to export Plan 2 viewer hints** (e.g., new banner copy for `vlm_runtime_failed`). Probably yes; viewer changes are likely zero-line because the existing `pipeline_status.degrade_reason` is rendered as-is. Confirmed during writing-plans.

## 9. Acceptance

This spec is accepted when:

- The Codex spec-document-reviewer subagent loop completes with "Approved" status.
- The user reviews the file and confirms readiness for writing-plans.

After acceptance, work proceeds to writing-plans, which decomposes this spec into discrete tasks following the parent spec's existing pattern (Plan 1 had 32 tasks, Plan 2 had 19; Phase 2 will likely fall in the same range).
