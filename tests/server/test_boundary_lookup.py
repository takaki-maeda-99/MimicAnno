"""Unit tests for boundary_lookup.py (T2 + T3)."""
from __future__ import annotations

import pytest

from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.server.boundary_lookup import (
    BoundaryIsTimelineEdge,
    BoundaryNotFound,
    InvalidFrame,
    derive_n_frames,
    resolve_boundary,
    validate_new_frame,
)


def _make_segment(seg_id: str, start: int, end: int) -> SubtaskSegment:
    br = BoundaryRef(candidate_id=None, time=float(start) / 30.0, sources=[], score=0.8)
    return SubtaskSegment(
        segment_id=seg_id,
        episode_id="episode_000000",
        start_frame=start,
        end_frame=end,
        start_time=float(start) / 30.0,
        end_time=float(end) / 30.0,
        phase="approach_object",
        verb=None, object=None, target=None,
        failure_flags=[],
        label_source="signals_only",
        object_state_unavailable=True,
        object_track_ids=[],
        label_version="manipulation.v1",
        start_boundary=br,
        end_boundary=br,
        boundary_confidence=0.8,
        vlm_confidence=None,
        overall_confidence=0.8,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )


# ---------------------------------------------------------------------------
# resolve_boundary (T2)
# ---------------------------------------------------------------------------


def _segs(n: int = 4) -> list:
    """n segments with frames [0,9], [10,19], [20,29], [30,39] etc."""
    segs = []
    for i in range(n):
        segs.append(_make_segment(f"seg_{i:05d}", i * 10, i * 10 + 9))
    return segs


def test_resolve_boundary_normal() -> None:
    segs = _segs(4)
    left, right = resolve_boundary(segs, "seg_00001")
    assert left == 0
    assert right == 1


def test_resolve_boundary_last_inner() -> None:
    segs = _segs(4)
    left, right = resolve_boundary(segs, "seg_00003")
    assert left == 2
    assert right == 3


def test_resolve_boundary_timeline_edge() -> None:
    segs = _segs(4)
    with pytest.raises(BoundaryIsTimelineEdge):
        resolve_boundary(segs, "seg_00000")


def test_resolve_boundary_not_found() -> None:
    segs = _segs(4)
    with pytest.raises(BoundaryNotFound):
        resolve_boundary(segs, "seg_99999")


# ---------------------------------------------------------------------------
# derive_n_frames (T3)
# ---------------------------------------------------------------------------


def test_derive_n_frames() -> None:
    segs = _segs(4)
    assert derive_n_frames(segs) == 40  # max end_frame=39, +1


# ---------------------------------------------------------------------------
# validate_new_frame (T3)
# ---------------------------------------------------------------------------


def _lr(left_start: int, left_end: int, right_start: int, right_end: int):  # type: ignore[no-untyped-def]
    left = _make_segment("seg_00000", left_start, left_end)
    right = _make_segment("seg_00001", right_start, right_end)
    return left, right


def test_validate_new_frame_happy() -> None:
    left, right = _lr(0, 9, 10, 19)
    validate_new_frame(left, right, 5, 20)  # move boundary from 10 to 5


def test_validate_new_frame_happy_forward() -> None:
    left, right = _lr(0, 9, 10, 19)
    validate_new_frame(left, right, 15, 20)  # move boundary forward


def test_validate_no_op() -> None:
    left, right = _lr(0, 9, 10, 19)
    with pytest.raises(InvalidFrame, match="no-op"):
        validate_new_frame(left, right, 10, 20)


def test_validate_out_of_range_negative() -> None:
    left, right = _lr(0, 9, 10, 19)
    with pytest.raises(InvalidFrame, match="out of episode"):
        validate_new_frame(left, right, -1, 20)


def test_validate_out_of_range_too_large() -> None:
    left, right = _lr(0, 9, 10, 19)
    with pytest.raises(InvalidFrame, match="out of episode"):
        validate_new_frame(left, right, 20, 20)


def test_validate_left_would_vanish() -> None:
    left, right = _lr(5, 9, 10, 19)
    with pytest.raises(InvalidFrame, match="left segment"):
        validate_new_frame(left, right, 5, 20)  # new_frame == left.start_frame


def test_validate_left_min_one_frame() -> None:
    left, right = _lr(5, 9, 10, 19)
    validate_new_frame(left, right, 6, 20)  # left keeps 1 frame (frame 5)


def test_validate_right_would_vanish() -> None:
    left, right = _lr(0, 9, 10, 19)
    with pytest.raises(InvalidFrame, match="right segment"):
        validate_new_frame(left, right, 20, 25)  # new_frame > right.end_frame


def test_validate_right_min_one_frame() -> None:
    left, right = _lr(0, 9, 10, 19)
    validate_new_frame(left, right, 19, 25)  # right keeps 1 frame (frame 19)
