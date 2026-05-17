"""Phase 6: EditEvent old_value/new_value/pre_edit_overall_confidence round-trip."""
from __future__ import annotations

from mimicanno.schema import EditEvent


def test_p17_back_compat_03_event_loads_with_none_values() -> None:
    # 0.3.0-shaped EditEvent (no old_value/new_value/pre_edit_overall_confidence).
    d = {
        "edit_type": "relabel",
        "segment_id": "seg-001",
        "edited_at": "2026-05-17T15:30:00Z",
        "reviewer": None,
        "client_edit_duration_ms": 420,
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value is None
    assert ev.new_value is None
    assert ev.pre_edit_overall_confidence is None


def test_p3_labels_event_round_trip_full_4_field_tuple() -> None:
    d = {
        "edit_type": "labels",
        "segment_id": "seg-002",
        "edited_at": "2026-05-17T15:31:00Z",
        "reviewer": None,
        "client_edit_duration_ms": 1000,
        "old_value": {
            "kind": "labels",
            "verb": "approach",
            "object": "cube",
            "target": None,
            "failure_flags": [],
        },
        "new_value": {
            "kind": "labels",
            "verb": "grasp",
            "object": "cube",
            "target": None,
            "failure_flags": [],
        },
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value == {
        "kind": "labels",
        "verb": "approach",
        "object": "cube",
        "target": None,
        "failure_flags": [],
    }
    assert ev.new_value["verb"] == "grasp"
    # Round-trip through to_dict / from_dict.
    again = EditEvent.from_dict(ev.to_dict())
    assert again == ev


def test_p4_boundary_event_uses_int_frame() -> None:
    d = {
        "edit_type": "boundary",
        "segment_id": "seg-003",
        "edited_at": "2026-05-17T15:32:00Z",
        "reviewer": None,
        "client_edit_duration_ms": None,
        "old_value": {"kind": "boundary", "value": 120},
        "new_value": {"kind": "boundary", "value": 145},
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value == {"kind": "boundary", "value": 120}
    assert isinstance(ev.new_value["value"], int)


def test_pre_edit_overall_confidence_round_trip() -> None:
    d = {
        "edit_type": "relabel",
        "segment_id": "seg-004",
        "edited_at": "2026-05-17T15:33:00Z",
        "reviewer": None,
        "client_edit_duration_ms": None,
        "old_value": {"kind": "relabel", "value": "approach_object"},
        "new_value": {"kind": "relabel", "value": "grasp_object"},
        "pre_edit_overall_confidence": 0.72,
    }
    ev = EditEvent.from_dict(d)
    assert ev.pre_edit_overall_confidence == 0.72
    assert ev.to_dict()["pre_edit_overall_confidence"] == 0.72
