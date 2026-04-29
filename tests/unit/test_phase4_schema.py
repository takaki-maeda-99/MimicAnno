"""Phase 4 schema additions (spec §4)."""
from __future__ import annotations

import pytest

from mimicanno.schema import BoundaryRef, SmoothingSummary, SubtaskSegment


def _make_segment(**overrides: object) -> SubtaskSegment:
    """Build a minimal valid SubtaskSegment matching Phase 1-3 shape."""
    base: dict[str, object] = dict(
        segment_id="ep__seg0000",
        episode_id="ep",
        start_frame=0, end_frame=10,
        start_time=0.0, end_time=0.33,
        phase="grasp_object", verb="grasp", object="cube", target=None,
        failure_flags=[],
        label_source="vlm_with_object_state",
        object_state_unavailable=False,
        object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id="b0", time=0.0, sources=[], score=0.5),
        end_boundary=BoundaryRef(candidate_id="b1", time=0.33, sources=[], score=0.5),
        boundary_confidence=0.5,
        vlm_confidence=0.7,
        overall_confidence=0.59,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )
    base.update(overrides)
    return SubtaskSegment(**base)  # type: ignore[arg-type]


def test_subtask_segment_smoothing_ops_default_empty() -> None:
    seg = _make_segment()
    assert seg.smoothing_ops == []


def test_subtask_segment_smoothing_ops_explicit_value() -> None:
    seg = _make_segment(smoothing_ops=["merge_same_label"])
    assert seg.smoothing_ops == ["merge_same_label"]


def test_subtask_segment_smoothing_ops_unknown_op_rejected() -> None:
    with pytest.raises(ValueError, match="unknown smoothing op"):
        _make_segment(smoothing_ops=["not_an_op"])


def test_subtask_segment_smoothing_ops_none_rejected() -> None:
    with pytest.raises(TypeError, match="smoothing_ops must be"):
        _make_segment(smoothing_ops=None)


def test_subtask_segment_to_dict_emits_smoothing_ops_when_nonempty() -> None:
    seg = _make_segment(smoothing_ops=["merge_same_label", "viterbi_relabel"])
    d = seg.to_dict()
    assert d["smoothing_ops"] == ["merge_same_label", "viterbi_relabel"]


def test_subtask_segment_to_dict_emits_smoothing_ops_default_empty_list() -> None:
    seg = _make_segment()
    d = seg.to_dict()
    assert d["smoothing_ops"] == []


def test_smoothing_summary_to_dict_shape() -> None:
    s = SmoothingSummary(
        initial_segment_count=5,
        final_segment_count=3,
        merge_same_label_rounds=1,
        merge_same_label_collapses=1,
        merge_short_absorbs=1,
        viterbi_relabels=0,
        viterbi_skipped=False,
    )
    d = s.to_dict()
    assert d == {
        "initial_segment_count": 5,
        "final_segment_count": 3,
        "merge_same_label_rounds": 1,
        "merge_same_label_collapses": 1,
        "merge_short_absorbs": 1,
        "viterbi_relabels": 0,
        "viterbi_skipped": False,
    }


def test_smoothing_summary_from_dict_round_trip() -> None:
    s = SmoothingSummary(
        initial_segment_count=10, final_segment_count=8,
        merge_same_label_rounds=2, merge_same_label_collapses=2,
        merge_short_absorbs=0, viterbi_relabels=1, viterbi_skipped=False,
    )
    s2 = SmoothingSummary.from_dict(s.to_dict())
    assert s == s2


def test_annotation_schema_version_bumped_to_0_2_0() -> None:
    """Spec §4.4: annotation 0.1.0 -> 0.2.0."""
    from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
    assert ARTIFACT_SCHEMA_VERSIONS["annotation"] == "0.2.0"


def test_annotation_compat_block_major_unchanged() -> None:
    """Spec §4.4 + parent §6.6: COMPAT_BLOCK is keyed on MAJOR; 0.2.0 -> MAJOR=0,
    same as 0.1.0 -> MAJOR=0."""
    from mimicanno.schema_versions import COMPAT_BLOCK
    assert COMPAT_BLOCK["annotation"] == 0
