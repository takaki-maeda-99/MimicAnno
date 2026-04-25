"""Phase 1 clip bracketing algorithm (spec §5.6)."""
from __future__ import annotations

from mimicanno.schema import BoundaryCandidate, BoundaryRef, SubtaskSegment

LABEL_VERSION = "manipulation.v1"


def bracket_phase1_segments(
    episode_id: str,
    candidates: list[BoundaryCandidate],
    *,
    fps: float,
    duration_sec: float,
) -> list[SubtaskSegment]:
    """Deterministic §5.6 bracketing.

    1. Sort candidates by ``time``.
    2. Cut list = [0.0] + candidate.times + [duration_sec].
    3. Half-open intervals [t_i, t_{i+1}); end_frame is inclusive.
    4. Drop sub-frame segments (length < 1/fps).
    """
    sorted_cands = sorted(candidates, key=lambda c: c.time)
    epsilon_sec = 1.0 / fps

    # Build edge refs with sentinels.
    start_ref = BoundaryRef(candidate_id=None, time=0.0, sources=["episode_start"], score=1.0)
    end_ref = BoundaryRef(candidate_id=None, time=duration_sec, sources=["episode_end"], score=1.0)
    cand_refs = [
        BoundaryRef(
            candidate_id=c.id, time=c.time, sources=list(c.sources), score=c.score,
        )
        for c in sorted_cands
    ]
    edges: list[BoundaryRef] = [start_ref, *cand_refs, end_ref]

    out: list[SubtaskSegment] = []
    next_id = 1
    for left, right in zip(edges, edges[1:], strict=False):
        if right.time - left.time < epsilon_sec:
            continue
        boundary_confidence = min(left.score, right.score)
        seg = SubtaskSegment(
            segment_id=f"s_{next_id:03d}",
            episode_id=episode_id,
            start_frame=int(round(left.time * fps)),
            end_frame=max(int(round(right.time * fps)) - 1, int(round(left.time * fps))),
            start_time=left.time,
            end_time=right.time,
            phase="unlabeled",
            verb=None,
            object=None,
            target=None,
            failure_flags=[],
            label_source="signals_only",
            object_state_unavailable=True,
            object_track_ids=[],
            label_version=LABEL_VERSION,
            start_boundary=left,
            end_boundary=right,
            boundary_confidence=boundary_confidence,
            vlm_confidence=None,
            overall_confidence=0.0,  # reserved phase = 0 (§6.4)
            evidence=None,
            reviewed=False,
            reviewer_id=None,
        )
        out.append(seg)
        next_id += 1
    return out
