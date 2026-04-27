# MimicAnno Phase 2 — VLM labeling design

Status: **draft**, awaiting review (Codex).
Author: brainstorming session 2026-04-27.
Supersedes: nothing — new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§3 Phase 2 deliverable, §4.1 hashing, §4.3 manifest schema, §6.1–§6.4 SubtaskSegment / confidence, §8.1–§8.4 allowed-labels enforcement, §11 error handling, §12 package structure, §15.2 Phase 2 exit criteria).
Sibling: [`2026-04-26-mimicanno-plan2-viewer-design.md`](./2026-04-26-mimicanno-plan2-viewer-design.md) (Plan 2 viewer; Phase 2 changes the artifacts it consumes via MINOR schema bumps only).

## 0. Scope and intent

This spec covers **Phase 2**: the **provisional VLM labeling** stage that converts every Phase 1 `unlabeled` segment into one of the allowed labels (or the reserved `"unknown"`), without object-state tracking (SAM3 enters in Phase 3).

Phase 2's purpose, from parent spec §3, is to **lock the VLM JSON schema and allowed-label enforcement** — not to evaluate VLM intelligence. The label quality is a Phase 3+ concern; Phase 2 is the contract, and the contract must survive model swaps.

In scope:

- Single-CLI integration: `mimicanno annotate --target-phase 2 --vlm-model <id> ...` extends the existing entry point.
- Pluggable `VLMLabeler` protocol with two implementations: `FixtureVLMLabeler` (test/CI) and `LocalGemmaVLMLabeler` (default real impl; concrete `model_id` deferred to writing-plans).
- Per-segment, single-call VLM labeling with `K=4` keyframes + 5-scalar robot-state summary + episode-level context.
- Validation, retry (max 3), segment-level fallback to `phase="unknown"`, and run-level degrade triggers/reasons.
- MINOR schema bumps for `manifest.json` and `annotation.json` (forwards-compatible; existing Plan 2 viewer keeps working unchanged).
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
| `manifest.pipeline_params.vlm` | absent | new sub-block (§2.4) |
| `manifest.pipeline_status.degrade_reason` value space | `null` only | adds `vlm_init_failed` / `vlm_unreachable` / `vlm_runtime_failed` |
| `annotation.segments[].phase` | `"unlabeled"` | allowed_labels member or `"unknown"` (degrade: still `"unlabeled"`) |
| `annotation.segments[].label_source` | `"signals_only"` | `"vlm_robot_state_only"` (degrade: `"signals_only"`) |
| `annotation.segments[].vlm_confidence` | `null` | float ∈ [0.0, 1.0] (degrade: `null`) |
| `annotation.segments[].verb / object / target` | `null` | str or `null` (VLM free-form, no enforcement) |
| `annotation.segments[].overall_confidence` | `boundary_confidence` | `sqrt(boundary_confidence × vlm_confidence)` per parent §6.4 |
| `annotation.notes` | `null` | aggregate 1-line summary (e.g. `"vlm_labeler: 8/8 segments labeled; 2 needed retry; 0 fell back to unknown."`) |

Schema versioning: `manifest.json` and `annotation.json` MINOR-bump (`1.0.0 → 1.1.0`). New fields are additive; existing consumers ignore them per parent spec §6.6 forwards-compatibility within MAJOR.

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
    gripper_open_fraction: float       # [0.0, 1.0], time-weighted average of normalized gripper signal
    gripper_transitions: int           # count of threshold crossings (open↔closed)
    dwell_fraction: float              # fraction of segment time where ‖velocity‖ < dwell_threshold


class VLMRequest(TypedDict):
    """1-call input to the VLM. Episode-level + Segment-level."""
    # Episode-level (constant across segments in a run)
    task_text: str
    allowed_labels: list[str]          # e.g. ["idle", "approach_object", ..., "retreat"]
    label_version: str                 # e.g. "manipulation.v1"
    robot_type: str                    # adapter name, e.g. "aloha"
    fps: float
    episode_duration_sec: float
    segment_index: int                 # 1-based
    segment_total: int
    # Segment-level (per call)
    keyframes: list[np.ndarray]        # K images, RGB uint8, long edge resized to image_size_px
    keyframe_offsets_sec: list[float]  # offsets from segment start, len == K
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


class LabelerError(Exception):
    """Raised by VLMLabeler.label_segment on schema/parse/range failures.
    Carries reject_reason for the orchestrator to record in LabelAttempt."""
    reject_reason: Literal[
        "json_parse_error",
        "schema_violation",
        "invalid_label",
        "out_of_range_confidence",
        "timeout",
    ]


