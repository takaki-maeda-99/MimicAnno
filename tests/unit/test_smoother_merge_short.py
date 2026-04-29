"""Op 2: min-duration absorb (spec §3.3)."""
from __future__ import annotations

import math

from mimicanno.config import SmootherConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _merge_short


def _seg(*, idx: int, phase: str, start_frame: int, end_frame: int,
         fps: int = 30, vlm: float | None = 0.7,
         start_score: float = 0.5, end_score: float = 0.5,
         smoothing_ops: list[str] | None = None,
         label_source: str = "vlm_with_object_state",
         ) -> SubtaskSegment:
    bc = min(start_score, end_score)
    if vlm is None:
        oc = bc
    elif phase in {"unlabeled", "unknown"}:
        oc = 0.0
    else:
        oc = math.sqrt(bc * vlm)
    return SubtaskSegment(
        segment_id=f"ep__seg{idx:04d}", episode_id="ep",
        start_frame=start_frame, end_frame=end_frame,
        start_time=start_frame / fps, end_time=end_frame / fps,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[],
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s",
                                    time=start_frame / fps, sources=[],
                                    score=start_score),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e",
                                  time=end_frame / fps, sources=[],
                                  score=end_score),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=list(smoothing_ops or []),
    )


def test_below_threshold_absorbs_into_higher_neighbor() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.4)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.6)
    long_r = _seg(idx=2, phase="lift_object", start_frame=32, end_frame=62, vlm=0.9)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([long_l, short, long_r], config=cfg)
    assert absorbs == 1
    # short merged into right (higher overall_confidence)
    assert len(out) == 2
    assert out[1].phase == "lift_object"
    assert out[1].start_frame == 30
    assert out[1].end_frame == 62
    assert "merge_short" in out[1].smoothing_ops


def test_tie_prefers_left() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.6)
    long_r = _seg(idx=2, phase="lift_object", start_frame=32, end_frame=62, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short, long_r], config=cfg)
    # Tie on overall_confidence → prefer left (no forbidden conflict)
    assert out[0].phase == "approach_object"
    assert out[0].end_frame == 32
    assert out[1].phase == "lift_object"


def test_single_segment_no_neighbor_passes_through() -> None:
    only = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=2)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([only], config=cfg)
    assert len(out) == 1
    assert out[0].smoothing_ops == []
    assert absorbs == 0


def test_no_short_segments_identity() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30)
    b = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=60)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([a, b], config=cfg)
    assert len(out) == 2
    assert absorbs == 0
    assert all(s.smoothing_ops == [] for s in out)


def test_all_short_cascade_to_one() -> None:
    """All segments below threshold, equal confidence → cascade to one."""
    segs = [_seg(idx=i, phase=f"phase_{i}", start_frame=i*2, end_frame=(i+1)*2,
                 vlm=0.5)
            for i in range(4)]
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short(segs, config=cfg)
    assert len(out) == 1
    assert absorbs == 3


def test_smoothing_ops_records_merge_short_and_preserves_prior() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.5,
                 smoothing_ops=["merge_same_label"])
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    assert len(out) == 1
    assert "merge_short" in out[0].smoothing_ops
    assert "merge_same_label" in out[0].smoothing_ops


def test_boundary_confidence_re_derived_after_absorb() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30,
                  start_score=0.9, end_score=0.7, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32,
                 start_score=0.7, end_score=0.4, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    # Absorbed left; merged spans 0-32. start_score=0.9, end_score=0.4.
    # boundary_confidence = min(0.9, 0.4) = 0.4
    assert math.isclose(out[0].boundary_confidence, 0.4)


def test_left_only_neighbor() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.9)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    assert len(out) == 1
    # Only neighbor is left → absorb left, regardless of confidence
    assert out[0].phase == "approach_object"


def test_right_only_neighbor() -> None:
    short = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=2, vlm=0.9)
    long_r = _seg(idx=1, phase="approach_object", start_frame=2, end_frame=32, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([short, long_r], config=cfg)
    assert len(out) == 1
    assert out[0].phase == "approach_object"


def test_op2_does_not_collapse_same_label_neighbors() -> None:
    """Op 2 alone does NOT collapse adjacent same-phase segments — that's
    Op 1's job. Verify Op 2's output may have new same-label adjacencies."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="approach_object", start_frame=30, end_frame=32, vlm=0.5)
    c = _seg(idx=2, phase="grasp_object", start_frame=32, end_frame=62, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([a, short, c], config=cfg)
    # `short` absorbs into left (tie → left preference) → output has two
    # `grasp_object` segments adjacent (left-merged keeps "grasp_object"
    # from a; right is c). Op 1 follow-up is the orchestrator's job.
    assert len(out) == 2
    assert out[0].phase == "grasp_object"
    assert out[1].phase == "grasp_object"
