"""Op 1: same-label merge (spec §3.2)."""
from __future__ import annotations

import math
from dataclasses import replace

from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _merge_same_label


def _seg(*, idx: int, phase: str, start_frame: int, end_frame: int,
         vlm: float | None = 0.7, start_score: float = 0.5, end_score: float = 0.5,
         smoothing_ops: list[str] | None = None,
         failure_flags: list[str] | None = None,
         object_track_ids: list[str] | None = None,
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
        start_time=start_frame / 30, end_time=end_frame / 30,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=list(failure_flags or []),
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False,
        object_track_ids=list(object_track_ids or []),
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s",
                                    time=start_frame / 30, sources=[],
                                    score=start_score),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e",
                                  time=end_frame / 30, sources=[],
                                  score=end_score),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=list(smoothing_ops or []),
    )


def test_two_adjacent_same_collapse() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    out, rounds, collapses = _merge_same_label([a, b])
    assert len(out) == 1
    assert out[0].start_frame == 0 and out[0].end_frame == 20
    assert out[0].phase == "grasp_object"
    assert out[0].smoothing_ops == ["merge_same_label"]
    assert rounds == 1
    assert collapses == 1


def test_non_adjacent_same_no_merge() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="grasp_object", start_frame=20, end_frame=30)
    out, _, collapses = _merge_same_label([a, b, c])
    assert len(out) == 3
    assert collapses == 0


def test_three_in_a_row_collapse() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="grasp_object", start_frame=20, end_frame=30)
    out, _, collapses = _merge_same_label([a, b, c])
    assert len(out) == 1
    assert out[0].start_frame == 0 and out[0].end_frame == 30
    # Two collapses total to compress 3 → 1
    assert collapses == 2


def test_higher_confidence_label_source_wins_on_merge() -> None:
    """When merging same-phase segments with different label_source, the higher
    overall_confidence side's label_source wins (spec §3.2 phase/.../label_source rule)."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             vlm=0.4, label_source="vlm_robot_state_only")
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             vlm=0.9, label_source="vlm_with_object_state")
    out, _, _ = _merge_same_label([a, b])
    assert len(out) == 1
    assert out[0].label_source == "vlm_with_object_state"


def test_failure_flags_set_union() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             failure_flags=["failed_grasp"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             failure_flags=["lost_object"])
    out, _, _ = _merge_same_label([a, b])
    assert out[0].failure_flags == ["failed_grasp", "lost_object"]


def test_object_track_ids_set_union() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             object_track_ids=["obj_red_block"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             object_track_ids=["obj_red_block", "obj_bin"])
    out, _, _ = _merge_same_label([a, b])
    assert out[0].object_track_ids == ["obj_bin", "obj_red_block"]


def test_boundary_confidence_derived_not_max() -> None:
    """Spec §3.2: merged boundary_confidence is min of surviving outer edges."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             start_score=0.9, end_score=0.9, vlm=0.5)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             start_score=0.9, end_score=0.3, vlm=0.5)
    out, _, _ = _merge_same_label([a, b])
    # merged.start = a.start (0.9), merged.end = b.end (0.3); min = 0.3
    assert out[0].boundary_confidence == 0.3
    assert math.isclose(out[0].overall_confidence, math.sqrt(0.3 * 0.5))


def test_reviewed_reset_on_merge() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    a = replace(a, reviewed=True, reviewer_id="alice")
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    out, _, _ = _merge_same_label([a, b])
    assert out[0].reviewed is False
    assert out[0].reviewer_id is None


def test_smoothing_ops_lineage_from_both() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             smoothing_ops=["merge_short"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             smoothing_ops=["viterbi_relabel"])
    out, _, _ = _merge_same_label([a, b])
    # Spec §3.2: dedup(a.ops + b.ops + ["merge_same_label"]); preserves order
    assert out[0].smoothing_ops == ["merge_short", "viterbi_relabel", "merge_same_label"]


def test_smoothing_ops_dedup_consecutive() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             smoothing_ops=["merge_same_label"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             smoothing_ops=["merge_same_label"])
    out, _, _ = _merge_same_label([a, b])
    # Two "merge_same_label" entries from inputs + one new = three; dedup
    # consecutive duplicates leaves one.
    assert out[0].smoothing_ops == ["merge_same_label"]


def test_segment_id_regenerated() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="approach_object", start_frame=20, end_frame=30)
    out, _, _ = _merge_same_label([a, b, c])
    assert [s.segment_id for s in out] == ["ep__seg0000", "ep__seg0001"]


def test_empty_input() -> None:
    out, rounds, collapses = _merge_same_label([])
    assert out == []
    assert rounds == 0
    assert collapses == 0


def test_single_segment() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    out, rounds, collapses = _merge_same_label([a])
    assert len(out) == 1
    assert out[0].smoothing_ops == []   # no merge, no op recorded
    assert rounds == 0
    assert collapses == 0


def test_higher_overall_confidence_segment_wins_label_fields() -> None:
    """Same phase but different overall_confidence: the higher side's verb / object /
    target / evidence should propagate to merged segment (spec §3.2)."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10, vlm=0.3)
    a = replace(a, verb="grasp", object="cube_a", target=None, evidence="from_a")
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20, vlm=0.9)
    b = replace(b, verb="grasp", object="cube_b", target="bin", evidence="from_b")
    out, _, _ = _merge_same_label([a, b])
    # b has higher overall_confidence
    assert out[0].object == "cube_b"
    assert out[0].target == "bin"
    assert out[0].evidence == "from_b"


def test_vlm_confidence_duration_weighted_mean() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10, vlm=0.6)  # 10 frames
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=40, vlm=0.9)  # 30 frames
    out, _, _ = _merge_same_label([a, b])
    # weighted mean: (0.6 * 10/30 + 0.9 * 30/30) / (1/30 + 30/30) = (0.2 + 0.9) / (1/30 + 1)
    # Actually: durations are 10/30 and 30/30 sec. weighted = (0.6*10/30 + 0.9*30/30) / (10/30 + 30/30)
    # = (0.2 + 0.9) / (1/3 + 1) = 1.1 / 1.333 = 0.825
    expected = (0.6 * (10 / 30) + 0.9 * (30 / 30)) / ((10 / 30) + (30 / 30))
    assert out[0].vlm_confidence is not None
    assert math.isclose(out[0].vlm_confidence, expected, rel_tol=1e-6)


def test_vlm_confidence_none_handling() -> None:
    """Both None → None; one None → other's value alone."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10, vlm=None)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20, vlm=None)
    out, _, _ = _merge_same_label([a, b])
    assert out[0].vlm_confidence is None

    c = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10, vlm=None)
    d = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20, vlm=0.7)
    out, _, _ = _merge_same_label([c, d])
    assert out[0].vlm_confidence == 0.7
