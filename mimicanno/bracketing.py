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

    Edge cases (all produce dropped degenerate segments, by design):
    - A candidate at ``time == 0.0`` produces a zero-width interval with
      the start sentinel and is dropped. The episode-start sentinel's
      coverage subsumes it.
    - A candidate within ``1/fps`` of ``duration_sec`` produces a sub-frame
      trailing segment and is dropped; the episode tail is NOT covered by
      any segment in this case. Upstream callers can avoid this by
      filtering candidates whose time is outside ``[1/fps, duration_sec - 1/fps]``.
    - Empty candidate list → exactly one segment spanning ``[0.0, duration_sec)``.

    Segment IDs (``s_NNN``) are assigned sequentially within ONE invocation
    starting at ``s_001``. They are NOT episode-globally unique across calls;
    callers re-running the bracketer must understand that IDs may collide
    with a prior result for the same episode.
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
