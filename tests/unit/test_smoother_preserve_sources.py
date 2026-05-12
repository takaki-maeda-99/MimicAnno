"""Source-aware merge preserve_sources tests (spec 2026-05-12 §5.1)."""
from __future__ import annotations

import math
from dataclasses import replace

from mimicanno.config import SmootherConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import (
    _assert_segment_invariants,
    _do_one_merge_round,
    _merge_same_label,
    apply_smoothing,
)


def _seg(
    *,
    idx: int,
    phase: str,
    start_frame: int,
    end_frame: int,
    start_sources: list[str] | None = None,
    end_sources: list[str] | None = None,
    vlm: float | None = 0.7,
    start_score: float = 0.5,
    end_score: float = 0.5,
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
        start_time=start_frame / 30, end_time=end_frame / 30,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[],
        label_source="vlm_with_object_state",
        object_state_unavailable=False,
        object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(
            candidate_id=f"b{idx}s", time=start_frame / 30,
            sources=list(start_sources or []), score=start_score,
        ),
        end_boundary=BoundaryRef(
            candidate_id=f"b{idx}e", time=end_frame / 30,
            sources=list(end_sources or []), score=end_score,
        ),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=[],
    )


def _chain(*segs: SubtaskSegment) -> list[SubtaskSegment]:
    """Force adjacency invariants: rewrite left.end_boundary to match
    right.start_boundary so _assert_segment_invariants passes when applicable."""
    out = list(segs)
    for i in range(len(out) - 1):
        left, right = out[i], out[i + 1]
        # Share the boundary (time + candidate_id + union of sources).
        shared_sources = list({*left.end_boundary.sources, *right.start_boundary.sources})
        new_boundary = BoundaryRef(
            candidate_id=right.start_boundary.candidate_id,
            time=right.start_boundary.time,
            sources=shared_sources,
            score=max(left.end_boundary.score, right.start_boundary.score),
        )
        out[i] = replace(left, end_boundary=new_boundary)
        out[i + 1] = replace(right, start_boundary=new_boundary)
    return out


# 1. default = legacy behavior
def test_preserve_empty_default_legacy_behavior() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"])
    out, _, collapses = _merge_same_label(_chain(a, b))  # preserve omitted
    assert len(out) == 1
    assert collapses == 1


# 2. single source preserve blocks the merge
def test_preserve_single_source_blocks_merge() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"])
    out, rounds, collapses = _merge_same_label(
        _chain(a, b), preserve=frozenset({"gripper_zero_crossing"}),
    )
    assert len(out) == 2
    assert collapses == 0
    assert rounds == 0


# 3. multi source preserve (intersection)
def test_preserve_multi_source_intersection() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["hand_pose_keypoint"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["hand_pose_keypoint"])
    out, _, _ = _merge_same_label(
        _chain(a, b),
        preserve=frozenset({"gripper_zero_crossing", "hand_pose_keypoint"}),
    )
    assert len(out) == 2  # blocked by hand_pose_keypoint


# 4. non-matching source -> merge proceeds
def test_preserve_non_matching_source_merges() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["hand_motion"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["hand_motion"])
    out, _, collapses = _merge_same_label(
        _chain(a, b), preserve=frozenset({"gripper_zero_crossing"}),
    )
    assert len(out) == 1
    assert collapses == 1


# 5. Op 2 でできた新 pair (preserve 対象でない) は merge される
def test_preserve_op2_followup_merges_non_preserved_new_pair() -> None:
    """After Op 2 absorbs a short segment, the new pair's boundary has
    no preserved source → Op 1 follow-up MUST merge it.
    The short middle segment uses cheap_boundary source (not preserved)."""
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=20,
             end_sources=["cheap_source"])
    b = _seg(idx=1, phase="grasp_object", start_frame=20, end_frame=23,
             start_sources=["cheap_source"], end_sources=["cheap_source"],
             vlm=0.3)
    c = _seg(idx=2, phase="approach_object", start_frame=23, end_frame=40,
             start_sources=["cheap_source"])
    cfg = SmootherConfig(
        min_segment_duration_sec=0.30,
        viterbi_enabled=False,  # isolate to Op1/Op2
        forbidden_transitions=(),
        merge_same_label_preserve_sources=("gripper_zero_crossing",),
    )
    res = apply_smoothing(_chain(a, b, c), config=cfg, labelset=["approach_object", "grasp_object"])
    # b is 0.10s (3 frames @30fps) < 0.30s → absorbed; surviving pair is same-phase,
    # boundary has cheap_source only → preserve doesn't apply → merged.
    assert len(res.segments) == 1
    assert res.segments[0].phase == "approach_object"


