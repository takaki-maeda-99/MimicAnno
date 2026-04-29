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
