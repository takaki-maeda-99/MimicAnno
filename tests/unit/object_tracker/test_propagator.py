"""Tests for Propagator.run (spec §2.4.1, Task 8).

Covers:
1. Single-call contract: runtime.propagate called exactly once.
2. Gap consolidation: contiguous missing frames => 1 GapEvent.
3. Low-conf gap reason: score below threshold => sam3_low_conf.
4. Mixed-reason gap: any low_conf in range => sam3_low_conf.
5. Re-acquisition same id: high IoU after gap => same track_id.
6. Re-acquisition new id: low IoU after gap => new Track with index+1.
7. Primary marking — happy path: first object prompt is primary.
8. Primary marking — first prompt failed Step B: second prompt is primary.
9. Deterministic ordering: sorted by (role_order, slug, index).
10. Last frame inclusion: n_frames - 1 always in iterator.
11. Empty-samples track: all frames None => track with 1 GapEvent[0, n_frames-1].
12. Stable ordering: multiple roles + multiple prompts per role.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.config import TrackingConfig
from mimicanno.object_tracker.fixtures import FixtureSAM3Tracker
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    Propagator,
    Track,
    TrackingPlan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VIDEO = Path("/dev/null")


def _make_config(
    *,
    min_track_score: float = 0.30,
    reacquisition_iou_threshold: float = 0.30,
    max_gap_frames: int = 30,
    stride: int | None = None,
) -> TrackingConfig:
    return TrackingConfig(
        min_track_score=min_track_score,
        reacquisition_iou_threshold=reacquisition_iou_threshold,
        max_gap_frames=max_gap_frames,
        track_stride_frames=stride,
    )


def _plan_single_object(
    prompt: str = "red block",
    bbox: BBox | None = None,
) -> TrackingPlan:
    if bbox is None:
        bbox = BBox(0.1, 0.1, 0.2, 0.2)
    return TrackingPlan(
        entities=EntityPlan(
            object_prompts=[prompt],
            target_prompts=[],
            tool_prompts=[],
        ),
        initial_detections={("object", prompt): bbox},
        failed_prompts=[],
    )


def _run(
    fixture: FixtureSAM3Tracker,
    plan: TrackingPlan,
    *,
    n_frames: int,
    stride: int,
    config: TrackingConfig | None = None,
) -> list[Track]:
    if config is None:
        config = _make_config(stride=stride)
    return Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=30.0,
        n_frames=n_frames,
        stride=stride,
        config=config,
    )


# ---------------------------------------------------------------------------
# Test 1: Single-call contract
# ---------------------------------------------------------------------------


def test_single_call_contract() -> None:
    """runtime.propagate is called exactly once per Propagator.run call."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    fixture = FixtureSAM3Tracker(
        propagation_results={
            0: {"red block": (bbox, 0.95)},
            1: {"red block": (bbox, 0.95)},
            2: {"red block": (bbox, 0.95)},
        }
    )
    plan = _plan_single_object("red block", bbox)
    _run(fixture, plan, n_frames=3, stride=1)
    assert fixture.propagate_call_count == 1


# ---------------------------------------------------------------------------
# Test 2: Gap consolidation — contiguous missing frames => 1 GapEvent
# ---------------------------------------------------------------------------


