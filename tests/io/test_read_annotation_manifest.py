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