class VLMLabeler(Protocol):
    def label_segment(self, request: VLMRequest, attempt: int) -> VLMResponse:
        """One VLM invocation. Returns a schema-valid VLMResponse or raises
        LabelerError (recoverable, retry-eligible) / RuntimeError (runtime fault,
        counts toward run-level degrade threshold) / Exception (init-time, raised
        from __init__ and converted to vlm_init_failed degrade upstream).

        `attempt` is the 1-based attempt counter; the implementation MAY use it
        to apply stricter-prompt phrasing on retry (parent spec §8.2)."""
        ...

    def model_identity(self) -> ModelIdentity:
        """Returns the (vlm_model, vlm_checkpoint) tuple that enters config_hash."""
        ...
```

**Design note: retry/fallback in the orchestrator, not the labeler.** `label_segment` does one call and either succeeds (returns valid response) or raises (with classified `reject_reason` for `LabelerError`, generic for runtime). The retry loop, segment-level fallback to `"unknown"`, run-level degrade thresholding, and observation-log emission live in `vlm_labeler.label_run`. Rationale: keeps the protocol thin and identical for fixture vs real impls; centralizes the policy.

### 2.2 Implementations

```python
class FixtureVLMLabeler:
    """Test/CI implementation. Reads a JSON fixture file and replays canned
    responses (or raises) per segment scenario. Used to deterministically
    exercise retry / fallback / degrade paths without a real model."""

    def __init__(self, fixture_path: Path) -> None: ...
    def label_segment(self, request: VLMRequest, attempt: int) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity:
        # vlm_model = "fixture"
        # vlm_checkpoint = sha256 of the fixture file content
        ...


class LocalGemmaVLMLabeler:
    """Default real implementation. Loads a Gemma 4-family multimodal IT model
    via HuggingFace transformers and emits structured JSON.

    Concrete model_id is configured via VLMConfig; this spec does not pin it.
    The init constructor performs model + processor load; failures raise and
    are converted to vlm_init_failed run-level degrade upstream."""

    def __init__(self, config: VLMConfig) -> None: ...
    def label_segment(self, request: VLMRequest, attempt: int) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity:
        # vlm_model = config.model_id
        # vlm_checkpoint = HF revision sha (resolved at __init__) or None if not resolvable
        ...
```

`LocalGemmaVLMLabeler` internals (prompt assembly, image preprocessing, JSON parse, validation) are implementation details of writing-plans; this spec only fixes the protocol and prompt skeleton (§3.3). The implementation MUST run the validation pipeline (§3.4) on every response regardless of any model-side structured-output features, so that the contract holds across model swaps.

### 2.3 Orchestrator contract: `label_run`

```python
def label_run(
    segments: list[SubtaskSegment],
    signals: SignalsBundle,
    video_path: Path,
    parquet_path: Path,
    config: VLMConfig,
    labeler: VLMLabeler,
) -> tuple[list[SubtaskSegment], list[LabelAttempt], RunOutcome]:
    """Returns (labeled_segments, attempts_log, outcome).

    outcome.kind ∈ {"ok", "degraded"}.
    On degrade, labeled_segments == segments (Phase 1 unchanged) and
    outcome.degrade_reason is set."""
```

`LabelAttempt` records per-segment retry observability:

```python
@dataclass
class LabelAttempt:
    segment_id: str
    attempt_count: int                  # number of VLM calls made (1..max_retries)
    final_status: Literal["ok", "unknown_fallback"]
    reject_reasons: list[str]           # one per failed attempt; ∈ reject_reason enum
    response: VLMResponse               # final response (fallback => phase="unknown", confidence=0.0)


@dataclass
class RunOutcome:
    kind: Literal["ok", "degraded"]
    degrade_reason: Literal[
        "vlm_init_failed", "vlm_unreachable", "vlm_runtime_failed",
    ] | None
    underlying_error: str | None        # exception repr for log/notes; never user-facing
```

### 2.4 `VLMConfig` (sub-block of `AnnotationConfig`)

```python
@dataclass(frozen=True)
class VLMConfig:
    model_id: str                                  # e.g. "google/gemma-4-...-it"
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


@dataclass(frozen=True)
class AnnotationConfig:
    boundary: BoundaryConfig                       # existing
    vlm: VLMConfig | None = None                   # required when target_phase >= 2; null otherwise