def test_gap_consolidation_single_gap_event() -> None:
    """Frames 10-20 missing for red_block => 1 GapEvent(from_frame=10, to_frame=20)."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    # stride=10, n_frames=100: iterator = [0, 10, 20, 30, ..., 90, 99]
    # Frames 10 and 20 are None => gap from 10 to 20
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox, 0.95)},
        10: {"red block": None},
        20: {"red block": None},
        30: {"red block": (bbox, 0.95)},
    }
    # Fill remaining stride frames with detections
    for f in [40, 50, 60, 70, 80, 90, 99]:
        prop_results[f] = {"red block": (bbox, 0.95)}

    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=10)
    tracks = _run(fixture, plan, n_frames=100, stride=10, config=config)

    assert len(tracks) == 1
    track = tracks[0]
    assert len(track.gap_events) == 1
    gap = track.gap_events[0]
    assert gap.from_frame == 10
    assert gap.to_frame == 20
    assert gap.reason == "sam3_lost"


# ---------------------------------------------------------------------------
# Test 3: Low-conf gap reason
# ---------------------------------------------------------------------------


def test_low_conf_gap_reason() -> None:
    """Score below min_track_score => GapEvent.reason == 'sam3_low_conf'."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    low_score = 0.10  # below threshold of 0.30
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox, 0.95)},
        1: {"red block": (bbox, low_score)},  # low conf => gap
        2: {"red block": (bbox, 0.95)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = _run(fixture, plan, n_frames=3, stride=1, config=config)

    assert len(tracks) == 1
    assert len(tracks[0].gap_events) == 1
    assert tracks[0].gap_events[0].reason == "sam3_low_conf"
    assert tracks[0].gap_events[0].from_frame == 1
    assert tracks[0].gap_events[0].to_frame == 1


# ---------------------------------------------------------------------------
# Test 4: Mixed-reason gap — any low_conf => sam3_low_conf
# ---------------------------------------------------------------------------


def test_mixed_reason_gap_is_low_conf() -> None:
    """Range has 1 sam3_lost + 1 sam3_low_conf frame => consolidated reason = sam3_low_conf."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    low_score = 0.10
    # stride=1, frames: 0(good), 1(None=lost), 2(low_conf), 3(good)
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox, 0.95)},
        1: {"red block": None},           # sam3_lost
        2: {"red block": (bbox, low_score)},  # sam3_low_conf
        3: {"red block": (bbox, 0.95)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = _run(fixture, plan, n_frames=4, stride=1, config=config)

    assert len(tracks) == 1
    assert len(tracks[0].gap_events) == 1
    gap = tracks[0].gap_events[0]
    assert gap.from_frame == 1
    assert gap.to_frame == 2
    assert gap.reason == "sam3_low_conf"


# ---------------------------------------------------------------------------
# Test 5: Re-acquisition same track_id (high IoU)
# ---------------------------------------------------------------------------


def test_reacquisition_same_track_id_high_iou() -> None:
    """After gap > max_gap_frames, new bbox overlaps old bbox => same track_id (index 0)."""
    # bbox_a at frame 0, gap from 1 to 109, bbox close to bbox_a at frame 110
    bbox_a = BBox(0.1, 0.1, 0.3, 0.3)
    bbox_close = BBox(0.12, 0.12, 0.3, 0.3)  # very close to bbox_a, high IoU
    # Verify IoU > 0.3
    assert bbox_a.iou(bbox_close) > 0.30

    # stride=10, n_frames=120: frames [0, 10, 20, ..., 110, 119]
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox_a, 0.95)},
    }
    # Frames 10..100 are None (no detection)
    for f in range(10, 110, 10):
        prop_results[f] = {"red block": None}
    # Frame 110: re-acquired with close bbox
    prop_results[110] = {"red block": (bbox_close, 0.90)}
    prop_results[119] = {"red block": (bbox_close, 0.90)}

    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox_a)
    # max_gap_frames=30: gap from frame 0 to 110 is 110 frames > 30 => triggers re-acq check
    config = _make_config(max_gap_frames=30, reacquisition_iou_threshold=0.30, stride=10)
    tracks = _run(fixture, plan, n_frames=120, stride=10, config=config)

    # Should be 1 track (same track_id), index 0
    assert len(tracks) == 1
    assert tracks[0].index == 0
    assert tracks[0].track_id == "obj:object:red_block:0"
    # Should have both samples: frame 0 and frames 110, 119
    frame_nums = [s.frame for s in tracks[0].samples]
    assert 0 in frame_nums
    assert 110 in frame_nums


# ---------------------------------------------------------------------------
# Test 6: Re-acquisition new track_id (low IoU)
# ---------------------------------------------------------------------------


def test_reacquisition_new_track_id_low_iou() -> None:
    """After gap > max_gap_frames, new bbox far from old bbox => new Track with index 1."""
    bbox_a = BBox(0.0, 0.0, 0.2, 0.2)
    bbox_far = BBox(0.7, 0.7, 0.2, 0.2)  # completely separate from bbox_a
    assert bbox_a.iou(bbox_far) < 0.30

    # stride=10, n_frames=120: frames [0, 10, ..., 110, 119]
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox_a, 0.95)},
    }
    for f in range(10, 110, 10):
        prop_results[f] = {"red block": None}
    prop_results[110] = {"red block": (bbox_far, 0.90)}
    prop_results[119] = {"red block": (bbox_far, 0.90)}

    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox_a)
    config = _make_config(max_gap_frames=30, reacquisition_iou_threshold=0.30, stride=10)
    tracks = _run(fixture, plan, n_frames=120, stride=10, config=config)

    # Should be 2 tracks: index 0 (before gap) and index 1 (after gap)
    assert len(tracks) == 2
    indices = sorted(t.index for t in tracks)
    assert indices == [0, 1]
    for track in tracks:
        assert track.role == "object"
        assert track.prompt == "red block"
        assert track.slug == "red_block"

    track0 = next(t for t in tracks if t.index == 0)
    track1 = next(t for t in tracks if t.index == 1)
    assert track0.track_id == "obj:object:red_block:0"
    assert track1.track_id == "obj:object:red_block:1"

    # track0 should have frame 0
    assert any(s.frame == 0 for s in track0.samples)
    # track1 should have frame 110
    assert any(s.frame == 110 for s in track1.samples)


# ---------------------------------------------------------------------------
# Test 7: Primary marking — happy path
# ---------------------------------------------------------------------------


def test_primary_marking_happy_path() -> None:
    """First object prompt in order is primary=True; second is primary=False."""
    bbox_r = BBox(0.1, 0.1, 0.2, 0.2)
    bbox_b = BBox(0.5, 0.5, 0.2, 0.2)
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox_r, 0.95), "blue block": (bbox_b, 0.90)},
        1: {"red block": (bbox_r, 0.95), "blue block": (bbox_b, 0.90)},
        2: {"red block": (bbox_r, 0.95), "blue block": (bbox_b, 0.90)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block", "blue block"],
            target_prompts=[],
            tool_prompts=[],
        ),
        initial_detections={
            ("object", "red block"): bbox_r,
            ("object", "blue block"): bbox_b,
        },
        failed_prompts=[],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=30.0,
        n_frames=3,
        stride=1,
        config=config,
    )

    assert len(tracks) == 2
    by_prompt = {t.prompt: t for t in tracks}
    assert by_prompt["red block"].primary is True
    assert by_prompt["blue block"].primary is False


# ---------------------------------------------------------------------------
# Test 8: Primary marking — first prompt failed Step B
# ---------------------------------------------------------------------------


def test_primary_marking_first_prompt_failed() -> None:
    """If first prompt failed Step B, second prompt becomes primary."""
    bbox_b = BBox(0.5, 0.5, 0.2, 0.2)
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"blue block": (bbox_b, 0.90)},
        1: {"blue block": (bbox_b, 0.90)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    # "red block" failed Step B (in failed_prompts, not in initial_detections)
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block", "blue block"],
            target_prompts=[],
            tool_prompts=[],
        ),
        initial_detections={
            ("object", "blue block"): bbox_b,
        },
        failed_prompts=[("object", "red block")],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=30.0,
        n_frames=2,
        stride=1,
        config=config,
    )

    assert len(tracks) == 1
    assert tracks[0].prompt == "blue block"
    assert tracks[0].primary is True


# ---------------------------------------------------------------------------
# Test 9: Deterministic ordering
# ---------------------------------------------------------------------------


def test_deterministic_ordering() -> None:
    """Tracks sorted by (role_order, slug, index): object < target < tool."""
    bbox_r = BBox(0.1, 0.1, 0.2, 0.2)
    bbox_b = BBox(0.3, 0.3, 0.2, 0.2)
    bbox_t = BBox(0.5, 0.5, 0.2, 0.2)
    bbox_g = BBox(0.7, 0.7, 0.1, 0.1)

    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {
            "red block": (bbox_r, 0.95),
            "blue block": (bbox_b, 0.90),
            "bin A": (bbox_t, 0.85),
            "gripper": (bbox_g, 0.80),
        }
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block", "blue block"],
            target_prompts=["bin A"],
            tool_prompts=["gripper"],
        ),
        initial_detections={
            ("object", "red block"): bbox_r,
            ("object", "blue block"): bbox_b,
            ("target", "bin A"): bbox_t,
            ("tool", "gripper"): bbox_g,
        },
        failed_prompts=[],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=1.0,
        n_frames=1,
        stride=1,
        config=config,
    )

    assert len(tracks) == 4
    roles = [t.role for t in tracks]
    # Objects come before targets, targets before tools
    assert roles.index("object") < roles.index("target")
    assert roles.index("target") < roles.index("tool")

    # Within objects, blue_block slug < red_block slug alphabetically
    object_tracks = [t for t in tracks if t.role == "object"]
    assert object_tracks[0].slug == "blue_block"
    assert object_tracks[1].slug == "red_block"


# ---------------------------------------------------------------------------
# Test 10: Last frame inclusion
# ---------------------------------------------------------------------------


def test_last_frame_inclusion() -> None:
    """n_frames - 1 is always in the iterator even if not stride-aligned."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    # stride=10, n_frames=15: iterator should be [0, 10, 14]
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox, 0.95)},
        10: {"red block": (bbox, 0.95)},
        14: {"red block": (bbox, 0.95)},  # n_frames-1 = 14
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=10)
    tracks = _run(fixture, plan, n_frames=15, stride=10, config=config)

    assert len(tracks) == 1
    frame_nums = [s.frame for s in tracks[0].samples]
    assert 14 in frame_nums  # n_frames - 1 must be visited


