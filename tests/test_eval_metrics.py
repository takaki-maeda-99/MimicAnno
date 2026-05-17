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


def test_human_touched_fraction() -> None:
    """3 of 5 segments are human_edit → human_touched_fraction = 0.6."""
    ann = _make_annotation(n_human=3, n_total=5)
    m = compute_metrics(ann, "run_d")
    assert m.human_edited_segments == 3
    assert m.total_segments == 5
    assert m.human_touched_fraction == pytest.approx(0.6)


def test_aggregate() -> None:
    """Two runs → sums are correct."""
    m1 = RunMetrics(
        run_name="run_a",
        total_edits=3,
        human_edit_time_ms=1500,
        client_coverage=1.0,
        human_edited_segments=2,
        total_segments=5,
        human_touched_fraction=0.4,
    )
    m2 = RunMetrics(
        run_name="run_b",
        total_edits=1,
        human_edit_time_ms=300,
        client_coverage=0.0,
        human_edited_segments=0,
        total_segments=3,
        human_touched_fraction=0.0,
    )
    agg = aggregate([m1, m2])
    assert agg.run_name == "**total**"
    assert agg.total_edits == 4
    assert agg.human_edit_time_ms == 1800
    # timed: m1 contributes 3*1.0=3, m2 contributes 1*0.0=0 → 3/4 = 0.75
    assert agg.client_coverage == pytest.approx(0.75)
    assert agg.human_edited_segments == 2
    assert agg.total_segments == 8
    assert agg.human_touched_fraction == pytest.approx(2 / 8)


def test_aggregate_empty() -> None:
    agg = aggregate([])
    assert agg.total_edits == 0
    assert agg.client_coverage == 0.0
    assert agg.total_segments == 0


# ----------------------------------------------------------------------------
# Phase 5 D — render smoke + empty_segments guard
# ----------------------------------------------------------------------------


def test_render_markdown_smoke() -> None:
    """render.render_markdown returns a str containing a header and a row per run."""
    from mimicanno.eval.render import render_markdown

    m1 = compute_metrics(
        _make_annotation(history=[_event(duration_ms=500)], n_human=1, n_total=4),
        "run_a",
    )
    m2 = compute_metrics(
        _make_annotation(history=[_event(duration_ms=200)], n_human=0, n_total=2),
        "run_b",
    )
    agg = aggregate([m1, m2])

    out = render_markdown([m1, m2], agg)
    assert isinstance(out, str)
    # Header from render_markdown.
    assert "MimicAnno eval" in out
    # Required columns mentioned in spec.
    for col in (
        "run",
        "edits",
        "edit_time_ms",
        "client_cov",
        "human_segs",
        "total_segs",
        "human_touched",
    ):
        assert col in out
    # Each run name and the aggregate row appear.
    assert "run_a" in out
    assert "run_b" in out
    assert "**total**" in out


def test_render_json_smoke() -> None:
    """render.render_json returns parseable JSON with the {runs, aggregate} shape."""
    from mimicanno.eval.render import render_json

    m1 = compute_metrics(
        _make_annotation(history=[_event(duration_ms=500)], n_human=1, n_total=4),
        "run_a",
    )
    agg = aggregate([m1])

    out = render_json([m1], agg)
    assert isinstance(out, str)
    import json as _json
    parsed = _json.loads(out)
    assert isinstance(parsed, dict)
    assert isinstance(parsed.get("runs"), list)
    assert len(parsed["runs"]) == 1
    assert parsed["runs"][0]["run"] == "run_a"
    assert isinstance(parsed.get("aggregate"), dict)
    assert parsed["aggregate"]["run"] == "**total**"


def test_empty_segments_no_zerodiv() -> None:
    """compute_metrics on an annotation with zero segments must not ZeroDivide;
    human_touched_fraction defaults to 0.0 and total_segments to 0."""
    ann = _make_annotation(n_total=0, history=[])
    m = compute_metrics(ann, "run_empty")
    assert m.total_segments == 0
    assert m.human_touched_fraction == 0.0
    assert m.total_edits == 0
    assert m.client_coverage == 0.0


# ----------------------------------------------------------------------------
# Phase 5 D r2 — B3: rename label_agreement → human_touched_fraction
# ----------------------------------------------------------------------------


def test_human_touched_fraction_replaces_label_agreement() -> None:
    """RunMetrics must expose the renamed field; the old name MUST be gone."""
    from mimicanno.eval.metrics import RunMetrics
    m = RunMetrics(
        run_name="dummy",
        total_edits=0,
        human_edit_time_ms=0,
        client_coverage=0.0,
        human_edited_segments=0,
        total_segments=0,
        human_touched_fraction=0.5,
    )
    assert m.human_touched_fraction == 0.5
    assert not hasattr(m, "label_agreement"), (
        "label_agreement field must be removed after D r2 rename"
    )


def test_render_markdown_uses_workload_proxy_footnote() -> None:
    """The Markdown render must include a footnote clarifying the metric is
    a workload proxy, not planner agreement."""
    from mimicanno.eval.metrics import RunMetrics
    from mimicanno.eval.render import render_markdown
    r = RunMetrics(
        run_name="ep0",
        total_edits=1,
        human_edit_time_ms=100,
        client_coverage=1.0,
        human_edited_segments=3,
        total_segments=5,
        human_touched_fraction=0.6,
    )
    agg = RunMetrics(
        run_name="**total**",
        total_edits=1,
        human_edit_time_ms=100,
        client_coverage=1.0,
        human_edited_segments=3,
        total_segments=5,
        human_touched_fraction=0.6,
    )
    out = render_markdown([r], agg)
    lo = out.lower()
    assert "workload proxy" in lo or "human-workload" in lo, (
        f"render must include a workload-proxy footnote, got: {out!r}"
    )


def test_render_markdown_uses_human_touched_column() -> None:
    """The Markdown header must read `human_touched` (not `label_agr`)."""
    from mimicanno.eval.metrics import RunMetrics
    from mimicanno.eval.render import render_markdown
    r = RunMetrics(
        run_name="ep0",
        total_edits=0, human_edit_time_ms=0, client_coverage=0.0,
        human_edited_segments=0, total_segments=0, human_touched_fraction=0.0,
    )
    out = render_markdown([r], r)
    assert "human_touched" in out, f"missing column header: {out!r}"
    assert "label_agr" not in out, f"old column header still present: {out!r}"


def test_render_json_uses_new_key() -> None:
    """The JSON render must emit `human_touched_fraction`, not `label_agreement`."""
    import json
    from mimicanno.eval.metrics import RunMetrics
    from mimicanno.eval.render import render_json
    r = RunMetrics(
        run_name="ep0",
        total_edits=0, human_edit_time_ms=0, client_coverage=0.0,
        human_edited_segments=0, total_segments=0, human_touched_fraction=0.6,
    )
    parsed = json.loads(render_json([r], r))
    assert "human_touched_fraction" in parsed["runs"][0]
    assert "label_agreement" not in parsed["runs"][0]
    assert "human_touched_fraction" in parsed["aggregate"]
