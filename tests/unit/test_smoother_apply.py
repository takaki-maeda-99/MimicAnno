"""apply_smoothing top-level + _recompute_confidence helper (spec §3.5)."""
from __future__ import annotations

import math

from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _recompute_confidence


def _seg(*, phase: str = "grasp_object",
         vlm_confidence: float | None = 0.8,
         start_score: float = 0.6, end_score: float = 0.4) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id="ep__seg0000", episode_id="ep",
        start_frame=0, end_frame=10, start_time=0.0, end_time=0.33,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[], label_source="vlm_with_object_state",
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id="b0", time=0.0, sources=[],
                                    score=start_score),
        end_boundary=BoundaryRef(candidate_id="b1", time=0.33, sources=[],
                                  score=end_score),
        boundary_confidence=0.0, vlm_confidence=vlm_confidence,
        overall_confidence=0.0, evidence=None, reviewed=False, reviewer_id=None,
    )


def test_recompute_confidence_sets_boundary_to_min_of_edges() -> None:
    seg = _seg(start_score=0.6, end_score=0.4)
    out = _recompute_confidence(seg)
    assert out.boundary_confidence == 0.4   # min(0.6, 0.4)


def test_recompute_confidence_overall_geometric_mean() -> None:
    seg = _seg(start_score=0.6, end_score=0.6, vlm_confidence=0.4)
    out = _recompute_confidence(seg)
    assert out.boundary_confidence == 0.6
    assert math.isclose(out.overall_confidence, math.sqrt(0.6 * 0.4))


def test_recompute_confidence_reserved_phases_zero() -> None:
    for phase in ("unlabeled", "unknown"):
        seg = _seg(phase=phase, start_score=0.9, end_score=0.9, vlm_confidence=0.9)
        out = _recompute_confidence(seg)
        assert out.overall_confidence == 0.0


def test_recompute_confidence_none_vlm_uses_boundary() -> None:
    seg = _seg(start_score=0.5, end_score=0.4, vlm_confidence=None)
    out = _recompute_confidence(seg)
    assert out.overall_confidence == 0.4   # boundary_confidence


def test_recompute_confidence_does_not_mutate_input() -> None:
    """_recompute_confidence returns a new dataclass; original is untouched."""
    seg = _seg(start_score=0.5, end_score=0.5, vlm_confidence=0.4)
    original_bc = seg.boundary_confidence
    original_oc = seg.overall_confidence
    _ = _recompute_confidence(seg)
    assert seg.boundary_confidence == original_bc
    assert seg.overall_confidence == original_oc


# ----- apply_smoothing orchestrator -----

import pytest  # noqa: E402

from dataclasses import replace  # noqa: E402

from mimicanno.config import SmootherConfig  # noqa: E402
from mimicanno.errors import SmootherSegmentInvariantViolation  # noqa: E402
from mimicanno.schema import SmoothingSummary  # noqa: E402
from mimicanno.smoother import (  # noqa: E402
    _assert_segment_invariants,
    apply_smoothing,
)


LABELSET = ["approach_object", "grasp_object", "lift_object",
            "release_object", "idle"]


def _seg2(*, idx: int, phase: str, start_frame: int, end_frame: int,
          vlm: float | None = 0.7,
          start_score: float = 0.5, end_score: float = 0.5,
          ) -> SubtaskSegment:
    bc = min(start_score, end_score)
    if phase in {"unlabeled", "unknown"}:
        oc = 0.0
    elif vlm is None:
        oc = bc
    else:
        oc = math.sqrt(bc * vlm)
    return SubtaskSegment(
        segment_id=f"ep__seg{idx:04d}", episode_id="ep",
        start_frame=start_frame, end_frame=end_frame,
        start_time=start_frame / 30, end_time=end_frame / 30,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[], label_source="vlm_with_object_state",
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s",
                                    time=start_frame / 30, sources=[],
                                    score=start_score),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e",
                                  time=end_frame / 30, sources=[],
                                  score=end_score),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=[],
    )


def test_apply_empty_input() -> None:
    cfg = SmootherConfig()
    result = apply_smoothing([], config=cfg, labelset=LABELSET)
    assert result.segments == []
    assert result.summary.initial_segment_count == 0
    assert result.summary.final_segment_count == 0
    assert result.summary.viterbi_skipped is True


def test_apply_single_segment_passthrough() -> None:
    only = _seg2(idx=0, phase="grasp_object", start_frame=0, end_frame=30)
    cfg = SmootherConfig()
    result = apply_smoothing([only], config=cfg, labelset=LABELSET)
    assert len(result.segments) == 1
    assert result.summary.initial_segment_count == 1
    assert result.summary.final_segment_count == 1