# ---------------------------------------------------------------------------
# Test 11: Empty-samples track (all frames lost immediately)
# ---------------------------------------------------------------------------


def test_empty_samples_track_returned() -> None:
    """Even if all frames yield None for a prompt, the Track is returned with empty samples."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    # All frames return None for "red block"
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": None},
        1: {"red block": None},
        2: {"red block": None},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = _run(fixture, plan, n_frames=3, stride=1, config=config)

    assert len(tracks) == 1
    track = tracks[0]
    assert track.samples == []
    assert len(track.gap_events) == 1
    gap = track.gap_events[0]
    assert gap.from_frame == 0
    assert gap.to_frame == 2  # n_frames - 1
    assert gap.reason == "sam3_lost"


# ---------------------------------------------------------------------------
# Test 12: Stable ordering — multiple roles + multiple prompts per role
# ---------------------------------------------------------------------------


def test_stable_ordering_multiple_roles() -> None:
    """Full stable ordering test: (role_order, slug, index) sort."""
    bbox = BBox(0.1, 0.1, 0.1, 0.1)
    bbox2 = BBox(0.3, 0.3, 0.1, 0.1)
    bbox3 = BBox(0.5, 0.5, 0.1, 0.1)
    bbox4 = BBox(0.7, 0.7, 0.1, 0.1)

    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {
            "apple": (bbox, 0.9),
            "zebra": (bbox2, 0.9),
            "mango": (bbox3, 0.9),
            "wrench": (bbox4, 0.9),
        }
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["zebra", "apple"],  # alphabetically: apple < zebra
            target_prompts=["mango"],
            tool_prompts=["wrench"],
        ),
        initial_detections={
            ("object", "zebra"): bbox2,
            ("object", "apple"): bbox,
            ("target", "mango"): bbox3,
            ("tool", "wrench"): bbox4,
        },
        failed_prompts=[],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=1.0,
        n_frames=1,
        stride=1,
        config=config,
    )

    assert len(tracks) == 4
    slugs_in_order = [t.slug for t in tracks]
    # Expected: apple (object), zebra (object), mango (target), wrench (tool)
    assert slugs_in_order == ["apple", "zebra", "mango", "wrench"]


# ---------------------------------------------------------------------------
# Test 13: Track ID format
# ---------------------------------------------------------------------------


def test_track_id_format() -> None:
    """track_id follows obj:<role>:<slug>:<index> format."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    prop_results = {0: {"red block": (bbox, 0.95)}}
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = _run(fixture, plan, n_frames=1, stride=1, config=config)

    assert tracks[0].track_id == "obj:object:red_block:0"
    assert tracks[0].slug == "red_block"
    assert tracks[0].index == 0