```

Hash inclusion: every `VLMConfig` field enters `config_hash` (via canonical-JSON serialization of `AnnotationConfig`). Changing `keyframes_per_segment` or `image_size_px` produces a distinct `run_hash` and therefore a distinct run directory — runs cannot silently mix VLM configurations.

### 2.5 `ClipFeatures` (output of `clip_features.py`)

```python
@dataclass
class ClipFeatures:
    keyframes: list[np.ndarray]                    # len ≤ K (auto-reduced for short segments)
    keyframe_offsets_sec: list[float]              # 0.0..(end-start), uniform spacing
    robot_state_summary: RobotStateSummary
```

`ClipFeatureExtractor` is a pure function over `(SubtaskSegment, video_path, signals, parquet)`. No new event detectors, no smoothing — only Phase 1 signals aggregation and frame extraction. EEF unavailability surfaces as `mean_eef_speed_mps=None`, which the prompt instruction handles ("if null, treat as no EEF data").

Keyframe selection rule:

```
K_effective = min(config.keyframes_per_segment, end_frame - start_frame + 1)
offsets_frames = [start_frame + round(i * (end_frame - start_frame) / (K_effective - 1))
                  for i in range(K_effective)]   # K_effective == 1 case: [start_frame]
```

`K_effective = 1` arises only for sub-frame-resolution segments which Phase 1 already drops via `epsilon_sec` (parent spec §5.6 step 5); included for defense-in-depth.

## 3. Data flow

### 3.1 Per-segment flow

```
segment ─┬─→ ClipFeatureExtractor.extract(segment, video, signals, parquet) → ClipFeatures
         │
         ├─→ VLMRequest assembled (episode-level + ClipFeatures)
         │
         ├─→ for attempt in 1..max_retries:
         │     │
         │     ├─ try: response = labeler.label_segment(request, attempt)
         │     │   └─ break (final_status="ok")
         │     │
         │     ├─ except LabelerError as e:
         │     │   reject_reasons.append(e.reject_reason)
         │     │   continue (with stricter-prompt hint passed via `attempt`)
         │     │
         │     └─ except RuntimeError as e:
         │         consecutive_runtime_failures += 1
         │         if consecutive_runtime_failures >= config.runtime_failure_threshold:
         │             raise RunDegrade("vlm_runtime_failed", e)
         │         else:
         │             reject_reasons.append("runtime_error")  # not part of LabelerError enum;
         │             continue                                # tracked separately in log
         │
         └─→ if all attempts exhausted (attempt_count == max_retries and no break):
               response = VLMResponse(phase="unknown", verb=None, object=None, target=None,
                                      vlm_confidence=0.0, evidence=None)
               final_status = "unknown_fallback"
```

A successful call in any attempt resets `consecutive_runtime_failures` to 0. Only **consecutive** runtime exceptions trigger run-level degrade — a run that recovers between flaky calls completes normally.

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
  dwell_fraction: {dwell_fraction}

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
def parse_and_validate(raw_text: str, allowed_labels: set[str]) -> VLMResponse:
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

    # 4. phase ∈ allowed_labels ∪ {"unknown"}
    if obj["phase"] not in allowed_labels | {"unknown"}:
        raise LabelerError("invalid_label")

    # 5. vlm_confidence ∈ [0.0, 1.0]
    if not 0.0 <= float(obj["vlm_confidence"]) <= 1.0:
        raise LabelerError("out_of_range_confidence")

    # 6. Coerce missing optional fields to None; ignore unknown extra fields (forwards-compat)
    return VLMResponse(
        phase=obj["phase"],
        verb=obj.get("verb"),
        object=obj.get("object"),
        target=obj.get("target"),
        vlm_confidence=float(obj["vlm_confidence"]),
        evidence=obj.get("evidence"),
    )
```

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

Per-attempt detail goes to structured stderr logs (§4.3); `notes` only carries the aggregate.

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

| Condition | exit | `error_code` |
|---|---|---|
| `--target-phase ≥ 2` and `--vlm-model` not provided | 2 | `vlm_model_required` |
| `target_phase ≥ 2` and `AnnotationConfig.vlm` is `None` or invalid | 2 | `vlm_config_invalid` |
| `--vlm-model` value cannot be resolved at startup (HF lookup fails before any inference call) | 2 | `vlm_model_not_found` |

Structured stderr per parent §11:

```json
{"error_code": "vlm_model_required",
 "message": "target_phase=2 requires --vlm-model",
 "context": {"target_phase": 2}}
```

No run directory is created. Idempotent re-run with the same broken config produces the same abort.

