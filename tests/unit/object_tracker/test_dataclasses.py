"""Object-tracker core dataclasses (spec §2.2, §2.4).

Tests cover BBox math (iou, center, validation), TrackSample / GapEvent /
Track field invariants, EntityPlan helpers, and TrackingPlan tuple-key
disambiguation."""

from __future__ import annotations

import pytest

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    GapEvent,
    Track,
    TrackingPlan,
    TrackSample,
)

# ---- BBox ----

def test_bbox_center() -> None:
    b = BBox(0.10, 0.20, 0.40, 0.30)  # x, y, w, h
    cx, cy = b.center
    assert cx == pytest.approx(0.30)
    assert cy == pytest.approx(0.35)


def test_bbox_iou_identical() -> None:
    b = BBox(0.0, 0.0, 0.5, 0.5)
    assert b.iou(b) == pytest.approx(1.0)


def test_bbox_iou_disjoint() -> None:
    a = BBox(0.0, 0.0, 0.10, 0.10)
    b = BBox(0.50, 0.50, 0.10, 0.10)
    assert a.iou(b) == 0.0


def test_bbox_iou_partial_overlap() -> None:
    """Two half-width boxes offset by 0.25 in x: overlap = 0.25 x 1.0 = 0.25;
    union = 0.5 + 0.5 - 0.25 = 0.75; iou = 1/3."""
    a = BBox(0.0, 0.0, 0.5, 1.0)
    b = BBox(0.25, 0.0, 0.5, 1.0)
    assert a.iou(b) == pytest.approx(1.0 / 3.0)


def test_bbox_iou_subset() -> None:
    """A is fully inside B: iou = area(A) / area(B)."""
    a = BBox(0.25, 0.25, 0.50, 0.50)
    b = BBox(0.0, 0.0, 1.0, 1.0)
    assert a.iou(b) == pytest.approx(0.25)


def test_bbox_validation_rejects_negative_dims() -> None:
    with pytest.raises(ValueError):
        BBox(0.0, 0.0, -0.1, 0.5)
    with pytest.raises(ValueError):
        BBox(0.0, 0.0, 0.5, 0.0)


def test_bbox_validation_rejects_out_of_unit_square() -> None:
    with pytest.raises(ValueError):
        BBox(0.6, 0.0, 0.5, 0.5)  # x + w > 1
    with pytest.raises(ValueError):
        BBox(-0.1, 0.0, 0.5, 0.5)  # x < 0


# ---- TrackSample / GapEvent / Track ----

def test_tracksample_fields() -> None:
    s = TrackSample(frame=10, time_sec=0.333, bbox=BBox(0.1, 0.1, 0.1, 0.1), score=0.9)
    assert s.frame == 10
    assert s.time_sec == pytest.approx(0.333)
    assert s.score == pytest.approx(0.9)


def test_gap_event_reasons_restricted() -> None:
    """sam3_reacquired was REMOVED from GapEvent.reason in the GPT-review
    round (spec §2.4 GapEvent docstring). Only sam3_lost / sam3_low_conf are
    valid."""
    GapEvent(from_frame=5, to_frame=10, reason="sam3_lost")
    GapEvent(from_frame=5, to_frame=10, reason="sam3_low_conf")


def test_track_with_samples_and_gaps() -> None:
    t = Track(
        track_id="obj:object:red_block:0",
        role="object",
        prompt="red block",
        slug="red_block",
        index=0,
        primary=True,
        samples=[TrackSample(0, 0.0, BBox(0, 0, 0.1, 0.1), 0.95)],
        gap_events=[GapEvent(from_frame=10, to_frame=20, reason="sam3_lost")],
    )
    assert t.role == "object"
    assert len(t.samples) == 1
    assert len(t.gap_events) == 1
    assert t.primary is True


# ---- EntityPlan ----

def test_entity_plan_all_prompts_with_role_ordering() -> None:
    """spec §2.2: stable ordering — objects, then targets, then tools;
    within each role, original order from Gemma."""
    ep = EntityPlan(
        object_prompts=["red block", "blue block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
    )
    assert ep.all_prompts_with_role() == [
        ("object", "red block"),
        ("object", "blue block"),
        ("target", "bin A"),
        ("tool", "gripper"),
    ]


def test_entity_plan_empty_objects_yields_no_object_entries() -> None:
    ep = EntityPlan(object_prompts=[], target_prompts=["x"], tool_prompts=[])
    rolled = ep.all_prompts_with_role()
    assert ("target", "x") in rolled
    assert all(r != "object" for r, _ in rolled)


# ---- TrackingPlan ----

def test_tracking_plan_initial_detections_uses_tuple_key() -> None:
    """spec §2.4.0: cross-role duplicates are preserved via tuple keys.
    object='red block' AND target='red block' yield 2 distinct entries."""
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block"],
            target_prompts=["red block"],
            tool_prompts=[],
        ),
        initial_detections={
            ("object", "red block"): BBox(0.1, 0.1, 0.1, 0.1),
            ("target", "red block"): BBox(0.6, 0.6, 0.1, 0.1),
        },
        failed_prompts=[],
    )
    assert len(plan.initial_detections) == 2
    assert plan.initial_detections[("object", "red block")].x == pytest.approx(0.1)
    assert plan.initial_detections[("target", "red block")].x == pytest.approx(0.6)


def test_tracking_plan_failed_prompts_uses_tuple() -> None:
    """spec §2.4.0: failed_prompts is list[(role, prompt)], not list[str]."""
    plan = TrackingPlan(
        entities=EntityPlan(object_prompts=["x", "y"], target_prompts=[], tool_prompts=[]),
        initial_detections={("object", "y"): BBox(0, 0, 0.1, 0.1)},
        failed_prompts=[("object", "x")],
    )
    assert plan.failed_prompts == [("object", "x")]
