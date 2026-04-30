"""SubtaskSegment.to_sidecar_row + from_row round-trip (Phase 5, Task 8).

Spec §3.1 sidecar row shape; spec §3.3 documents that BoundaryRef.per-source
per-edge scores live in ``boundaries.json`` and are not preserved through the
sidecar (lossy field). The round trip is therefore segment-equal modulo
``start_boundary.candidate_id`` / ``time`` and any score map outside
``BoundaryRef.score`` / ``BoundaryRef.sources``.
"""

from __future__ import annotations

from mimicanno.schema import BoundaryRef, SubtaskSegment


def _make_boundary(score: float, sources: list[str]) -> BoundaryRef:
    return BoundaryRef(
        candidate_id=None,
        time=0.0,
        sources=sources,
        score=score,
    )


def _make_segment(
    *,
    phase: str = "unlabeled",
    label_source: str = "signals_only",
    smoothing_ops: list[str] | None = None,
    vlm_confidence: float | None = None,
    reviewed: bool = False,
    reviewer_id: str | None = None,
    failure_flags: list[str] | None = None,
    object_track_ids: list[str] | None = None,
) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id="ep0_seg0",
        episode_id="ep0",
        start_frame=0,
        end_frame=10,
        start_time=0.0,
        end_time=1.0,
        phase=phase,
        verb=None,
        object=None,
        target=None,
        failure_flags=failure_flags if failure_flags is not None else [],
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False,
        object_track_ids=object_track_ids if object_track_ids is not None else [],
        label_version="manipulation.v1",
        start_boundary=_make_boundary(0.8, ["episode_start"]),
        end_boundary=_make_boundary(0.6, ["gripper_drop"]),
        boundary_confidence=0.6,
        vlm_confidence=vlm_confidence,
        overall_confidence=0.5,
        evidence=None,
        reviewed=reviewed,
        reviewer_id=reviewer_id,
        smoothing_ops=smoothing_ops if smoothing_ops is not None else [],
    )


def test_round_trip_minimal_segment() -> None:
    seg = _make_segment()
    row = seg.to_sidecar_row()
    assert row["phase"] == "unlabeled"
    assert row["start_frame"] == 0
    assert row["end_frame"] == 10
    assert row["failure_flags"] == []
    assert row["smoothing_ops"] == []
    assert row["boundary_source_start"] == ["episode_start"]
    assert row["boundary_source_end"] == ["gripper_drop"]
    # min(start_boundary.score, end_boundary.score) = min(0.8, 0.6)
    assert row["boundary_confidence"] == 0.6

    seg2 = SubtaskSegment.from_row(row)
    assert seg2.phase == seg.phase
    assert seg2.start_frame == seg.start_frame
    assert seg2.end_frame == seg.end_frame
    assert seg2.failure_flags == []
    assert seg2.start_boundary.sources == ["episode_start"]
    assert seg2.end_boundary.sources == ["gripper_drop"]


def test_round_trip_full_phase_4_segment() -> None:
    seg = _make_segment(
        phase="approach",
        label_source="vlm_robot_state_only",
        smoothing_ops=["merge_same_label", "viterbi_relabel"],
        vlm_confidence=0.92,
        reviewed=True,
        reviewer_id="alice",
    )
    row = seg.to_sidecar_row()
    assert row["smoothing_ops"] == ["merge_same_label", "viterbi_relabel"]
    assert row["vlm_confidence"] == 0.92
    assert row["reviewed"] is True
    assert row["reviewer_id"] == "alice"
    assert row["label_source"] == "vlm_robot_state_only"

    seg2 = SubtaskSegment.from_row(row)
    assert seg2.smoothing_ops == ["merge_same_label", "viterbi_relabel"]
    assert seg2.vlm_confidence == 0.92
    assert seg2.reviewed is True
    assert seg2.reviewer_id == "alice"
    assert seg2.label_source == "vlm_robot_state_only"


def test_round_trip_with_failure_flags_and_object_tracks() -> None:
    seg = _make_segment(
        phase="grasp",
        failure_flags=["object_slipped"],
        object_track_ids=["obj_001", "tgt_001"],
    )
    row = seg.to_sidecar_row()
    assert row["failure_flags"] == ["object_slipped"]
    assert row["object_track_ids"] == ["obj_001", "tgt_001"]

    seg2 = SubtaskSegment.from_row(row)
    assert seg2.failure_flags == ["object_slipped"]
    assert seg2.object_track_ids == ["obj_001", "tgt_001"]


def test_from_row_ignores_extra_provenance_columns() -> None:
    seg = _make_segment()
    row = seg.to_sidecar_row()
    row["episode_index"] = 0
    row["segment_index"] = 0
    row["run_hash"] = "sha256:00"
    row["config_hash"] = "sha256:01"
    row["input_hash"] = "sha256:02"
    row["pipeline_phase"] = 4
    row["mimicanno_version"] = "0.1.0"
    row["generated_at"] = "2026-04-30T00:00:00Z"
    seg2 = SubtaskSegment.from_row(row)
    assert seg2.segment_id == seg.segment_id
