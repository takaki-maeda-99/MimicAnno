"""Phase 2 VLMLabeler protocol, types, exception classes, and label_run
orchestrator (spec §2.1 + §2.3).

This file is the contract surface. Concrete implementations
(FixtureVLMLabeler, LocalGemmaVLMLabeler) and the orchestrator land in
later tasks.
"""
from __future__ import annotations

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
