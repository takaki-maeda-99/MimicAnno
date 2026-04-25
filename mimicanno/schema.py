"""Versioned dataclasses for every JSON shape that hits disk.

Each dataclass exposes ``to_dict()`` returning a JSON-ready Python object
(only str/int/float/bool/None/list/dict). Use ``json.dumps`` (or
``mimicanno.hashing.canonical_json`` for hashing) on the result.

We deliberately use plain ``@dataclass`` rather than pydantic / msgspec —
this code has no validation needs that can't be served by ``jsonschema``
at the I/O boundary, and avoiding the third-party dep simplifies install.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class TaskInfo:
    text: str
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "version": self.version}


@dataclass(slots=True)
class GeneratorInfo:
    name: str
    cli_version: str
    pipeline_phase: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cli_version": self.cli_version,
            "pipeline_phase": self.pipeline_phase,
        }


@dataclass(slots=True)
class InputRef:
    path: str
    sha256: str  # Always prefixed "sha256:"

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(slots=True)
class Artifact:
    role: str
    url: str
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "url": self.url, "content_type": self.content_type}


@dataclass(slots=True)
class PipelineStatus:
    object_state_available: bool
    degraded_from_phase: int | None
    degrade_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_state_available": self.object_state_available,
            "degraded_from_phase": self.degraded_from_phase,
            "degrade_reason": self.degrade_reason,
        }


@dataclass(slots=True)
class BoundaryRef:
    """Per-edge reference attached to a SubtaskSegment (spec §6.1).

    ``candidate_id`` is None for sentinel boundaries (episode_start, episode_end);
    in that case ``sources`` holds ``["episode_start"]`` or ``["episode_end"]``
    and ``score`` is 1.0.
    """
    candidate_id: str | None
    time: float
    sources: list[str]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "time": self.time,
            "sources": list(self.sources),
            "score": self.score,
        }


@dataclass(slots=True)
class BoundaryCandidate:
    """A boundary candidate emitted by the integrated-score detector (spec §5.4)."""
    id: str
    frame: int
    time: float
    sources: list[str]
    scores: dict[str, float]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "frame": self.frame,
            "time": self.time,
            "sources": list(self.sources),
            "scores": dict(self.scores),
            "score": self.score,
        }


LabelSource = Literal[
    "signals_only",
    "vlm_robot_state_only",
    "vlm_with_object_state",
    "human_edit",
]


@dataclass(slots=True)
class SubtaskSegment:
    """One labeled (or, in Phase 1, ``unlabeled``) clip in a timeline."""
    segment_id: str
    episode_id: str
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    phase: str
    verb: str | None
    object: str | None
    target: str | None
    failure_flags: list[str]
    label_source: LabelSource
    object_state_unavailable: bool
    object_track_ids: list[str]
    label_version: str
    start_boundary: BoundaryRef
    end_boundary: BoundaryRef
    boundary_confidence: float
    vlm_confidence: float | None
    overall_confidence: float
    evidence: str | None
    reviewed: bool
    reviewer_id: str | None

    def __post_init__(self) -> None:
        # Reject None for list fields — the schema is opinionated to avoid
        # downstream None-checks. Empty list is the valid sentinel.
        if self.failure_flags is None:  # type: ignore[unreachable]
            raise TypeError("failure_flags must be list[str], not None")
        if self.object_track_ids is None:  # type: ignore[unreachable]
            raise TypeError("object_track_ids must be list[str], not None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "episode_id": self.episode_id,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "phase": self.phase,
            "verb": self.verb,
            "object": self.object,
            "target": self.target,
            "failure_flags": list(self.failure_flags),
            "label_source": self.label_source,
            "object_state_unavailable": self.object_state_unavailable,
            "object_track_ids": list(self.object_track_ids),
            "label_version": self.label_version,
            "start_boundary": self.start_boundary.to_dict(),
            "end_boundary": self.end_boundary.to_dict(),
            "boundary_confidence": self.boundary_confidence,
            "vlm_confidence": self.vlm_confidence,
            "overall_confidence": self.overall_confidence,
            "evidence": self.evidence,
            "reviewed": self.reviewed,
            "reviewer_id": self.reviewer_id,
        }


@dataclass(slots=True)
class Manifest:
    schema_version: str
    episode_id: str
    task: TaskInfo
    generated_at: str
    generator: GeneratorInfo
    config_hash: str
    input_hash: str
    run_hash: str
    model_versions: dict[str, str | None]
    pipeline_params: dict[str, Any]
    inputs: dict[str, InputRef]
    time_base: str
    fps: float
    duration_sec: float
    pipeline_status: PipelineStatus
    compat: dict[str, int]
    artifacts: list[Artifact]

    def artifact(self, role: str) -> Artifact:
        for a in self.artifacts:
            if a.role == role:
                return a
        raise KeyError(f"no artifact with role={role!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "task": self.task.to_dict(),
            "generated_at": self.generated_at,
            "generator": self.generator.to_dict(),
            "config_hash": self.config_hash,
            "input_hash": self.input_hash,
            "run_hash": self.run_hash,
            "model_versions": dict(self.model_versions),
            "pipeline_params": _deep_jsonify(self.pipeline_params),
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "time_base": self.time_base,
            "fps": self.fps,
            "duration_sec": self.duration_sec,
            "pipeline_status": self.pipeline_status.to_dict(),
            "compat": dict(self.compat),
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


@dataclass(slots=True)
class AnnotationResult:
    schema_version: str
    episode_id: str
    task: TaskInfo
    generated_at: str
    generator: GeneratorInfo
    config_hash: str
    input_hash: str
    run_hash: str
    model_versions: dict[str, str | None]
    pipeline_phase: int
    pipeline_status: PipelineStatus
    segments: list[SubtaskSegment]
    boundaries_url: str
    signals_url: str
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "task": self.task.to_dict(),
            "generated_at": self.generated_at,
            "generator": self.generator.to_dict(),
            "config_hash": self.config_hash,
            "input_hash": self.input_hash,
            "run_hash": self.run_hash,
            "model_versions": dict(self.model_versions),
            "pipeline_phase": self.pipeline_phase,
            "pipeline_status": self.pipeline_status.to_dict(),
            "segments": [s.to_dict() for s in self.segments],
            "boundaries_url": self.boundaries_url,
            "signals_url": self.signals_url,
            "notes": self.notes,
        }


def _deep_jsonify(value: Any) -> Any:
    """Recursively convert nested dataclasses inside dict/list to dicts.

    Used for ``pipeline_params`` which is a free-form nested dict in the spec.
    """
    if isinstance(value, dict):
        return {k: _deep_jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_jsonify(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    return value
