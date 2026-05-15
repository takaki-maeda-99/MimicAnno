"""Boundary lookup and frame validation helpers (Phase 5 B r2).

A "boundary" is the shared edge between two adjacent segments, identified
by the *right* segment's segment_id (spec §3.1).
"""
from __future__ import annotations

from mimicanno.schema import SubtaskSegment


class BoundaryNotFound(LookupError):
    """boundary_id does not match any segment_id in the annotation."""

    def __init__(self, boundary_id: str) -> None:
        super().__init__(f"boundary not found: {boundary_id!r}")
        self.boundary_id = boundary_id


class BoundaryIsTimelineEdge(ValueError):
    """boundary_id refers to segments[0], which has no left neighbour."""

    def __init__(self, boundary_id: str) -> None:
        super().__init__(f"boundary is timeline start edge: {boundary_id!r}")
        self.boundary_id = boundary_id


class InvalidFrame(ValueError):
    """new_frame violates the frame invariant (spec §3.3)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_boundary(
    segments: list[SubtaskSegment],
    boundary_id: str,
) -> tuple[int, int]:
    """Return (left_idx, right_idx) for the boundary identified by boundary_id.

    boundary_id is the segment_id of the *right* segment. Raises
    BoundaryIsTimelineEdge if it matches segments[0], BoundaryNotFound if
    the id is absent entirely.
    """
    idx = next(
        (i for i, s in enumerate(segments) if s.segment_id == boundary_id),
        None,
    )
    if idx is None:
        raise BoundaryNotFound(boundary_id)
    if idx == 0:
        raise BoundaryIsTimelineEdge(boundary_id)
    return idx - 1, idx


def derive_n_frames(segments: list[SubtaskSegment]) -> int:
    """Derive episode frame count from segments (spec §3.3).

    Phase 4 smoother invariant: the last segment covers through the final
    frame, so n_frames = max(end_frame) + 1.
    """
    return max(s.end_frame for s in segments) + 1


def validate_new_frame(
    left: SubtaskSegment,
    right: SubtaskSegment,
    new_frame: int,
    n_frames: int,
) -> None:
    """Raise InvalidFrame if new_frame violates spec §3.3 constraints.

    Constraints (MIN_SEGMENT_FRAMES = 1):
    - new_frame must be in [0, n_frames)
    - left segment retains >= 1 frame: new_frame > left.start_frame
    - right segment retains >= 1 frame: new_frame <= right.end_frame
    - no-op (same as current boundary) is rejected
    """
    current_boundary = right.start_frame
    if new_frame == current_boundary:
        raise InvalidFrame("no-op: new_frame equals current boundary frame")
    if new_frame < 0 or new_frame >= n_frames:
        raise InvalidFrame(
            f"new_frame {new_frame} out of episode range [0, {n_frames})"
        )
    if new_frame <= left.start_frame:
        raise InvalidFrame(
            f"new_frame {new_frame} <= left.start_frame {left.start_frame}:"
            " left segment would have 0 frames"
        )
    if new_frame > right.end_frame:
        raise InvalidFrame(
            f"new_frame {new_frame} > right.end_frame {right.end_frame}:"
            " right segment would have 0 frames"
        )
