"""Public I/O helpers for MimicAnno artifacts.

Exposes:
- ``write_json_atomic`` — primitive atomic JSON write (writers.py re-exports this)
- ``write_tracks_json`` / ``read_tracks_json`` — Phase 3 tracks.json I/O (spec §3)
- ``read_manifest`` / ``read_annotation_result`` — Phase 5 export reads the
  ``manifest.json`` / ``annotation.json`` of a published mimicanno run via these
  loaders (spec §2.3 step 1). Symmetric inverses of
  ``writers.write_manifest_json`` / ``writers.write_annotation_json``.
"""

from __future__ import annotations

import json
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from mimicanno.errors import ArtifactIntegrityError, ErrorCode, MimicAnnoError
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    BoundaryRef,
    EditEvent,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    SmoothingSummary,
    SubtaskSegment,
    TaskInfo,
    TracksFile,
)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write *payload* as JSON to *path* via tmp-file replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def write_tracks_json(path: Path, tracks: TracksFile) -> None:
    """Serialize and atomically write a ``tracks.json`` artifact (spec §3)."""
    write_json_atomic(path, tracks.to_dict())


def read_tracks_json(
    path: Path,
    *,
    expected: tuple[str, float, int] | None = None,
) -> TracksFile:
    """Read and validate a ``tracks.json`` artifact (spec §3).

    Parameters
    ----------
    path:
        Filesystem path to ``tracks.json``.
    expected:
        Optional ``(episode_id, fps, n_frames)`` tuple taken from ``manifest.json``.
        When provided, the values are compared against the file and
        ``ArtifactIntegrityError`` is raised on any mismatch (spec §3.3).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    tf = TracksFile.from_dict(raw)

    if expected is not None:
        exp_episode_id, exp_fps, exp_n_frames = expected
        if tf.episode_id != exp_episode_id:
            raise ArtifactIntegrityError("episode_id", exp_episode_id, tf.episode_id)
        if tf.fps != exp_fps:
            raise ArtifactIntegrityError("fps", exp_fps, tf.fps)
        if tf.n_frames != exp_n_frames:
            raise ArtifactIntegrityError("n_frames", exp_n_frames, tf.n_frames)

    return tf


# ---------------------------------------------------------------------------
# manifest.json / annotation.json loaders (Phase 5 export, spec §2.3)
# ---------------------------------------------------------------------------


def _load_schema(name: str) -> dict[str, Any]:
    text = pkg_files("mimicanno.jsonschemas").joinpath(f"{name}.schema.json").read_text()
    return json.loads(text)  # type: ignore[no-any-return]


def _validate(name: str, data: dict[str, Any]) -> None:
    try:
        jsonschema.validate(instance=data, schema=_load_schema(name))
    except jsonschema.ValidationError as e:
        raise MimicAnnoError(
            ErrorCode.EXPORT_PROFILE_INVALID,  # generic schema-violation code reused
            f"{name}.json schema violation: {e.message}",
            {"json_path": list(e.absolute_path)},
        ) from e


def _boundary_from_dict(d: dict[str, Any]) -> BoundaryRef:
    return BoundaryRef(
        candidate_id=d.get("candidate_id"),
        time=float(d["time"]),
        sources=list(d["sources"]),
        score=float(d["score"]),
    )


def _segment_from_dict(d: dict[str, Any]) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id=str(d["segment_id"]),
        episode_id=str(d["episode_id"]),
        start_frame=int(d["start_frame"]),
        end_frame=int(d["end_frame"]),
        start_time=float(d["start_time"]),
        end_time=float(d["end_time"]),
        phase=str(d["phase"]),
        verb=d.get("verb"),
        object=d.get("object"),
        target=d.get("target"),
        failure_flags=list(d.get("failure_flags", [])),
        label_source=d["label_source"],
        object_state_unavailable=bool(d["object_state_unavailable"]),
        object_track_ids=list(d.get("object_track_ids", [])),
        label_version=str(d["label_version"]),
        start_boundary=_boundary_from_dict(d["start_boundary"]),
        end_boundary=_boundary_from_dict(d["end_boundary"]),
        boundary_confidence=float(d["boundary_confidence"]),
        vlm_confidence=(
            None if d.get("vlm_confidence") is None else float(d["vlm_confidence"])
        ),
        overall_confidence=float(d["overall_confidence"]),
        evidence=d.get("evidence"),
        reviewed=bool(d["reviewed"]),
        reviewer_id=d.get("reviewer_id"),
        smoothing_ops=list(d.get("smoothing_ops", [])),
    )


def _pipeline_status_from_dict(d: dict[str, Any]) -> PipelineStatus:
    return PipelineStatus(
        object_state_available=bool(d["object_state_available"]),
        degraded_from_phase=d.get("degraded_from_phase"),
        degrade_reason=d.get("degrade_reason"),
        object_state_segment_coverage=d.get("object_state_segment_coverage"),
    )


def read_manifest(path: Path) -> Manifest:
    """Load and validate a ``manifest.json`` artifact.

    Used by the Phase 5 exporter to read ``runs/<canonical>/manifest.json``
    (spec §2.3 step 1). Validates against ``mimicanno.jsonschemas.manifest``;
    schema violations raise ``MimicAnnoError`` with code
    ``EXPORT_PROFILE_INVALID`` (the generic schema-violation code).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate("manifest", raw)
    inputs = {
        k: InputRef(path=str(v["path"]), sha256=str(v["sha256"]))
        for k, v in raw["inputs"].items()
    }
    artifacts = [
        Artifact(role=a["role"], url=a["url"], content_type=a["content_type"])
        for a in raw["artifacts"]
    ]
    smoothing_summary = (
        SmoothingSummary.from_dict(raw["smoothing_summary"])
        if "smoothing_summary" in raw
        else None
    )
    # Phase 5 B r1: canonical_name fallback. `or` would swallow empty
    # string into the dir-name fallback; require an explicit non-empty
    # string instead (T15 typing note).
    canonical_name_raw = raw.get("canonical_name")
    canonical_name = (
        canonical_name_raw
        if isinstance(canonical_name_raw, str) and canonical_name_raw
        else path.parent.name
    )
    edited_at_raw = raw.get("edited_at")
    edited_at = edited_at_raw if isinstance(edited_at_raw, str) else None

    return Manifest(
        schema_version=str(raw["schema_version"]),
        episode_id=str(raw["episode_id"]),
        task=TaskInfo(
            text=str(raw["task"]["text"]),
            version=raw["task"].get("version"),
        ),
        generated_at=str(raw["generated_at"]),
        generator=GeneratorInfo(
            name=str(raw["generator"]["name"]),
            cli_version=str(raw["generator"]["cli_version"]),
            pipeline_phase=int(raw["generator"]["pipeline_phase"]),
        ),
        config_hash=str(raw["config_hash"]),
        input_hash=str(raw["input_hash"]),
        run_hash=str(raw["run_hash"]),
        model_versions=dict(raw["model_versions"]),
        pipeline_params=dict(raw["pipeline_params"]),
        inputs=inputs,
        time_base=str(raw["time_base"]),
        fps=float(raw["fps"]),
        duration_sec=float(raw["duration_sec"]),
        pipeline_status=_pipeline_status_from_dict(raw["pipeline_status"]),
        compat=dict(raw["compat"]),
        artifacts=artifacts,
        smoothing_summary=smoothing_summary,
        canonical_name=canonical_name,
        edited_at=edited_at,
    )


