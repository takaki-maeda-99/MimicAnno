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
from dataclasses import dataclass, field
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
    object_state_segment_coverage: float | None = None  # Phase 3 only; absent for Phase 1/2 (§6.3)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "object_state_available": self.object_state_available,
            "degraded_from_phase": self.degraded_from_phase,
            "degrade_reason": self.degrade_reason,
        }
        if self.object_state_segment_coverage is not None:
            d["object_state_segment_coverage"] = self.object_state_segment_coverage
        return d


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


SmoothingOpName = Literal[
    "merge_same_label", "merge_short", "viterbi_relabel", "edited",
]
_ALLOWED_SMOOTHING_OPS: frozenset[str] = frozenset({
    "merge_same_label", "merge_short", "viterbi_relabel", "edited",
})


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
    # Phase 4 — additive, default empty for Phase 1/2/3 lineage (spec §4.1).
    # Allowed entries: "merge_same_label", "merge_short", "viterbi_relabel".
    smoothing_ops: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Reject None for list fields — the schema is opinionated to avoid
        # downstream None-checks. Empty list is the valid sentinel.
        if self.failure_flags is None:
            raise TypeError("failure_flags must be list[str], not None")
        if self.object_track_ids is None:
            raise TypeError("object_track_ids must be list[str], not None")
        if self.smoothing_ops is None:
            raise TypeError("smoothing_ops must be list[str], not None")
        for op in self.smoothing_ops:
            if op not in _ALLOWED_SMOOTHING_OPS:
                raise ValueError(f"unknown smoothing op: {op!r}")

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
            "smoothing_ops": list(self.smoothing_ops),
        }

    def to_sidecar_row(self) -> dict[str, Any]:
        """Flat row dict for ``meta/mimicanno_segments.parquet`` (spec §3.1).

        Emits the segment-derived columns. Provenance columns
        (``episode_index``, ``segment_index``, ``run_hash``, ``config_hash``,
        ``input_hash``, ``pipeline_phase``, ``mimicanno_version``,
        ``generated_at``) are added by the sink writer using the manifest /
        ``CanonicalEpisode`` context.

        Per-edge per-source ``BoundaryRef`` scores beyond ``score`` /
        ``sources`` are not represented (lossy; they live in
        ``boundaries.json``, see spec §3.3).
        """
        return {
            "segment_id": self.segment_id,
            "phase": self.phase,
            "verb": self.verb,
            "object": self.object,
            "target": self.target,
            "failure_flags": list(self.failure_flags),
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "label_source": self.label_source,
            "object_state_unavailable": self.object_state_unavailable,
            "object_track_ids": list(self.object_track_ids),
            "label_version": self.label_version,
            "boundary_confidence": self.boundary_confidence,
            "vlm_confidence": self.vlm_confidence,
            "overall_confidence": self.overall_confidence,
            "evidence": self.evidence,
            "reviewed": self.reviewed,
            "reviewer_id": self.reviewer_id,
            "smoothing_ops": list(self.smoothing_ops),
            "boundary_source_start": list(self.start_boundary.sources),
            "boundary_source_end": list(self.end_boundary.sources),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SubtaskSegment:
        """Inverse of :meth:`to_sidecar_row`.

        Rebuilds a SubtaskSegment from a sidecar row. The row may carry
        provenance columns (``episode_index``, ``run_hash``, etc.) from the
        sink writer; those are ignored here. Per-edge per-source BoundaryRef
        scores are not recoverable from the sidecar (lossy field, spec §3.3) —
        the reconstructed BoundaryRefs carry ``candidate_id=None``,
        ``time=start_time`` (or ``end_time`` for the end edge) and
        ``score=boundary_confidence``. Reading ``boundaries.json`` from the
        original run dir is required to recover the per-source detail.

        ``episode_id`` is also not on the segment-level columns; callers that
        need it should pass it via the surrounding ``CanonicalEpisode``.
        We use ``""`` as the sidecar-roundtrip-only sentinel because the row
        does not carry it. Round-trippers that care should set
        ``episode_id`` on the reconstructed segment after the fact.
        """
        boundary_confidence = float(row["boundary_confidence"])
        start_boundary = BoundaryRef(
            candidate_id=None,
            time=float(row["start_time"]),
            sources=list(row["boundary_source_start"]),
            score=boundary_confidence,
        )
        end_boundary = BoundaryRef(
            candidate_id=None,
            time=float(row["end_time"]),
            sources=list(row["boundary_source_end"]),
            score=boundary_confidence,
        )
        vlm_conf_raw = row.get("vlm_confidence")
        vlm_conf = None if vlm_conf_raw is None else float(vlm_conf_raw)
        return cls(
            segment_id=str(row["segment_id"]),
            episode_id=str(row.get("episode_id", "")),
            start_frame=int(row["start_frame"]),
            end_frame=int(row["end_frame"]),
            start_time=float(row["start_time"]),
            end_time=float(row["end_time"]),
            phase=str(row["phase"]),
            verb=row["verb"],
            object=row["object"],
            target=row["target"],
            failure_flags=list(row["failure_flags"]),
            label_source=row["label_source"],
            object_state_unavailable=bool(row["object_state_unavailable"]),
            object_track_ids=list(row["object_track_ids"]),
            label_version=str(row["label_version"]),
            start_boundary=start_boundary,
            end_boundary=end_boundary,
            boundary_confidence=boundary_confidence,
            vlm_confidence=vlm_conf,
            overall_confidence=float(row["overall_confidence"]),
            evidence=row["evidence"],
            reviewed=bool(row["reviewed"]),
            reviewer_id=row["reviewer_id"],
            smoothing_ops=list(row["smoothing_ops"]),
        )


@dataclass(slots=True)
class SmoothingSummary:
    """Phase 4 smoothing summary block (spec §4.3).

    Emitted as ``manifest.smoothing_summary`` only on Phase 4 runs; absent on
    Phase 1/2/3 manifests (where ``Manifest.smoothing_summary is None`` and
    serialization omits the key entirely).
    """

    initial_segment_count: int
    final_segment_count: int
    merge_same_label_rounds: int
    merge_same_label_collapses: int
    merge_short_absorbs: int
    viterbi_relabels: int
    viterbi_skipped: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_segment_count": self.initial_segment_count,
            "final_segment_count": self.final_segment_count,
            "merge_same_label_rounds": self.merge_same_label_rounds,
            "merge_same_label_collapses": self.merge_same_label_collapses,
            "merge_short_absorbs": self.merge_short_absorbs,
            "viterbi_relabels": self.viterbi_relabels,
            "viterbi_skipped": self.viterbi_skipped,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SmoothingSummary:
        return cls(
            initial_segment_count=int(d["initial_segment_count"]),
            final_segment_count=int(d["final_segment_count"]),
            merge_same_label_rounds=int(d["merge_same_label_rounds"]),
            merge_same_label_collapses=int(d["merge_same_label_collapses"]),
            merge_short_absorbs=int(d["merge_short_absorbs"]),
            viterbi_relabels=int(d["viterbi_relabels"]),
            viterbi_skipped=bool(d["viterbi_skipped"]),
        )


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
    # Phase 4 only — None on Phase 1/2/3 manifests; key omitted from to_dict
    # output when None to preserve forward-compat with older readers (spec §4.3).
    smoothing_summary: SmoothingSummary | None = None
    # Phase 5 B r1 — canonical_name materializes the run's dir name into the
    # manifest so post-edit readers don't have to derive it from disk path
    # (spec 2026-05-13-phase5-B §3.3). edited_at carries the latest human
    # PATCH time (§3.2 step 7). Both conditionally emitted to keep pre-r1
    # manifests byte-identical (load-bearing for T4's hash invariant).
    canonical_name: str | None = None
    edited_at: str | None = None

    def artifact(self, role: str) -> Artifact:
        for a in self.artifacts:
            if a.role == role:
                return a
        raise KeyError(f"no artifact with role={role!r}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
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
        if self.smoothing_summary is not None:
            d["smoothing_summary"] = self.smoothing_summary.to_dict()
        if self.canonical_name is not None:
            d["canonical_name"] = self.canonical_name
        if self.edited_at is not None:
            d["edited_at"] = self.edited_at
        return d


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


def _is_int(x: Any) -> bool:
    """Return True iff *x* is a plain int (not bool — isinstance(True, int) is True)."""
    return isinstance(x, int) and not isinstance(x, bool)


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
        if not _is_int(frame) or frame < 0 or frame >= n_frames:
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
        if not _is_int(from_frame) or from_frame < 0 or from_frame >= n_frames:
            raise ValueError(
                f"gap from_frame={from_frame!r} is out of [0, n_frames={n_frames})"
            )
        if not _is_int(to_frame) or to_frame < 0 or to_frame >= n_frames:
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
        if not _is_int(index) or index < 0:
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
        for i in range(1, len(gap_events)):
            prev, curr = gap_events[i - 1], gap_events[i]
            if prev.to_frame >= curr.from_frame:
                raise ValueError(
                    f"gap_events must be strictly frame-ascending and non-overlapping; "
                    f"got prev.to_frame={prev.to_frame} >= curr.from_frame={curr.from_frame}"
                )
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
            role = str(entry["role"])
            if role not in _VALID_ROLES:
                raise ValueError(
                    f"failed_prompts role={role!r} must be one of {sorted(_VALID_ROLES)}"
                )
            failed.append((role, str(entry["prompt"])))
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
        if not _is_int(n_frames) or n_frames < 1:
            raise ValueError(f"n_frames={n_frames!r} must be int >= 1")
        image_size = d["image_size"]
        width = image_size["width"]
        height = image_size["height"]
        if not _is_int(width) or width <= 0:
            raise ValueError(f"image_size.width={width!r} must be int > 0")
        if not _is_int(height) or height <= 0:
            raise ValueError(f"image_size.height={height!r} must be int > 0")
        stride = d["track_stride_frames"]
        if not _is_int(stride) or stride < 1:
            raise ValueError(f"track_stride_frames={stride!r} must be int >= 1")
        tracking_plan = TracksTrackingPlan.from_dict(d["tracking_plan"])
        tracks = [TracksTrack.from_dict(t, n_frames=n_frames) for t in d["tracks"]]
        # Validate track_id uniqueness within file
        seen_ids: set[str] = set()
        for t in tracks:
            if t.track_id in seen_ids:
                raise ValueError(
                    f"track_id={t.track_id!r} appears more than once within the file"
                )
            seen_ids.add(t.track_id)
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


@dataclass(slots=True)
class ObjectStateSummary:
    """Per-segment object/target/tool state derived from SAM3 tracks.
    Used as the Phase 3 add-on to ClipFeatures and the VLM prompt."""

    object_prompts: list[str]                       # visible >= visibility_threshold of seg
    target_prompts: list[str]
    tool_prompts:   list[str]                       # may be []

    visible_track_ids: list[str]                    # track_ids that passed visibility filter (§5.5)

    gripper_object_distance_at_start: float | None  # primary pair, image-width-normalized
    gripper_object_distance_at_end:   float | None
    gripper_object_distance_min:      float | None

    primary_object_displacement: float | None       # image-width-normalized
    primary_object_max_speed:    float | None       # image-width-normalized / sec

    primary_object_at_target_at_end: bool | None    # bbox-IoU(obj_0, tgt_0) at last frame > 0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_prompts": list(self.object_prompts),
            "target_prompts": list(self.target_prompts),
            "tool_prompts": list(self.tool_prompts),
            "visible_track_ids": list(self.visible_track_ids),
            "gripper_object_distance_at_start": self.gripper_object_distance_at_start,
            "gripper_object_distance_at_end": self.gripper_object_distance_at_end,
            "gripper_object_distance_min": self.gripper_object_distance_min,
            "primary_object_displacement": self.primary_object_displacement,
            "primary_object_max_speed": self.primary_object_max_speed,
            "primary_object_at_target_at_end": self.primary_object_at_target_at_end,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ObjectStateSummary:
        return cls(
            object_prompts=list(d["object_prompts"]),
            target_prompts=list(d["target_prompts"]),
            tool_prompts=list(d["tool_prompts"]),
            visible_track_ids=list(d.get("visible_track_ids", [])),
            gripper_object_distance_at_start=(
                float(d["gripper_object_distance_at_start"])
                if d["gripper_object_distance_at_start"] is not None
                else None
            ),
            gripper_object_distance_at_end=(
                float(d["gripper_object_distance_at_end"])
                if d["gripper_object_distance_at_end"] is not None
                else None
            ),
            gripper_object_distance_min=(
                float(d["gripper_object_distance_min"])
                if d["gripper_object_distance_min"] is not None
                else None
            ),
            primary_object_displacement=(
                float(d["primary_object_displacement"])
                if d["primary_object_displacement"] is not None
                else None
            ),
            primary_object_max_speed=(
                float(d["primary_object_max_speed"])
                if d["primary_object_max_speed"] is not None
                else None
            ),
            primary_object_at_target_at_end=(
                bool(d["primary_object_at_target_at_end"])
                if d["primary_object_at_target_at_end"] is not None
                else None
            ),
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