# ---------------------------------------------------------------------------
# Test 14: All-roles primary marking
# ---------------------------------------------------------------------------


def test_primary_marking_each_role_independent() -> None:
    """Primary marking is independent per role: each role has its own primary."""
    bbox_r = BBox(0.1, 0.1, 0.1, 0.1)
    bbox_t = BBox(0.3, 0.3, 0.1, 0.1)
    bbox_g = BBox(0.5, 0.5, 0.1, 0.1)

    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {
            "red block": (bbox_r, 0.95),
            "bin A": (bbox_t, 0.90),
            "gripper": (bbox_g, 0.85),
        }
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block"],
            target_prompts=["bin A"],
            tool_prompts=["gripper"],
        ),
        initial_detections={
            ("object", "red block"): bbox_r,
            ("target", "bin A"): bbox_t,
            ("tool", "gripper"): bbox_g,
        },
        failed_prompts=[],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=1.0,
        n_frames=1,
        stride=1,
        config=config,
    )

    assert len(tracks) == 3
    for track in tracks:
        # Each role has exactly one prompt => that track is primary
        assert track.primary is True


# ---------------------------------------------------------------------------
# Test 15: time_sec is correctly computed from frame and fps
# ---------------------------------------------------------------------------


def test_track_sample_time_sec() -> None:
    """TrackSample.time_sec = frame / fps."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    prop_results = {
        0: {"red block": (bbox, 0.95)},
        10: {"red block": (bbox, 0.90)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=10)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=10.0,
        n_frames=11,
        stride=10,
        config=config,
    )

    assert len(tracks) == 1
    samples = sorted(tracks[0].samples, key=lambda s: s.frame)
    assert samples[0].time_sec == pytest.approx(0.0)   # 0 / 10.0
    assert samples[1].time_sec == pytest.approx(1.0)   # 10 / 10.0


# ---------------------------------------------------------------------------
# Test 16: Gap within max_gap_frames — no re-acquisition check
# ---------------------------------------------------------------------------


def test_gap_within_max_gap_no_reacq_split() -> None:
    """Gap <= max_gap_frames: same track regardless of bbox distance."""
    bbox_a = BBox(0.0, 0.0, 0.2, 0.2)
    bbox_far = BBox(0.7, 0.7, 0.2, 0.2)
    assert bbox_a.iou(bbox_far) < 0.30  # Would split if gap > max_gap_frames

    # stride=1, frames: 0(good), 1(None), 2(far bbox)
    # gap = 1 frame, max_gap_frames=30 => no re-acq check
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox_a, 0.95)},
        1: {"red block": None},
        2: {"red block": (bbox_far, 0.90)},
    }
    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox_a)
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = _run(fixture, plan, n_frames=3, stride=1, config=config)

    # Only 1 track (no split)
    assert len(tracks) == 1
    assert tracks[0].index == 0


# ---------------------------------------------------------------------------
# Test 17: Empty initial_detections => no tracks
# ---------------------------------------------------------------------------


def test_no_initial_detections_returns_empty() -> None:
    """If plan has no initial_detections, return empty list."""
    fixture = FixtureSAM3Tracker(propagation_results={})
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block"],
            target_prompts=[],
            tool_prompts=[],
        ),
        initial_detections={},
        failed_prompts=[("object", "red block")],
    )
    config = _make_config(max_gap_frames=30, stride=1)
    tracks = Propagator().run(
        runtime=fixture,
        plan=plan,
        video_path=_VIDEO,
        fps=1.0,
        n_frames=1,
        stride=1,
        config=config,
    )
    assert tracks == []


# ---------------------------------------------------------------------------
# Test 18: Empty-samples track with stride < n_frames - 1 covers full range
# ---------------------------------------------------------------------------


def test_empty_samples_track_with_stride_covers_full_range() -> None:
    """Empty-samples track (all frames None) with stride < n_frames-1 yields gap [0, n_frames-1].

    This is the spec §2.4.2 requirement: "Tracks with empty samples are
    returned even if `samples == []`. Such tracks have `gap_events`
    covering `[0, n_frames - 1]`."

    Bug scenario: stride=10, n_frames=100 => iterator has 11 frames.
    All return None => resulting gap was [0, 90] instead of [0, 99].
    """
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    # stride=10, n_frames=100: iterator = [0, 10, 20, ..., 90, 99]
    # All 11 frames return None
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {}
    for f in range(0, 100, 10):
        prop_results[f] = {"red block": None}
    prop_results[99] = {"red block": None}  # Last frame always included

    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=10)
    tracks = _run(fixture, plan, n_frames=100, stride=10, config=config)

    assert len(tracks) == 1
    track = tracks[0]
    assert track.samples == []
    assert len(track.gap_events) == 1
    gap = track.gap_events[0]
    assert gap.from_frame == 0
    assert gap.to_frame == 99  # SPEC REQUIREMENT: must be n_frames - 1
    assert gap.reason == "sam3_lost"


# ---------------------------------------------------------------------------
# Test 19: Empty-samples track with low-conf reason
# ---------------------------------------------------------------------------


def test_empty_samples_track_low_conf_reason() -> None:
    """Empty-samples track where all detections have low score => reason == 'sam3_low_conf'.

    When a track has no samples because all frames failed the score threshold,
    the synthesized gap should have reason='sam3_low_conf' (not 'sam3_lost').
    """
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    low_score = 0.10  # below min_track_score=0.30
    # stride=10, n_frames=100: iterator = [0, 10, 20, ..., 90, 99]
    # All 11 frames return detections but with low score
    prop_results: dict[int, dict[str, tuple[BBox, float] | None]] = {}
    for f in range(0, 100, 10):
        prop_results[f] = {"red block": (bbox, low_score)}
    prop_results[99] = {"red block": (bbox, low_score)}  # Last frame

    fixture = FixtureSAM3Tracker(propagation_results=prop_results)
    plan = _plan_single_object("red block", bbox)
    config = _make_config(max_gap_frames=30, stride=10, min_track_score=0.30)
    tracks = _run(fixture, plan, n_frames=100, stride=10, config=config)

    assert len(tracks) == 1
    track = tracks[0]
    assert track.samples == []
    assert len(track.gap_events) == 1
    gap = track.gap_events[0]
    assert gap.from_frame == 0
    assert gap.to_frame == 99
    assert gap.reason == "sam3_low_conf"
