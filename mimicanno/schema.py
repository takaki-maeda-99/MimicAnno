"""Versioned dataclasses for every JSON shape that hits disk.

Each dataclass exposes ``to_dict()`` returning a JSON-ready Python object
(only str/int/float/bool/None/list/dict). Use ``json.dumps`` (or
``mimicanno.hashing.canonical_json`` for hashing) on the result.

We deliberately use plain ``@dataclass`` rather than pydantic / msgspec —
this code has no validation needs that can't be served by ``jsonschema``
at the I/O boundary, and avoiding the third-party dep simplifies install.
"""

from __future__ import annotations

import math
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
        if self.failure_flags is None:
            raise TypeError("failure_flags must be list[str], not None")
        if self.object_track_ids is None:
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


# ---------------------------------------------------------------------------
# Phase 3 wire-format dataclasses (spec §3)
# ---------------------------------------------------------------------------

_TRACKS_SCHEMA_VERSION = "0.1.0"
_VALID_ROLES = frozenset({"object", "target", "tool"})
_VALID_GAP_REASONS = frozenset({"sam3_lost", "sam3_low_conf"})


@dataclass(slots=True)
class TracksSample:
    """One propagation sample (spec §3.2)."""

    frame: int
    time_sec: float
    bbox: list[float]  # [x, y, w, h] — all in [0, 1]; w > 0; h > 0; x+w ≤ 1; y+h ≤ 1
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "time_sec": self.time_sec,
            "bbox": list(self.bbox),
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, n_frames: int) -> TracksSample:
        frame = d["frame"]
        if not isinstance(frame, int) or frame < 0 or frame >= n_frames:
            raise ValueError(
                f"sample frame={frame!r} is out of [0, n_frames={n_frames})"
            )
        score = float(d["score"])
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"sample score={score!r} must be in [0, 1]")
        bbox = list(d["bbox"])
        _validate_bbox(bbox)
        return cls(frame=frame, time_sec=float(d["time_sec"]), bbox=bbox, score=score)


def _validate_bbox(bbox: list[float]) -> None:
    if len(bbox) != 4:
        raise ValueError(f"bbox must have 4 elements [x,y,w,h], got {len(bbox)}")
    x, y, w, h = bbox
    if w <= 0.0 or h <= 0.0:
        raise ValueError(f"bbox w and h must be > 0; got w={w}, h={h}")
    if x < 0.0 or x + w > 1.0 + 1e-9:
        raise ValueError(f"bbox x out of unit square: x={x}, w={w}")
    if y < 0.0 or y + h > 1.0 + 1e-9:
        raise ValueError(f"bbox y out of unit square: y={y}, h={h}")


@dataclass(slots=True)
class TracksGap:
    """One gap event (spec §3.2)."""

    from_frame: int
    to_frame: int
    reason: str  # "sam3_lost" | "sam3_low_conf"

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_frame": self.from_frame,
            "to_frame": self.to_frame,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, n_frames: int) -> TracksGap:
        from_frame = d["from_frame"]
        to_frame = d["to_frame"]
        reason = d["reason"]
        if not isinstance(from_frame, int) or from_frame < 0 or from_frame >= n_frames:
            raise ValueError(
                f"gap from_frame={from_frame!r} is out of [0, n_frames={n_frames})"
            )
        if not isinstance(to_frame, int) or to_frame < 0 or to_frame >= n_frames:
            raise ValueError(
                f"gap to_frame={to_frame!r} is out of [0, n_frames={n_frames})"
            )
        if from_frame > to_frame:
            raise ValueError(
                f"gap from_frame={from_frame} > to_frame={to_frame}"
            )
        if reason not in _VALID_GAP_REASONS:
            raise ValueError(
                f"gap reason={reason!r} must be one of {sorted(_VALID_GAP_REASONS)}"
            )
        return cls(from_frame=from_frame, to_frame=to_frame, reason=reason)


@dataclass(slots=True)
class TracksTrack:
    """One full track entry (spec §3.2)."""

    track_id: str
    role: str  # "object" | "target" | "tool"
    prompt: str
    slug: str
    index: int
    primary: bool
    samples: list[TracksSample]
    gap_events: list[TracksGap]

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "role": self.role,
            "prompt": self.prompt,
            "slug": self.slug,
            "index": self.index,
            "primary": self.primary,
            "samples": [s.to_dict() for s in self.samples],
            "gap_events": [g.to_dict() for g in self.gap_events],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, n_frames: int) -> TracksTrack:
        role = d["role"]
        if role not in _VALID_ROLES:
            raise ValueError(f"track role={role!r} must be one of {sorted(_VALID_ROLES)}")
        index = d["index"]
        if not isinstance(index, int) or index < 0:
            raise ValueError(f"track index={index!r} must be int >= 0")
        samples = [TracksSample.from_dict(s, n_frames=n_frames) for s in d["samples"]]
        # Validate strict frame-ascending order
        for i in range(1, len(samples)):
            if samples[i].frame <= samples[i - 1].frame:
                raise ValueError(
                    f"samples must be strictly ascending in frame; "
                    f"frame[{i}]={samples[i].frame} <= frame[{i - 1}]={samples[i - 1].frame}"
                )
        gap_events = [TracksGap.from_dict(g, n_frames=n_frames) for g in d["gap_events"]]
        return cls(
            track_id=str(d["track_id"]),
            role=role,
            prompt=str(d["prompt"]),
            slug=str(d["slug"]),
            index=index,
            primary=bool(d["primary"]),
            samples=samples,
            gap_events=gap_events,
        )


