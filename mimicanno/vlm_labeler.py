"""Phase 2 VLMLabeler protocol, types, exception classes, and label_run
orchestrator (spec §2.1 + §2.3).

This file is the contract surface. Concrete implementations
(FixtureVLMLabeler, LocalGemmaVLMLabeler) and the orchestrator land in
later tasks.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NotRequired, Protocol, TypedDict, get_args

import numpy as np

from mimicanno.config import VLMConfig
from mimicanno.schema import ObjectStateSummary, SubtaskSegment

# --- Reject / runtime-fault reason enums (kept as Literal for type-checkers,
#     and re-exported as concrete tuples for runtime exhaustiveness checks).

RejectReason = Literal[
    "json_parse_error",
    "schema_violation",
    "invalid_label",
    "out_of_range_confidence",
    "timeout",
]
REJECT_REASONS: tuple[str, ...] = get_args(RejectReason)

RuntimeFaultReason = Literal[
    "model_unreachable",
    "device_unavailable",
    "cuda_oom",
    "inference_timeout",
]
RUNTIME_FAULT_REASONS: tuple[str, ...] = get_args(RuntimeFaultReason)


# --- Exception classes ------------------------------------------------------

class LabelerError(Exception):
    """Raised on VLM-output rejection (parse / schema / range failures).
    Retry-eligible (spec §4.5)."""
    def __init__(self, reject_reason: RejectReason) -> None:
        super().__init__(f"VLM output rejected: {reject_reason}")
        self.reject_reason: RejectReason = reject_reason


class LabelerRuntimeError(Exception):
    """Raised on inference-infrastructure faults. Counted toward
    runtime_failure_threshold (§4.3). Generic Python RuntimeError is NOT
    caught by the orchestrator — implementations must classify and wrap
    underlying PyTorch / HF exceptions into this class."""
    def __init__(self, reason: RuntimeFaultReason) -> None:
        super().__init__(f"VLM runtime fault: {reason}")
        self.reason: RuntimeFaultReason = reason


# --- Type surface -----------------------------------------------------------

class ModelIdentity(TypedDict):
    vlm_model: str
    vlm_checkpoint: str


class VLMResponse(TypedDict):
    phase: str                  # ∈ allowed_labels ∪ {"unknown"}
    verb: str | None
    object: str | None
    target: str | None
    vlm_confidence: float       # ∈ [0.0, 1.0]
    evidence: str | None


class VLMRequest(TypedDict):
    task_text: str
    allowed_labels: list[str]
    label_version: str
    robot_type: str
    fps: float
    episode_duration_sec: float
    segment_index: int          # 1-based ordinal in the episode
    segment_total: int
    segment_id: str             # SubtaskSegment.segment_id (e.g. "s_007"); spec §2.1
    keyframes: list[np.ndarray]
    keyframe_offsets_sec: list[float]
    robot_state_summary: dict[str, Any]   # see clip_features.RobotStateSummary
    object_state_summary: NotRequired[ObjectStateSummary | None]  # Phase 3; spec §5.4
    # Task 7 (vlm-mask-overlay): one-line color legend for SAM3 mask overlays
    # painted onto `keyframes`. Built per-segment by the labeler orchestrator
    # via vlm_overlay.build_color_legend; None when overlay is disabled or no
    # prompt has any non-None mask in this segment.
    mask_overlay_legend: NotRequired[str | None]


@dataclass(slots=True)
class LabelAttempt:
    segment_id: str
    attempt_count: int
    final_status: Literal["ok", "unknown_fallback"]
    reject_reasons: list[RejectReason] = field(default_factory=list)
    runtime_errors: list[RuntimeFaultReason] = field(default_factory=list)
    response: VLMResponse = field(default_factory=lambda: VLMResponse(
        phase="unknown", verb=None, object=None, target=None,
        vlm_confidence=0.0, evidence=None,
    ))
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunOutcome:
    kind: Literal["ok", "degraded"]
    degrade_reason: Literal[
        "vlm_init_failed", "vlm_unreachable", "vlm_runtime_failed"
    ] | None
    underlying_error: str | None  # exception repr — stderr-log-only, never artifact


# --- Protocol ---------------------------------------------------------------

class VLMLabeler(Protocol):
    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity: ...


# --- parse_and_validate (spec §3.4) -----------------------------------------

EVIDENCE_DISPLAY_HINT_CHARS = 80

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def parse_and_validate(raw_text: str, user_allowed_labels: set[str]) -> VLMResponse:
    """Validate a VLM response string against the spec §3.4 contract.

    On any failure raises LabelerError(reject_reason=...). On success returns
    a VLMResponse with optional fields coerced to None and evidence truncated
    to EVIDENCE_DISPLAY_HINT_CHARS (soft cap).

    `user_allowed_labels` MUST NOT include 'unknown' or 'unlabeled' (parent
    §8.4 — labels YAML loader rejects these). Validator internally accepts
    'unknown' as a valid VLM output; 'unlabeled' is always rejected.
    """
    text = _strip_markdown_fences(raw_text)

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise LabelerError("json_parse_error") from e
    if not isinstance(obj, dict):
        raise LabelerError("schema_violation")

    if "phase" not in obj or not isinstance(obj["phase"], str):
        raise LabelerError("schema_violation")
    if "vlm_confidence" not in obj or not isinstance(obj["vlm_confidence"], (int, float)) \
            or isinstance(obj["vlm_confidence"], bool):
        raise LabelerError("schema_violation")
    for field_name in ("verb", "object", "target", "evidence"):
        if field_name in obj and obj[field_name] is not None and not isinstance(obj[field_name], str):
            raise LabelerError("schema_violation")

    if obj["phase"] not in user_allowed_labels | {"unknown"}:
        raise LabelerError("invalid_label")

    if not 0.0 <= float(obj["vlm_confidence"]) <= 1.0:
        raise LabelerError("out_of_range_confidence")

    evidence = obj.get("evidence")
    if isinstance(evidence, str) and len(evidence) > EVIDENCE_DISPLAY_HINT_CHARS:
        evidence = evidence[:EVIDENCE_DISPLAY_HINT_CHARS]

    return VLMResponse(
        phase=obj["phase"],
        verb=obj.get("verb"),
        object=obj.get("object"),
        target=obj.get("target"),
        vlm_confidence=float(obj["vlm_confidence"]),
        evidence=evidence,
    )


# --- FixtureVLMLabeler (spec §5.5) ------------------------------------------

_FIXT_RUNTIME_PATTERN = re.compile(
    r"^LabelerRuntimeError\((?P<reason>[a-z_]+)\)$"
)


class FixtureVLMLabeler:
    """Test/CI implementation that replays scenarios from a fixture JSON
    (spec §5.5). Routing per segment uses ``request["segment_id"]`` (spec §2.1).
    """

    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = Path(fixture_path)
        body = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        init_raise = body.get("init_should_raise")
        if init_raise is not None:
            if init_raise.startswith("RuntimeError("):
                raise RuntimeError(init_raise)
            raise Exception(init_raise)
        self._segments: dict[str, dict[str, Any]] = body.get("segments", {})
        self._sha256 = hashlib.sha256(self._fixture_path.read_bytes()).hexdigest()

    def model_identity(self) -> ModelIdentity:
        return ModelIdentity(vlm_model="fixture", vlm_checkpoint=self._sha256)

    def _route(self, segment_id: str) -> dict[str, Any]:
        if segment_id in self._segments:
            return self._segments[segment_id]
        if "*" in self._segments:
            return self._segments["*"]
        raise KeyError(
            f"fixture has no scenario for segment_id={segment_id!r} and no '*' wildcard"
        )

    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse:
        scen = self._route(request["segment_id"])

        raise_each = scen.get("_raise_each_attempt")
        if raise_each is not None:
            m = _FIXT_RUNTIME_PATTERN.match(raise_each)
            if m:
                reason = m.group("reason")
                if reason not in RUNTIME_FAULT_REASONS:
                    raise RuntimeError(
                        f"fixture uses unknown runtime fault reason: {reason!r} "
                        f"(allowed: {RUNTIME_FAULT_REASONS})"
                    )
                raise LabelerRuntimeError(reason)  # type: ignore[arg-type]
            m2 = re.match(r"^LabelerError\(([a-z_]+)\)$", raise_each)
            if m2:
                reject = m2.group(1)
                if reject not in REJECT_REASONS:
                    raise RuntimeError(
                        f"fixture uses unknown reject reason: {reject!r} "
                        f"(allowed: {REJECT_REASONS})"
                    )
                raise LabelerError(reject)  # type: ignore[arg-type]
            raise RuntimeError(f"unparseable _raise_each_attempt: {raise_each!r}")

        responses = scen.get("responses", [])
        idx = attempt - 1
        if idx >= len(responses):
            raise RuntimeError(
                f"fixture exhausted: fixture={self._fixture_path} "
                f"segment_id={request['segment_id']!r} attempt={attempt}"
            )
        spec = responses[idx]

        if "_emit_raw" in spec:
            return parse_and_validate(spec["_emit_raw"], set(request["allowed_labels"]))
        as_text = json.dumps(spec)
        return parse_and_validate(as_text, set(request["allowed_labels"]))


# ---------------------------------------------------------------------------
# label_run orchestrator (spec §2.3, §4.4, §4.5)
# ---------------------------------------------------------------------------

LabelerFactory = Callable[[VLMConfig], "VLMLabeler"]


def _build_request(
    segment: SubtaskSegment,
    segment_index: int,
    segment_total: int,
    *,
    extractor: Any,
    gripper: np.ndarray,
    eef_velocity: np.ndarray | None,
    keyframes_per_segment: int,
    episode_meta: dict[str, Any],
    mask_cache: Any = None,
    mask_alpha: float = 0.4,
) -> VLMRequest:
    """Compose a VLMRequest from a SubtaskSegment and the run-level metadata.

    Keyframe + scalar extraction is delegated to ClipFeatureExtractor (Task 4);
    this function only reshapes the ClipFeatures into the VLMRequest TypedDict
    and attaches episode-level fields from `episode_meta`.

    ``mask_cache`` (Task 8): when provided, keyframe extraction overlays
    SAM3 masks (via ClipFeatureExtractor) and the per-segment color legend
    is built and attached to the request. ``None`` preserves pre-overlay
    behaviour bit-identically.
    """
    # Only thread mask kwargs through when overlay is actually engaged so
    # test-stub extractors that haven't been migrated to the Task 6
    # signature keep working untouched.
    if mask_cache is not None:
        feat = extractor.extract(
            segment=segment, gripper=gripper, eef_velocity=eef_velocity,
            keyframes_per_segment=keyframes_per_segment,
            mask_cache=mask_cache, mask_alpha=mask_alpha,
        )
    else:
        feat = extractor.extract(
            segment=segment, gripper=gripper, eef_velocity=eef_velocity,
            keyframes_per_segment=keyframes_per_segment,
        )
    legend: str | None = None
    if mask_cache is not None:
        from mimicanno.clip_features import compute_keyframe_offsets
        from mimicanno.vlm_overlay import build_color_legend
        offsets = compute_keyframe_offsets(
            segment.start_frame, segment.end_frame, keyframes_per_segment,
        )
        legend = build_color_legend(mask_cache, offsets)
    request = VLMRequest(
        task_text=episode_meta["task_text"],
        allowed_labels=list(episode_meta["allowed_labels"]),
        label_version=episode_meta.get("label_version", "manipulation.v1"),
        robot_type=episode_meta.get("robot_type", "aloha"),
        fps=episode_meta["fps"],
        episode_duration_sec=episode_meta["episode_duration_sec"],
        segment_index=segment_index, segment_total=segment_total,
        segment_id=segment.segment_id,
        keyframes=feat.keyframes,
        keyframe_offsets_sec=feat.keyframe_offsets_sec,
        robot_state_summary=feat.robot_state_summary,
    )
    if legend is not None:
        request["mask_overlay_legend"] = legend
    return request


def _merge_response(
    seg: SubtaskSegment, resp: VLMResponse,
) -> SubtaskSegment:
    seg.phase = resp["phase"]
    seg.verb = resp["verb"]
    seg.object = resp["object"]
    seg.target = resp["target"]
    seg.label_source = "vlm_robot_state_only"  # §4.4 invariant
    seg.vlm_confidence = resp["vlm_confidence"]
    seg.evidence = resp["evidence"]
    if seg.phase in ("unlabeled", "unknown"):
        seg.overall_confidence = 0.0
    else:
        seg.overall_confidence = math.sqrt(
            max(seg.boundary_confidence, 0.0) * max(seg.vlm_confidence, 0.0)
        )
    seg.object_state_unavailable = True
    seg.object_track_ids = []
    return seg


def label_run(
    *,
    segments: list[SubtaskSegment],
    extractor: Any,
    gripper: np.ndarray,
    eef_velocity: np.ndarray | None,
    episode_meta: dict[str, Any],
    config: VLMConfig,
    labeler_factory: LabelerFactory,
) -> tuple[list[SubtaskSegment], list[LabelAttempt], RunOutcome]:
    """Phase 2 labeling lifecycle owner — see spec §2.3 for the contract.

    Constructor failures, vlm_unreachable on first call, and
    runtime_failure_threshold escalation all return the Phase 1 baseline
    with a degraded RunOutcome; partial labels never leak.

    `episode_meta` is a flat dict carrying the episode-level fields that
    populate VLMRequest: task_text, allowed_labels, label_version, robot_type,
    fps, episode_duration_sec. The pipeline (Task 13) constructs it; tests
    can build it directly via helpers_phase1.make_synthetic_phase1_run."""
    baseline = copy.deepcopy(segments)
    working = copy.deepcopy(segments)
    attempts: list[LabelAttempt] = []

    try:
        labeler = labeler_factory(config)
    except Exception as e:
        return baseline, [], RunOutcome(
            kind="degraded", degrade_reason="vlm_init_failed",
            underlying_error=repr(e),
        )

    consecutive_runtime_failures = 0
    n = len(working)
    for idx, seg in enumerate(working):
        attempt_log = LabelAttempt(
            segment_id=seg.segment_id, attempt_count=0, final_status="ok",
        )
        attempts.append(attempt_log)
        request = _build_request(
            seg, segment_index=idx + 1, segment_total=n,
            extractor=extractor, gripper=gripper, eef_velocity=eef_velocity,
            keyframes_per_segment=config.keyframes_per_segment,
            episode_meta=episode_meta,
        )
        last_reject: RejectReason | None = None
        success = False
        for attempt in range(1, config.max_retries + 1):
            attempt_log.attempt_count = attempt
            try:
                resp = labeler.label_segment(
                    request, attempt=attempt,
                    last_reject_reason=last_reject,
                )
                consecutive_runtime_failures = 0
                _merge_response(seg, resp)
                attempt_log.final_status = "ok"
                attempt_log.response = resp
                success = True
                break
            except LabelerError as e:
                attempt_log.reject_reasons.append(e.reject_reason)
                # Only rejects update the hint; runtime faults preserve the last reject.
                last_reject = e.reject_reason
                continue
            except LabelerRuntimeError as e:
                attempt_log.runtime_errors.append(e.reason)
                if (idx == 0 and attempt == 1
                        and e.reason in ("model_unreachable", "device_unavailable")):
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_unreachable",
                        underlying_error=repr(e),
                    )
                consecutive_runtime_failures += 1
                if consecutive_runtime_failures >= config.runtime_failure_threshold:
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_runtime_failed",
                        underlying_error=repr(e),
                    )
                continue
        if not success:
            fallback_resp = VLMResponse(
                phase="unknown", verb=None, object=None, target=None,
                vlm_confidence=0.0, evidence=None,
            )
            _merge_response(seg, fallback_resp)
            attempt_log.final_status = "unknown_fallback"
            attempt_log.response = fallback_resp

    return working, attempts, RunOutcome(kind="ok", degrade_reason=None,
                                          underlying_error=None)


# ---------------------------------------------------------------------------
# LocalGemmaVLMLabeler (spec §2.2, §8 #1)
# ---------------------------------------------------------------------------

DEFAULT_LOCAL_GEMMA_MODEL_ID = "google/gemma-4-E2B-it"


def _resolve_auto_model_class() -> Any:
    """Resolve the transformers AutoModel class for image+text→text VLMs.

    transformers 5.x renamed `AutoModelForVision2Seq` to
    `AutoModelForImageTextToText`. Try the 5.x name first; fall back to the
    4.x name. Raises ImportError if neither is available (very old or very
    broken transformers install).

    Compatibility note: transformers 4.x and 5.x are *expected* to expose
    these names mutually exclusively — i.e. on a 5.x install
    `AutoModelForVision2Seq` is absent and on a 4.x install
    `AutoModelForImageTextToText` is absent. We bias towards 5.x because the
    Phase 5 follow-up real-data smoke ran on transformers 5.6.2 + Gemma 4
    E2B-it. If a transformers version ever exposes both names with
    different behavior, this resolver picks 5.x silently — adjust the
    ordering here if 4.x compatibility becomes the priority.
    """
    import transformers
    for name in ("AutoModelForImageTextToText", "AutoModelForVision2Seq"):
        cls = getattr(transformers, name, None)
        if cls is not None:
            return cls
    raise ImportError(
        "transformers has neither AutoModelForImageTextToText (>=5.0) nor "
        "AutoModelForVision2Seq (<5.0). Install a supported transformers "
        "version."
    )


def _hf_load_model_and_processor(
    *, model_id: str, revision: str, device: str, dtype: str,
) -> tuple[Any, Any]:
    """Load the HF model + processor at the pre-flight-resolved revision.
    Isolated for monkeypatching in unit tests."""
    import torch
    from transformers import AutoProcessor
    AutoModelClass = _resolve_auto_model_class()
    torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                   "float32": torch.float32}[dtype]
    model = AutoModelClass.from_pretrained(
        model_id, revision=revision, torch_dtype=torch_dtype,
    ).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_id, revision=revision)
    return model, processor


def _unsloth_load_model_and_processor(
    *, model_id: str, dtype: str,
) -> tuple[Any, Any]:
    """Load a Unsloth LoRA adapter (4-bit QLoRA) + processor.

    ``model_id`` must be a local directory containing ``adapter_config.json``.
    The base model path is read from ``adapter_config.json::base_model_name_or_path``.
    Unsloth's ``FastLanguageModel.from_pretrained`` accepts the adapter dir
    directly and fuses the LoRA weights automatically.

    ``device`` is not accepted because Unsloth manages device placement
    internally (always targets CUDA).
    """
    import json
    import torch
    from pathlib import Path
    from transformers import AutoProcessor

    adapter_cfg = json.loads((Path(model_id) / "adapter_config.json").read_text())
    base_model = adapter_cfg["base_model_name_or_path"]

    try:
        from unsloth import FastLanguageModel
    except ImportError as exc:
        raise ImportError(
            "unsloth is required to load LoRA adapters. "
            "Activate the unsloth_env conda environment: "
            "conda activate unsloth_env"
        ) from exc

    torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                   "float32": torch.float32}[dtype]
    model, _ = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=2048,
        load_in_4bit=True,
        dtype=torch_dtype,
        device_map="cuda:0",  # CUDA_VISIBLE_DEVICES で絞った1枚に収める
    )
    FastLanguageModel.for_inference(model)
    processor = AutoProcessor.from_pretrained(model_id)
    return model, processor


def _maybe_dump_vlm_input(
    request: VLMRequest,
    prompt: str,
    attempt: int,
    last_reject_reason: RejectReason | None,
) -> None:
    """Optional dump of Gemma inputs (prompt + keyframes + metadata).

    Activated by env var ``MIMICANNO_VLM_DUMP_DIR``. Writes to
    ``<dump_dir>/<segment_id>/attempt_<N>/{prompt.txt,request.json,keyframe_<i>.png}``.
    Set a per-episode dump dir to keep runs separated.

    Task 11 note: when ``VLMConfig.mask_overlay.enabled`` is True, the
    keyframes here are already overlay-baked — ``ClipFeatureExtractor``
    composes SAM3 masks onto the frame in ``_build_request`` before they
    land in the request dict. The dump path needs no special-casing.
    """
    import os
    dump_root = os.environ.get("MIMICANNO_VLM_DUMP_DIR")
    if not dump_root:
        return
    from PIL import Image
    out = Path(dump_root) / request["segment_id"] / f"attempt_{attempt}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    meta = {
        "task_text": request["task_text"],
        "allowed_labels": request["allowed_labels"],
        "label_version": request["label_version"],
        "robot_type": request["robot_type"],
        "fps": request["fps"],
        "episode_duration_sec": request["episode_duration_sec"],
        "segment_index": request["segment_index"],
        "segment_total": request["segment_total"],
        "segment_id": request["segment_id"],
        "keyframe_offsets_sec": request["keyframe_offsets_sec"],
        "robot_state_summary": request["robot_state_summary"],
        "object_state_summary": request.get("object_state_summary"),
        "mask_overlay_legend": request.get("mask_overlay_legend"),
        "attempt": attempt,
        "last_reject_reason": last_reject_reason,
    }
    (out / "request.json").write_text(
        json.dumps(meta, indent=2, default=str), encoding="utf-8"
    )
    for i, frame in enumerate(request["keyframes"]):
        Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(
            out / f"keyframe_{i:02d}.png"
        )


def _maybe_dump_vlm_output(
    request: VLMRequest,
    attempt: int,
    raw_text: str,
) -> None:
    import os
    dump_root = os.environ.get("MIMICANNO_VLM_DUMP_DIR")
    if not dump_root:
        return
    out = Path(dump_root) / request["segment_id"] / f"attempt_{attempt}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "response.txt").write_text(raw_text, encoding="utf-8")


@dataclass(frozen=True)
class GemmaHandle:
    """Thin reference to a loaded Gemma model + processor.

    Returned by ``LocalGemmaVLMLabeler.shared_handle()``. All three attributes
    are the SAME Python objects as inside the originating labeler — no copies.
    Callers can verify identity with ``id(handle.model) == id(labeler._model)``.
    """

    model: Any
    processor: Any
    config: VLMConfig


class LocalGemmaVLMLabeler:
    """Default real implementation — Gemma 4-family multimodal IT loaded via
    HuggingFace transformers (spec §2.2). Documented default:
    `google/gemma-4-E2B-it`.

    The constructor loads the model + processor against the pre-flight-resolved
    revision (§2.5); it never re-resolves. Failures propagate unwrapped — the
    label_run orchestrator catches them at the labeler-factory boundary and
    converts to vlm_init_failed degrade.
    """

    def __init__(self, config: VLMConfig) -> None:
        if config.resolved_checkpoint is None:
            raise ValueError("resolved_checkpoint must be set by pre-flight (§2.5)")
        self._config = config
        if config.is_lora_adapter:
            model, processor = _unsloth_load_model_and_processor(
                model_id=config.model_id,
                dtype=config.dtype,
            )
        else:
            model, processor = _hf_load_model_and_processor(
                model_id=config.model_id,
                revision=config.resolved_checkpoint,
                device=config.device,
                dtype=config.dtype,
            )
        self._model: Any = model
        self._processor: Any = processor

    def model_identity(self) -> ModelIdentity:
        return ModelIdentity(
            vlm_model=self._config.model_id,
            vlm_checkpoint=self._config.resolved_checkpoint or "",
        )

    def shared_handle(self) -> GemmaHandle:
        """Return a GemmaHandle exposing the same model/processor/config objects.

        The returned handle holds references (not copies) to ``self._model``,
        ``self._processor``, and ``self._config``. Identity is preserved:
        ``id(handle.model) == id(self._model)``.
        """
        return GemmaHandle(
            model=self._model,
            processor=self._processor,
            config=self._config,
        )

    def label_segment(
        self,
        request: VLMRequest,
        attempt: int,
        last_reject_reason: RejectReason | None = None,
    ) -> VLMResponse:
        from mimicanno.vlm_prompt import build_messages

        # transformers 5.x chat-template path: messages with explicit image
        # content blocks → apply_chat_template inserts the right number of
        # image placeholder tokens that align with `images=keyframes` below.
        # Verified end-to-end on transformers 5.6.2 + Gemma 4 E2B-it
        # (Phase 5 follow-up real-data smoke). transformers 4.x is also
        # expected to work via apply_chat_template — most 4.x VLM
        # processors implemented this method too — but has not been
        # exercised in CI; if you maintain 4.x support, add a smoke test.
        messages = build_messages(
            request, attempt=attempt, last_reject_reason=last_reject_reason
        )
        prompt = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        _maybe_dump_vlm_input(request, prompt, attempt, last_reject_reason)
        try:
            inputs = self._processor(
                text=prompt, images=request["keyframes"], return_tensors="pt"
            ).to(self._config.device)
            input_len = inputs["input_ids"].shape[1]
            with self._timeout_guard():
                tokens = self._model.generate(
                    **inputs,
                    do_sample=False,
                    temperature=self._config.temperature,
                    max_new_tokens=self._config.max_output_tokens,
                )
            # Slice off the prompt portion before decoding — `decoded.startswith(
            # prompt)` no longer matches reliably with the chat-template path
            # because batch_decode(skip_special_tokens=True) strips template
            # delimiters from the output but the `prompt` variable still
            # contains them. Token-level slicing is unambiguous.
            new_tokens = tokens[:, input_len:]
            decoded = self._processor.batch_decode(
                new_tokens, skip_special_tokens=True
            )[0]
        except Exception as e:
            self._raise_classified(e)
            raise  # unreachable; helps static analysis

        _maybe_dump_vlm_output(request, attempt, decoded)
        return parse_and_validate(decoded.strip(),
                                  set(request["allowed_labels"]))

    def _timeout_guard(self) -> AbstractContextManager[None]:
        import contextlib
        import signal
        from collections.abc import Iterator
        from types import FrameType

        @contextlib.contextmanager
        def _gm() -> Iterator[None]:
            def _handler(signum: int, frame: FrameType | None) -> None:
                raise TimeoutError(
                    f"inference exceeded {self._config.timeout_sec}s"
                )
            old = signal.signal(signal.SIGALRM, _handler)
            signal.setitimer(signal.ITIMER_REAL, self._config.timeout_sec)
            try:
                yield
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        return _gm()

    def _raise_classified(self, e: Exception) -> None:
        """Map low-level PyTorch / HF exceptions into LabelerRuntimeError(reason)."""
        import torch
        if isinstance(e, torch.cuda.OutOfMemoryError):
            raise LabelerRuntimeError("cuda_oom") from e
        if isinstance(e, TimeoutError):
            raise LabelerRuntimeError("inference_timeout") from e
        if isinstance(e, ConnectionError) or "connection" in str(e).lower():
            raise LabelerRuntimeError("model_unreachable") from e
        if isinstance(e, RuntimeError) and "device" in str(e).lower():
            raise LabelerRuntimeError("device_unavailable") from e
        # Anything else propagates — implementation bug, NOT a runtime fault.
        raise e


# ---------------------------------------------------------------------------
# apply_phase3_labeling (spec §5.5, §6)
# ---------------------------------------------------------------------------


def _merge_response_phase3(
    seg: SubtaskSegment,
    resp: VLMResponse,
    visible_track_ids: list[str],
) -> SubtaskSegment:
    """Merge a VLMResponse into a SubtaskSegment using Phase 3 provenance fields."""
    seg.phase = resp["phase"]
    seg.verb = resp["verb"]
    seg.object = resp["object"]
    seg.target = resp["target"]
    seg.label_source = "vlm_with_object_state"
    seg.vlm_confidence = resp["vlm_confidence"]
    seg.evidence = resp["evidence"]
    if seg.phase in ("unlabeled", "unknown"):
        seg.overall_confidence = 0.0
    else:
        seg.overall_confidence = math.sqrt(
            max(seg.boundary_confidence, 0.0) * max(seg.vlm_confidence, 0.0)
        )
    seg.object_state_unavailable = False
    seg.object_track_ids = list(visible_track_ids)
    return seg


def apply_phase3_labeling(
    *,
    segments: list[SubtaskSegment],
    tracks: list[Any],
    object_signals: Any,
    extractor: Any,
    gripper: np.ndarray,
    eef_velocity: np.ndarray | None,
    episode_meta: dict[str, Any],
    config: VLMConfig,
    tracking_config: Any,
    labeler_factory: LabelerFactory,
    mask_cache: Any = None,
    mask_alpha: float = 0.4,
) -> tuple[list[SubtaskSegment], list[LabelAttempt], RunOutcome, float]:
    """Phase 3 labeling orchestrator (spec §5.5, §6).

    Per-segment: calls compute_object_state_summary; if None, falls back to
    Phase 2 path for that segment only (§6). Returns a 4-tuple:
    (labeled_segments, attempts_log, run_outcome, object_state_segment_coverage).

    object_state_segment_coverage = n_segments_with_object_state / n_segments_total.
    """
    from mimicanno.clip_features import compute_object_state_summary

    baseline = copy.deepcopy(segments)
    working = copy.deepcopy(segments)
    attempts: list[LabelAttempt] = []

    try:
        labeler = labeler_factory(config)
    except Exception as e:
        return baseline, [], RunOutcome(
            kind="degraded", degrade_reason="vlm_init_failed",
            underlying_error=repr(e),
        ), 0.0

    consecutive_runtime_failures = 0
    n = len(working)
    n_with_object_state = 0

    for idx, seg in enumerate(working):
        attempt_log = LabelAttempt(
            segment_id=seg.segment_id, attempt_count=0, final_status="ok",
        )
        attempts.append(attempt_log)

        # Compute per-segment object state summary (§5.2); None → fallback (§6.1)
        object_state_summary = compute_object_state_summary(
            tracks,
            segment_start_frame=seg.start_frame,
            segment_end_frame=seg.end_frame,
            object_signals=object_signals,
            config=tracking_config,
        )

        is_fallback = object_state_summary is None

        # Build VLMRequest — include object_state_summary only for Phase 3 segments
        request = _build_request(
            seg, segment_index=idx + 1, segment_total=n,
            extractor=extractor, gripper=gripper, eef_velocity=eef_velocity,
            keyframes_per_segment=config.keyframes_per_segment,
            episode_meta=episode_meta,
            mask_cache=mask_cache, mask_alpha=mask_alpha,
        )
        if not is_fallback:
            request["object_state_summary"] = object_state_summary
        else:
            # Explicit None → Phase 2 byte-identical prompt (§6.2 step 1)
            request["object_state_summary"] = None
            attempt_log.notes.append("phase3_per_segment_fallback")

        last_reject: RejectReason | None = None
        success = False
        for attempt in range(1, config.max_retries + 1):
            attempt_log.attempt_count = attempt
            try:
                resp = labeler.label_segment(
                    request, attempt=attempt,
                    last_reject_reason=last_reject,
                )
                consecutive_runtime_failures = 0
                if is_fallback:
                    _merge_response(seg, resp)
                else:
                    assert object_state_summary is not None  # narrowing
                    _merge_response_phase3(seg, resp, object_state_summary.visible_track_ids)
                attempt_log.final_status = "ok"
                attempt_log.response = resp
                success = True
                break
            except LabelerError as e:
                attempt_log.reject_reasons.append(e.reject_reason)
                last_reject = e.reject_reason
                continue
            except LabelerRuntimeError as e:
                attempt_log.runtime_errors.append(e.reason)
                if (idx == 0 and attempt == 1
                        and e.reason in ("model_unreachable", "device_unavailable")):
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_unreachable",
                        underlying_error=repr(e),
                    ), 0.0
                consecutive_runtime_failures += 1
                if consecutive_runtime_failures >= config.runtime_failure_threshold:
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_runtime_failed",
                        underlying_error=repr(e),
                    ), 0.0
                continue
        if not success:
            fallback_resp = VLMResponse(
                phase="unknown", verb=None, object=None, target=None,
                vlm_confidence=0.0, evidence=None,
            )
            _merge_response(seg, fallback_resp)
            attempt_log.final_status = "unknown_fallback"
            attempt_log.response = fallback_resp
        elif not is_fallback:
            n_with_object_state += 1

    coverage = n_with_object_state / n if n > 0 else 0.0
    return working, attempts, RunOutcome(kind="ok", degrade_reason=None,
                                          underlying_error=None), coverage
