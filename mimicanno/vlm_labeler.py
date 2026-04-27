"""Phase 2 VLMLabeler protocol, types, exception classes, and label_run
orchestrator (spec §2.1 + §2.3).

This file is the contract surface. Concrete implementations
(FixtureVLMLabeler, LocalGemmaVLMLabeler) and the orchestrator land in
later tasks.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict, get_args

import numpy as np


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
    robot_state_summary: dict   # see clip_features.RobotStateSummary


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