def test_apply_idempotent_on_smooth_input() -> None:
    """Apply twice = apply once if input is already smooth."""
    cfg = SmootherConfig(forbidden_transitions=())
    segs = [
        _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=30),
        _seg2(idx=1, phase="grasp_object", start_frame=30, end_frame=60),
    ]
    r1 = apply_smoothing(segs, config=cfg, labelset=LABELSET)
    r2 = apply_smoothing(r1.segments, config=cfg, labelset=LABELSET)
    assert [s.phase for s in r1.segments] == [s.phase for s in r2.segments]


def test_apply_summary_counts_match_3_op_run() -> None:
    """Compose a fixture exercising Op 1 + Op 2; verify summary counts."""
    # 2 same-label adjacent (Op 1 collapses) + 1 short below threshold
    # (Op 2 absorbs)
    cfg = SmootherConfig(min_segment_duration_sec=0.30,
                          forbidden_transitions=())
    a = _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=15)
    b = _seg2(idx=1, phase="approach_object", start_frame=15, end_frame=30)
    short = _seg2(idx=2, phase="grasp_object", start_frame=30, end_frame=32)
    c = _seg2(idx=3, phase="lift_object", start_frame=32, end_frame=62)
    result = apply_smoothing([a, b, short, c], config=cfg, labelset=LABELSET)
    # a + b collapse (Op 1: 1 collapse, 1 round), short absorbs into c (Op 2: 1 absorb)
    assert result.summary.merge_same_label_collapses >= 1
    assert result.summary.merge_short_absorbs >= 1
    assert result.summary.final_segment_count <= 3   # at most 3 after smoothing


def test_apply_no_forbidden_high_conf_pair_after_smoothing() -> None:
    """Spec exit criterion §10 #3: no adjacent pair forbidden AND both
    overall_confidence > 0.5."""
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    a = _seg2(idx=0, phase="grasp_object", start_frame=0, end_frame=30, vlm=0.3)
    b = _seg2(idx=1, phase="approach_object", start_frame=30, end_frame=60, vlm=0.3)
    result = apply_smoothing([a, b], config=cfg, labelset=LABELSET)
    forbidden = set(cfg.forbidden_transitions)
    for s_i, s_j in zip(result.segments, result.segments[1:], strict=False):
        if (s_i.phase, s_j.phase) in forbidden:
            assert min(s_i.overall_confidence, s_j.overall_confidence) <= 0.5


def test_apply_invariant_check_passes_on_smooth_run() -> None:
    cfg = SmootherConfig()
    a = _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=30)
    b = _seg2(idx=1, phase="grasp_object", start_frame=30, end_frame=60)
    # No exception expected
    result = apply_smoothing([a, b], config=cfg, labelset=LABELSET)
    assert len(result.segments) >= 1


def test_assert_invariants_raises_on_gap() -> None:
    """Synthesize a frame gap between adjacent segments; helper must raise."""
    a = _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=10)
    a = replace(a, end_boundary=BoundaryRef(candidate_id="ax", time=0.33,
                                              sources=[], score=0.5))
    b = _seg2(idx=1, phase="grasp_object", start_frame=20, end_frame=30)
    b = replace(b, start_boundary=BoundaryRef(candidate_id="bx", time=0.66,
                                                sources=[], score=0.5))
    with pytest.raises(SmootherSegmentInvariantViolation) as exc_info:
        _assert_segment_invariants([a, b])
    assert exc_info.value.code == "smoother_segment_invariant_violation"


def test_assert_invariants_raises_on_nan_confidence() -> None:
    a = _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=10)
    a = replace(a, overall_confidence=float("nan"))
    with pytest.raises(SmootherSegmentInvariantViolation):
        _assert_segment_invariants([a])


def test_apply_default_config_runs_without_error() -> None:
    """Sanity: default SmootherConfig + a few segments produces no exception."""
    cfg = SmootherConfig()
    segs = [
        _seg2(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.7),
        _seg2(idx=1, phase="grasp_object", start_frame=30, end_frame=60, vlm=0.7),
        _seg2(idx=2, phase="lift_object", start_frame=60, end_frame=90, vlm=0.7),
    ]
    result = apply_smoothing(segs, config=cfg, labelset=LABELSET)
    # Default config has no forbidden pair triggering; expect identity.
    assert [s.phase for s in result.segments] == ["approach_object",
                                                    "grasp_object", "lift_object"]
    assert result.summary.viterbi_skipped is False