@dataclass(slots=True)
class TracksTrackingPlan:
    """Tracking plan wire format (spec §3.2)."""

    task_text: str
    object_prompts: list[str]
    target_prompts: list[str]
    tool_prompts: list[str]
    # Each entry is (role, prompt); preserved as list[{role, prompt}] on disk
    failed_prompts: list[tuple[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_text": self.task_text,
            "object_prompts": list(self.object_prompts),
            "target_prompts": list(self.target_prompts),
            "tool_prompts": list(self.tool_prompts),
            "failed_prompts": [
                {"role": role, "prompt": prompt}
                for role, prompt in self.failed_prompts
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TracksTrackingPlan:
        failed: list[tuple[str, str]] = []
        for entry in d.get("failed_prompts", []):
            failed.append((str(entry["role"]), str(entry["prompt"])))
        return cls(
            task_text=str(d["task_text"]),
            object_prompts=list(d.get("object_prompts", [])),
            target_prompts=list(d.get("target_prompts", [])),
            tool_prompts=list(d.get("tool_prompts", [])),
            failed_prompts=failed,
        )


@dataclass(slots=True)
class TracksStats:
    """Stats block (spec §3.2)."""

    n_tracks: int
    n_samples_total: int
    mean_track_score: float  # NaN serialized as None
    tracking_wall_time_sec: float

    def to_dict(self) -> dict[str, Any]:
        mean: float | None = None if math.isnan(self.mean_track_score) else self.mean_track_score
        return {
            "n_tracks": self.n_tracks,
            "n_samples_total": self.n_samples_total,
            "mean_track_score": mean,
            "tracking_wall_time_sec": self.tracking_wall_time_sec,
        }

    @classmethod
    def from_dict(
        cls,
        d: dict[str, Any],
        *,
        expected_n_tracks: int,
        expected_n_samples: int,
    ) -> TracksStats:
        n_tracks = d["n_tracks"]
        if n_tracks != expected_n_tracks:
            raise ValueError(
                f"stats.n_tracks={n_tracks} does not match len(tracks)={expected_n_tracks}"
            )
        n_samples_total = d["n_samples_total"]
        if n_samples_total != expected_n_samples:
            raise ValueError(
                f"stats.n_samples_total={n_samples_total} does not match "
                f"sum of samples={expected_n_samples}"
            )
        wall_time = float(d["tracking_wall_time_sec"])
        if wall_time < 0.0:
            raise ValueError(
                f"stats.tracking_wall_time_sec={wall_time!r} must be >= 0"
            )
        raw_mean = d.get("mean_track_score")
        mean_score = float("nan") if raw_mean is None else float(raw_mean)
        return cls(
            n_tracks=n_tracks,
            n_samples_total=n_samples_total,
            mean_track_score=mean_score,
            tracking_wall_time_sec=wall_time,
        )


@dataclass(slots=True)
class TracksFile:
    """Top-level tracks.json wire format (spec §3)."""

    schema_version: str
    episode_id: str
    fps: float
    n_frames: int
    image_width: int
    image_height: int
    track_stride_frames: int
    tracking_plan: TracksTrackingPlan
    tracks: list[TracksTrack]
    stats: TracksStats

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "fps": self.fps,
            "n_frames": self.n_frames,
            "image_size": {"width": self.image_width, "height": self.image_height},
            "track_stride_frames": self.track_stride_frames,
            "tracking_plan": self.tracking_plan.to_dict(),
            "tracks": [t.to_dict() for t in self.tracks],
            "stats": self.stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TracksFile:
        schema_version = d.get("schema_version", "")
        if schema_version != _TRACKS_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version={schema_version!r} must be {_TRACKS_SCHEMA_VERSION!r}"
            )
        fps = float(d["fps"])
        if fps <= 0.0:
            raise ValueError(f"fps={fps!r} must be > 0")
        n_frames = d["n_frames"]
        if not isinstance(n_frames, int) or n_frames < 1:
            raise ValueError(f"n_frames={n_frames!r} must be int >= 1")
        image_size = d["image_size"]
        width = image_size["width"]
        height = image_size["height"]
        if not isinstance(width, int) or width <= 0:
            raise ValueError(f"image_size.width={width!r} must be int > 0")
        if not isinstance(height, int) or height <= 0:
            raise ValueError(f"image_size.height={height!r} must be int > 0")
        stride = d["track_stride_frames"]
        if not isinstance(stride, int) or stride < 1:
            raise ValueError(f"track_stride_frames={stride!r} must be int >= 1")
        tracking_plan = TracksTrackingPlan.from_dict(d["tracking_plan"])
        tracks = [TracksTrack.from_dict(t, n_frames=n_frames) for t in d["tracks"]]
        # Validate at-most-one primary per role
        primary_roles: set[str] = set()
        for t in tracks:
            if t.primary:
                if t.role in primary_roles:
                    raise ValueError(
                        f"primary=true set on more than one track for role={t.role!r}"
                    )
                primary_roles.add(t.role)
        n_samples = sum(len(t.samples) for t in tracks)
        stats = TracksStats.from_dict(
            d["stats"],
            expected_n_tracks=len(tracks),
            expected_n_samples=n_samples,
        )
        return cls(
            schema_version=schema_version,
            episode_id=str(d["episode_id"]),
            fps=fps,
            n_frames=n_frames,
            image_width=width,
            image_height=height,
            track_stride_frames=stride,
            tracking_plan=tracking_plan,
            tracks=tracks,
            stats=stats,
        )


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