# 6. 3-in-a-row same phase, middle boundary preserved → left-pass property
def test_preserve_3_in_a_row_middle_preserved_left_pass() -> None:
    """Current-impl property: left→right pass means the right boundary
    of segment 0 is checked first. If that boundary is preserved, merge
    fails; iterator advances to index 1.
    NOTE: this test is sensitive to the merge-pass direction in
    _do_one_merge_round. If pass order changes (left-to-right vs right-
    to-left), update this assertion."""
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"],
             end_sources=["cheap_source"])
    c = _seg(idx=2, phase="approach_object", start_frame=20, end_frame=30,
             start_sources=["cheap_source"])
    out, _, _ = _merge_same_label(
        _chain(a, b, c), preserve=frozenset({"gripper_zero_crossing"}),
    )
    # Pass 1: pair (0,1) preserved → skip, advance i by 1.
    #         pair (1,2) NOT preserved → merge → [seg0, seg1+2].
    # No more pairs.
    assert len(out) == 2
    assert out[0].start_frame == 0 and out[0].end_frame == 10
    assert out[1].start_frame == 10 and out[1].end_frame == 30


# 7. chained preserve — no merges happen
def test_preserve_chained_all_blocked() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"],
             end_sources=["gripper_zero_crossing"])
    c = _seg(idx=2, phase="approach_object", start_frame=20, end_frame=30,
             start_sources=["gripper_zero_crossing"])
    out, rounds, collapses = _merge_same_label(
        _chain(a, b, c), preserve=frozenset({"gripper_zero_crossing"}),
    )
    assert len(out) == 3
    assert collapses == 0
    assert rounds == 0


# 8. multi-round convergence with preserve
def test_preserve_multi_round_convergence() -> None:
    """Preserve must not cause infinite loops. Pair (1,2) is non-preserve;
    after round 1 the resulting pair (0, 1+2) has the original preserved
    boundary at the new left.end position → still skipped in round 2."""
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"],
             end_sources=["cheap_source"])
    c = _seg(idx=2, phase="approach_object", start_frame=20, end_frame=30,
             start_sources=["cheap_source"])
    out, rounds, collapses = _merge_same_label(
        _chain(a, b, c), preserve=frozenset({"gripper_zero_crossing"}),
    )
    assert len(out) == 2
    assert rounds == 1  # one productive round, then converges
    assert collapses == 1


# 9. invariant 保持: result still passes _assert_segment_invariants
def test_preserve_result_passes_invariants() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=10,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20,
             start_sources=["gripper_zero_crossing"])
    chained = _chain(a, b)
    out, _, _ = _merge_same_label(
        chained, preserve=frozenset({"gripper_zero_crossing"}),
    )
    # Should not raise.
    _assert_segment_invariants(out)


# 10. Op 3 (Viterbi) 後の preserve
def test_preserve_after_viterbi_relabel() -> None:
    """If Viterbi changes phases such that adjacent segments share the same
    phase, the post-Viterbi _merge_same_label call must STILL honor preserve.
    We can't easily force Viterbi to do this in a unit test, but we can
    verify the apply_smoothing wiring: a preserved boundary stays even when
    the full pipeline runs."""
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30,
             end_sources=["gripper_zero_crossing"])
    b = _seg(idx=1, phase="approach_object", start_frame=30, end_frame=60,
             start_sources=["gripper_zero_crossing"])
    cfg = SmootherConfig(
        min_segment_duration_sec=0.30,
        viterbi_enabled=True,
        forbidden_transitions=(),
        merge_same_label_preserve_sources=("gripper_zero_crossing",),
    )
    res = apply_smoothing(
        _chain(a, b), config=cfg, labelset=["approach_object"],
    )
    # Boundary preserved through all three Op 1 invocations.
    assert len(res.segments) == 2
