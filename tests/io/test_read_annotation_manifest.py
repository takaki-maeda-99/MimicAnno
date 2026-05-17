"""JSON loaders for annotation.json and manifest.json (Phase 5 Task 9 step 0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.errors import MimicAnnoError
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    BoundaryRef,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    SubtaskSegment,
    TaskInfo,
    _UNSET,
)
from mimicanno.writers import write_annotation_json, write_manifest_json


def _boundary(score: float, sources: list[str]) -> BoundaryRef:
    return BoundaryRef(candidate_id=None, time=0.0, sources=sources, score=score)


def _manifest() -> Manifest:
    return Manifest(
        schema_version="1",
        episode_id="ep_0001",
        task=TaskInfo(text="pick the cube", version=None),
        generated_at="2026-04-30T00:00:00Z",
        generator=GeneratorInfo(
            name="mimicanno", cli_version="0.1.0", pipeline_phase=1
        ),
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash="sha256:" + "2" * 64,
        model_versions={"vlm": None, "sam3": None},
        pipeline_params={},
        inputs={
            "data_parquet": InputRef(
                path="data/chunk-000/episode_000000.parquet",
                sha256="sha256:" + "3" * 64,
            )
        },
        time_base="parquet_timestamp",
        fps=30.0,
        duration_sec=10.0,
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
        compat={"min_reader_version": 1},
        artifacts=[
            Artifact(role="annotation", url="annotation.json", content_type="application/json"),
        ],
    )


def _annotation() -> AnnotationResult:
    seg = SubtaskSegment(
        segment_id="ep_0001_seg0",
        episode_id="ep_0001",
        start_frame=0,
        end_frame=99,
        start_time=0.0,
        end_time=3.3,
        phase="unlabeled",
        verb=None,
        object=None,
        target=None,
        failure_flags=[],
        label_source="signals_only",
        object_state_unavailable=True,
        object_track_ids=[],
        label_version="manipulation.v1",
        start_boundary=_boundary(1.0, ["episode_start"]),
        end_boundary=_boundary(1.0, ["episode_end"]),
        boundary_confidence=1.0,
        vlm_confidence=None,
        overall_confidence=0.0,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )
    return AnnotationResult(
        schema_version="1",
        episode_id="ep_0001",
        task=TaskInfo(text="pick the cube", version=None),
        generated_at="2026-04-30T00:00:00Z",
        generator=GeneratorInfo(
            name="mimicanno", cli_version="0.1.0", pipeline_phase=1
        ),
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash="sha256:" + "2" * 64,
        model_versions={"vlm": None, "sam3": None},
        pipeline_phase=1,
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
        segments=[seg],
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )


def test_read_manifest_round_trip(tmp_path: Path) -> None:
    m = _manifest()
    p = tmp_path / "manifest.json"
    write_manifest_json(p, m)

    loaded = read_manifest(p)
    assert isinstance(loaded, Manifest)
    assert loaded.episode_id == "ep_0001"
    assert loaded.fps == 30.0
    assert loaded.run_hash == m.run_hash
    assert loaded.pipeline_status.object_state_available is False


# Phase 5 B r1 — canonical_name / edited_at reader behavior


def test_read_manifest_canonical_name_falls_back_to_dir_name(
    tmp_path: Path,
) -> None:
    """A pre-r1 manifest (no canonical_name key) reads back with the
    field falling back to the run dir name (spec §3.3 reader fallback).
    Also confirms empty-string is NOT a valid value (`or` short-circuit
    bug guarded by isinstance check, T15 typing note)."""
    run_dir = tmp_path / "episode_000000__abc123def456"
    run_dir.mkdir()
    p = run_dir / "manifest.json"
    write_manifest_json(p, _manifest())  # writer omits None canonical_name
    raw = json.loads(p.read_text())
    assert "canonical_name" not in raw  # confirm pre-r1 shape on disk

    loaded = read_manifest(p)
    assert loaded.canonical_name == "episode_000000__abc123def456"


def test_read_manifest_canonical_name_round_trip(tmp_path: Path) -> None:
    """When the writer emits canonical_name, the reader preserves it
    verbatim (does NOT fall back to dir name)."""
    from dataclasses import replace
    run_dir = tmp_path / "dir_does_not_match"
    run_dir.mkdir()
    p = run_dir / "manifest.json"
    m = replace(_manifest(), canonical_name="ep_0001__explicit_name")
    write_manifest_json(p, m)

    loaded = read_manifest(p)
    assert loaded.canonical_name == "ep_0001__explicit_name"


def test_read_manifest_edited_at_present_or_none(tmp_path: Path) -> None:
    """edited_at: None when absent, preserved when present."""
    from dataclasses import replace
    p = tmp_path / "manifest.json"
    write_manifest_json(p, _manifest())
    assert read_manifest(p).edited_at is None

    write_manifest_json(
        p, replace(_manifest(), edited_at="2026-05-13T12:00:00Z"),
    )
    assert read_manifest(p).edited_at == "2026-05-13T12:00:00Z"


def test_read_annotation_result_round_trip(tmp_path: Path) -> None:
    a = _annotation()
    p = tmp_path / "annotation.json"
    write_annotation_json(p, a)

    loaded = read_annotation_result(p)
    assert isinstance(loaded, AnnotationResult)
    assert loaded.episode_id == "ep_0001"
    assert loaded.pipeline_phase == 1
    assert len(loaded.segments) == 1
    seg = loaded.segments[0]
    assert seg.phase == "unlabeled"
    assert seg.start_frame == 0
    assert seg.end_frame == 99


def test_pipeline_status_retry_fields_round_trip_manifest(tmp_path: Path) -> None:
    """The 3 Phase 3 retry observability fields survive write→read on manifest.json."""
    from dataclasses import replace
    grounding_attempts = [
        {"attempt": 0, "prompt": "tape", "frame": 0, "score": 0.93, "adopted": True},
        {"attempt": 1, "prompt": "tape", "frame": 5, "score": 0.45, "adopted": False},
    ]
    ps = PipelineStatus(
        object_state_available=True,
        degraded_from_phase=None,
        degrade_reason=None,
        object_state_segment_coverage=0.87,
        adopted_frame_index=75,
        grounding_attempts=grounding_attempts,
        mask_overlay_unavailable_frames=2,
    )
    m = replace(_manifest(), pipeline_status=ps)
    p = tmp_path / "manifest.json"
    write_manifest_json(p, m)

    loaded = read_manifest(p)
    lps = loaded.pipeline_status
    assert lps.adopted_frame_index == 75
    assert lps.grounding_attempts == grounding_attempts
    assert lps.mask_overlay_unavailable_frames == 2


def test_pipeline_status_retry_fields_absent_on_phase12_manifest(tmp_path: Path) -> None:
    """Phase 1/2 manifests (no retry fields on disk) preserve _UNSET after read."""
    p = tmp_path / "manifest.json"
    write_manifest_json(p, _manifest())  # default PipelineStatus: _UNSET for all 3

    loaded = read_manifest(p)
    lps = loaded.pipeline_status
    assert lps.adopted_frame_index is _UNSET
    assert lps.grounding_attempts is _UNSET
    assert lps.mask_overlay_unavailable_frames is _UNSET


def test_pipeline_status_retry_fields_round_trip_annotation(tmp_path: Path) -> None:
    """The 3 Phase 3 retry observability fields survive write→read on annotation.json."""
    from dataclasses import replace
    grounding_attempts = [
        {"attempt": 0, "prompt": "marker", "frame": 10, "score": 0.88, "adopted": True},
    ]
    ps = PipelineStatus(
        object_state_available=True,
        degraded_from_phase=None,
        degrade_reason=None,
        object_state_segment_coverage=0.72,
        adopted_frame_index=10,
        grounding_attempts=grounding_attempts,
        mask_overlay_unavailable_frames=0,
    )
    a = replace(_annotation(), pipeline_status=ps)
    p = tmp_path / "annotation.json"
    write_annotation_json(p, a)

    loaded = read_annotation_result(p)
    lps = loaded.pipeline_status
    assert lps.adopted_frame_index == 10
    assert lps.grounding_attempts == grounding_attempts
    assert lps.mask_overlay_unavailable_frames == 0


def test_read_manifest_rejects_schema_violation(tmp_path: Path) -> None:
    bad = {"schema_version": "1", "episode_id": "x"}  # missing required fields
    p = tmp_path / "bad_manifest.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(MimicAnnoError) as ei:
        read_manifest(p)
    assert "manifest" in str(ei.value).lower()


def test_read_annotation_result_rejects_schema_violation(tmp_path: Path) -> None:
    bad = {"schema_version": "1"}  # missing required fields
    p = tmp_path / "bad_annotation.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(MimicAnnoError) as ei:
        read_annotation_result(p)
    assert "annotation" in str(ei.value).lower()