### 4.3 Tier 2 — Run-level degrade

| Trigger | Detection | `degrade_reason` |
|---|---|---|
| VLM constructor raises | `LocalGemmaVLMLabeler.__init__` exception | `vlm_init_failed` |
| First call cannot reach the model service / device | first `label_segment` raises `ConnectionError` or device-unavailable `RuntimeError` | `vlm_unreachable` |
| Consecutive runtime failures (e.g., GPU OOM) | `consecutive_runtime_failures >= runtime_failure_threshold` (default 3) | `vlm_runtime_failed` |
| Video decode fails 3 segments in a row | (existing Phase 1 path; out of scope for Phase 2 to redefine) | `video_decode_failed` |

Run-level degrade output:

- `manifest.generator.pipeline_phase = 2` (target was 2)
- `manifest.pipeline_status.degraded_from_phase = 2`
- `manifest.pipeline_status.degrade_reason = <reason>`
- `manifest.pipeline_status.object_state_available = false`
- `manifest.model_versions.vlm = <vlm_model>:<vlm_checkpoint>` (recorded even if init failed, when resolvable; otherwise the model_id only)
- Every `annotation.segments[*]`:
  - `phase = "unlabeled"` (Phase 1 baseline)
  - `label_source = "signals_only"`
  - `vlm_confidence = null`
  - `verb = object = target = evidence = null`
  - `overall_confidence = boundary_confidence` (parent §6.4 Phase 1 branch)
- `annotation.notes = "vlm_labeler: degraded to Phase 1 output (degrade_reason=..., underlying_error=...); 0/N segments labeled."`
- exit 0

The run dir IS published. Reusable, discoverable, and visible in the viewer's `pipeline_status` banner.

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

Attempts are tracked in `LabelAttempt.reject_reasons`. The runtime-error case is **not** part of `reject_reason` enum; it is logged separately and counted toward the run-level threshold.

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

On run-level degrade:

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
- Hash distinctness — running with `--keyframes 4` then `--keyframes 6` produces two different run dirs in the same `runs/index.json`.
- CLI abort test — `--target-phase=2` without `--vlm-model` exits non-zero with structured `error_code=vlm_model_required` JSON on stderr; no run dir.

The `fixture://<path>` URI scheme is a Phase 2-only test convenience supported by the CLI parser; it is not part of any persistent contract and not documented as a user-facing feature.

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
      "_raise_each_attempt": "RuntimeError(\"fake GPU OOM\")"
    }
  }
}
```

`FixtureVLMLabeler` interprets each entry's `responses[attempt - 1]`:

- A dict with a top-level `_emit_raw` key — the implementation passes that string directly into `parse_and_validate`, exercising the validator's reject paths.
- A dict matching `VLMResponse` shape — returned as-is (after passing validation).
- A scenario with `_raise_each_attempt` — the implementation raises the named exception type with the given message on every call.

The `init_should_raise` field, when non-null, makes `FixtureVLMLabeler.__init__` raise the named exception, exercising the `vlm_init_failed` degrade path.

### 5.6 Snapshot policy

Snapshots live at `tests/snapshots/phase2/` and are JSON pretty-printed for diff readability. Snapshots covered:

- Prompt text for a representative `VLMRequest`.
- `LabelAttempt` JSON for ok / retried / fallback shapes.
- `manifest.json` and `annotation.json` excerpts (Phase 2 fields only) for a fixture-driven smoke run.

Snapshot updates are reviewed manually; CI fails on drift. This guards against silent schema or prompt-text regressions.

## 6. Exit criteria mapping (parent spec §15.2)

| Parent criterion | Phase 2 spec satisfaction |
|---|---|
| #12 — VLM labels every Phase 1 clip with one of the allowed labels | §3.2 (segment merge invariant), §4.4 (segment-level fallback to `"unknown"` ∈ allowed reserved set), §5.3 integration test asserting `phase ∈ allowed_labels ∪ {"unknown"}` for all segments. |
| #12 — rejection retries are observable in logs | §4.6 structured `event=vlm_attempt` JSONL on stderr; §5.3 integration test asserting these events appear for the `ok_after_2_retries` fixture scenario. |
| #13 — `label_source = "vlm_robot_state_only"` on all segments | §3.2 segment merge sets this unconditionally on the success path; §4.4 keeps it on the segment-level fallback path. The only case where `label_source = "signals_only"` is run-level degrade (§4.3), which is by spec design — the run did not complete Phase 2. |

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
