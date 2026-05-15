"""Phase 5 D — T12: unit tests for mimicanno.eval.metrics."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mimicanno.eval.metrics import RunMetrics, aggregate, compute_metrics
from mimicanno.schema import AnnotationResult, EditEvent


def _make_annotation(
    history: list[EditEvent] | None = None,
    n_human: int = 0,
    n_total: int = 5,
) -> AnnotationResult:
    """Construct a minimal AnnotationResult for testing."""
    from mimicanno.schema import (
        BoundaryRef,
        GeneratorInfo,
        PipelineStatus,
        SubtaskSegment,
        TaskInfo,
    )

    def _seg(i: int, human: bool = False) -> SubtaskSegment:
        br = BoundaryRef(candidate_id=None, time=float(i), sources=[], score=1.0)
        return SubtaskSegment(
            segment_id=f"seg{i:04d}",
            episode_id="episode_000000",
            start_frame=i * 10,
            end_frame=i * 10 + 9,
            start_time=float(i),
            end_time=float(i) + 0.9,
            phase="grasp",
            verb=None,
            object=None,
            target=None,
            failure_flags=[],
            label_source="human_edit" if human else "signals_only",
            object_state_unavailable=False,
            object_track_ids=[],
            label_version="0.1.0",
            start_boundary=br,
            end_boundary=br,
            boundary_confidence=0.9,
            vlm_confidence=None,
            overall_confidence=0.9,
            evidence=None,
            reviewed=False,
            reviewer_id=None,
        )

    segments = [_seg(i, human=(i < n_human)) for i in range(n_total)]
    ps = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=None,
        degrade_reason=None,
    )
    return AnnotationResult(
        schema_version="0.3.0",
        episode_id="episode_000000",
        task=TaskInfo(text="pick", version=None),
        generated_at="2026-05-16T00:00:00Z",
        generator=GeneratorInfo(name="mimicanno", cli_version="0.1.0", pipeline_phase=4),
        config_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        run_hash="sha256:" + "c" * 64,
        model_versions={},
        pipeline_phase=4,
        pipeline_status=ps,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
        history=history or [],
    )


def _event(
    edit_type: str = "relabel",
    seg_id: str = "seg0000",
    duration_ms: int | None = None,
) -> EditEvent:
    return EditEvent(
        edit_type=edit_type,
        segment_id=seg_id,
        edited_at="2026-05-16T00:00:00Z",
        client_edit_duration_ms=duration_ms,
        reviewer=None,
    )


# ----------------------------------------------------------------------------
# Test cases
# ----------------------------------------------------------------------------


def test_empty_history() -> None:
    ann = _make_annotation(history=[])
    m = compute_metrics(ann, "run_a")
    assert m.total_edits == 0
    assert m.human_edit_time_ms == 0
    assert m.client_coverage == 0.0


def test_full_coverage() -> None:
    """All events have duration → client_coverage=1.0."""
    events = [_event(duration_ms=500), _event(duration_ms=1000), _event(duration_ms=200)]
    ann = _make_annotation(history=events)
    m = compute_metrics(ann, "run_b")
    assert m.total_edits == 3
    assert m.human_edit_time_ms == 1700
    assert m.client_coverage == pytest.approx(1.0)


def test_partial_coverage() -> None:
    """2/3 events have duration → client_coverage ≈ 0.667."""
    events = [_event(duration_ms=500), _event(duration_ms=None), _event(duration_ms=200)]
    ann = _make_annotation(history=events)
    m = compute_metrics(ann, "run_c")
    assert m.total_edits == 3
    assert m.human_edit_time_ms == 700
    assert m.client_coverage == pytest.approx(2 / 3, abs=1e-9)


def test_label_agreement() -> None:
    """3 of 5 segments are human_edit → label_agreement = 0.6."""
    ann = _make_annotation(n_human=3, n_total=5)
    m = compute_metrics(ann, "run_d")
    assert m.human_edited_segments == 3
    assert m.total_segments == 5
    assert m.label_agreement == pytest.approx(0.6)


def test_aggregate() -> None:
    """Two runs → sums are correct."""
    m1 = RunMetrics(
        run_name="run_a",
        total_edits=3,
        human_edit_time_ms=1500,
        client_coverage=1.0,
        human_edited_segments=2,
        total_segments=5,
        label_agreement=0.4,
    )
    m2 = RunMetrics(
        run_name="run_b",
        total_edits=1,
        human_edit_time_ms=300,
        client_coverage=0.0,
        human_edited_segments=0,
        total_segments=3,
        label_agreement=0.0,
    )
    agg = aggregate([m1, m2])
    assert agg.run_name == "**total**"
    assert agg.total_edits == 4
    assert agg.human_edit_time_ms == 1800
    # timed: m1 contributes 3*1.0=3, m2 contributes 1*0.0=0 → 3/4 = 0.75
    assert agg.client_coverage == pytest.approx(0.75)
    assert agg.human_edited_segments == 2
    assert agg.total_segments == 8
    assert agg.label_agreement == pytest.approx(2 / 8)


def test_aggregate_empty() -> None:
    agg = aggregate([])
    assert agg.total_edits == 0
    assert agg.client_coverage == 0.0
    assert agg.total_segments == 0