def read_annotation_result(path: Path) -> AnnotationResult:
    """Load and validate an ``annotation.json`` artifact.

    Used by the Phase 5 exporter (spec §2.3 step 1). Validates against
    ``mimicanno.jsonschemas.annotation``; schema violations raise
    ``MimicAnnoError`` with code ``EXPORT_PROFILE_INVALID``.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate("annotation", raw)
    history_raw = raw.get("history", [])
    history = [EditEvent.from_dict(e) for e in history_raw]
    return AnnotationResult(
        schema_version=str(raw["schema_version"]),
        episode_id=str(raw["episode_id"]),
        task=TaskInfo(
            text=str(raw["task"]["text"]),
            version=raw["task"].get("version"),
        ),
        generated_at=str(raw["generated_at"]),
        generator=GeneratorInfo(
            name=str(raw["generator"]["name"]),
            cli_version=str(raw["generator"]["cli_version"]),
            pipeline_phase=int(raw["generator"]["pipeline_phase"]),
        ),
        config_hash=str(raw["config_hash"]),
        input_hash=str(raw["input_hash"]),
        run_hash=str(raw["run_hash"]),
        model_versions=dict(raw["model_versions"]),
        pipeline_phase=int(raw["pipeline_phase"]),
        pipeline_status=_pipeline_status_from_dict(raw["pipeline_status"]),
        segments=[_segment_from_dict(s) for s in raw["segments"]],
        boundaries_url=str(raw["boundaries_url"]),
        signals_url=str(raw["signals_url"]),
        notes=raw.get("notes"),
        history=history,
    )
