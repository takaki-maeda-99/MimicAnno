"""Phase 4 temporal smoothing (spec §3).

Three deterministic operators applied in fixed order:

1. ``_merge_same_label`` — collapse adjacent same-phase segments (spec §3.2).
2. ``_merge_short`` — absorb short segments into highest-confidence neighbor (§3.3).
3. ``_viterbi_relabel`` — DP relabel with forbidden-transition penalty (§3.4),
   skipped when ``viterbi_enabled=False`` or when the segment count is < 2.

Public API::

    apply_smoothing(segments, *, config, labelset) -> SmoothingResult

Internal helpers (``_merge_same_label`` / ``_merge_short`` / ``_viterbi_relabel``
/ ``_recompute_confidence``) are exposed for unit-test assertions on the
operator semantics; they are not part of the public stable surface.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

from mimicanno.config import SmootherConfig
from mimicanno.schema import SmoothingSummary, SubtaskSegment

SmoothingOp = Literal["merge_same_label", "merge_short", "viterbi_relabel"]
_RESERVED_PHASES: frozenset[str] = frozenset({"unlabeled", "unknown"})


@dataclass(slots=True)
class SmoothingResult:
    """Returned by :func:`apply_smoothing` (spec §1.2)."""

    segments: list[SubtaskSegment]
    summary: SmoothingSummary
    ops_log: list[tuple[SmoothingOp, list[str]]] = field(default_factory=list)
    """Ordered log of ops applied; each entry is
    ``(op_name, list_of_segment_ids_post_op)``."""


def _recompute_confidence(seg: SubtaskSegment) -> SubtaskSegment:
    """Re-derive ``boundary_confidence`` and ``overall_confidence`` per spec §3.5.

    boundary_confidence = min(start_boundary.score, end_boundary.score)   [parent §6.1]
    overall_confidence  = 0.0                              if phase ∈ {unlabeled, unknown}
                        = boundary_confidence              if vlm_confidence is None
                        = sqrt(boundary * vlm)             otherwise        [parent §6.4]

    Returns a new segment dataclass; the input is not mutated.
    """
    bc = min(seg.start_boundary.score, seg.end_boundary.score)
    if seg.phase in _RESERVED_PHASES:
        oc = 0.0
    elif seg.vlm_confidence is None:
        oc = bc
    else:
        oc = math.sqrt(bc * seg.vlm_confidence)
    return replace(seg, boundary_confidence=bc, overall_confidence=oc)


def apply_smoothing(
    segments: list[SubtaskSegment],
    *,
    config: SmootherConfig,
    labelset: list[str],
) -> SmoothingResult:
    """Phase 4 smoothing pipeline (spec §3). Stub — Tasks 7-10 fill in the ops."""
    raise NotImplementedError("Tasks 7-10 implement the operators.")
