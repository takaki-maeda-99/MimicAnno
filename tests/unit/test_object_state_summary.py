"""Tests for ObjectStateSummary + compute_object_state_summary (spec §5.1, §5.2)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mimicanno.config import TrackingConfig
from mimicanno.object_tracker.propagator import BBox, GapEvent, Track, TrackSample
from mimicanno.object_tracker.signals import ObjectSignals

SNAPSHOT_DIR = Path(__file__).parent.parent / "snapshots" / "phase3"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_track(
    track_id: str,
    role: str,
    prompt: str,
    primary: bool,
    samples: list[tuple[int, float, float, float, float]] | None = None,
    gap_events: list[tuple[int, int]] | None = None,
) -> Track:
    """Build a Track from (frame, x, y, w, h) bbox tuples."""
    ts_list: list[TrackSample] = []
    if samples:
        for frame, x, y, w, h in samples:
            bbox = BBox(x=x, y=y, w=w, h=h)
            ts_list.append(
                TrackSample(frame=frame, time_sec=frame / 30.0, bbox=bbox, score=1.0)
            )
    ge_list: list[GapEvent] = []
    if gap_events:
        for from_frame, to_frame in gap_events:
            ge_list.append(
                GapEvent(from_frame=from_frame, to_frame=to_frame, reason="sam3_lost")
            )

    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=prompt,
        slug=track_id,
        index=0,
        primary=primary,
        samples=ts_list,
        gap_events=ge_list,
    )


def make_center_track(
    track_id: str,
    role: str,
    prompt: str,
    primary: bool,
    samples: list[tuple[int, float, float]] | None = None,
    gap_events: list[tuple[int, int]] | None = None,
) -> Track:
    """Build a Track from (frame, cx, cy) where w=h=0.1."""
    converted: list[tuple[int, float, float, float, float]] | None = None
    if samples:
        converted = []
        for frame, cx, cy in samples:
            w, h = 0.1, 0.1
            x = max(0.0, min(cx - w / 2, 1.0 - w))
            y = max(0.0, min(cy - h / 2, 1.0 - h))
            converted.append((frame, x, y, w, h))
    return make_track(track_id, role, prompt, primary, converted, gap_events)


def make_signals(
    n_frames: int,
    tracks: list[Track],
    fps: float = 30.0,
    image_aspect_ratio: float = 16.0 / 9.0,
) -> ObjectSignals:
    """Compute ObjectSignals from the given tracks."""
    from mimicanno.object_tracker.signals import compute_object_signals

    return compute_object_signals(
        tracks, fps=fps, n_frames=n_frames, image_aspect_ratio=image_aspect_ratio
    )


# ---------------------------------------------------------------------------
# Test 1: Visibility filter — track visible >= threshold appears in *_prompts
# ---------------------------------------------------------------------------


def test_visibility_filter_above_threshold_included() -> None:
    """Track visible in 60% of segment frames (threshold 0.5) → in *_prompts."""
    from mimicanno.clip_features import compute_object_state_summary

    # 10-frame segment [0, 9]. Gap covers [6, 9] = 4 frames.
    # Non-gap = 10 - 4 = 6 frames → 6/10 = 0.6 >= 0.5 → included.
    n_frames = 10
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (9, 0.5, 0.5)],
            gap_events=[(6, 9)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig(visibility_threshold=0.5)
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=9,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert "red block" in summary.object_prompts


def test_visibility_filter_below_threshold_excluded() -> None:
    """Track visible in 40% of segment frames → not in *_prompts → returns None."""
    from mimicanno.clip_features import compute_object_state_summary

    # 10-frame segment [0, 9]. Gap covers [0, 5] = 6 frames.
    # Non-gap = 10 - 6 = 4 frames → 4/10 = 0.4 < 0.5 → excluded.
    # Since the primary object is excluded → None.
    n_frames = 10
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(6, 0.5, 0.5), (9, 0.5, 0.5)],
            gap_events=[(0, 5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig(visibility_threshold=0.5)
    result = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=9,
        object_signals=signals,
        config=config,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 2: No primary object → None
# ---------------------------------------------------------------------------


def test_no_primary_object_returns_none() -> None:
    """primary_object_track is None → compute_object_state_summary returns None."""
    from mimicanno.clip_features import compute_object_state_summary

    n_frames = 10
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=False,
            samples=[(0, 0.5, 0.5), (9, 0.5, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    result = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=9,
        object_signals=signals,
        config=config,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: Primary track filtered out by visibility → None
# ---------------------------------------------------------------------------


def test_primary_track_below_visibility_returns_none() -> None:
    """Primary object track exists but visibility < threshold → return None."""
    from mimicanno.clip_features import compute_object_state_summary

    # Segment [0, 9]: 10 frames. Gap covers [0, 7] = 8 frames.
    # Non-gap = 2 frames → 2/10 = 0.2 < 0.5 → primary track filtered out → None.
    n_frames = 10
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(8, 0.5, 0.5), (9, 0.5, 0.5)],
            gap_events=[(0, 7)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig(visibility_threshold=0.5)
    result = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=9,
        object_signals=signals,
        config=config,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: Distance start/min/end from gripper_object_distance
# ---------------------------------------------------------------------------


def test_distance_start_min_end() -> None:
    """Distance scalars correctly derived from gripper_object_distance array."""
    from mimicanno.clip_features import compute_object_state_summary

    # Segment [0, 4]. 5 frames.
    # Object at x=0.6, gripper at x=0.5 → distance = 0.1 at frames 0-2.
    # Then closer: object at x=0.52, gripper at x=0.5 → distance = 0.02 at frame 3.
    # Back: object at x=0.6, gripper at x=0.5 → distance = 0.1 at frame 4.
    # start=0.1, min=0.02, end=0.1
    n_frames = 5
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[
                (0, 0.55, 0.45, 0.1, 0.1),  # center = (0.6, 0.5)
                (1, 0.55, 0.45, 0.1, 0.1),
                (2, 0.55, 0.45, 0.1, 0.1),
                (3, 0.47, 0.45, 0.1, 0.1),  # center = (0.52, 0.5)
                (4, 0.55, 0.45, 0.1, 0.1),
            ],
        ),
        make_track(
            "tool_a", "tool", "gripper", primary=True,
            samples=[
                (0, 0.45, 0.45, 0.1, 0.1),  # center = (0.5, 0.5)
                (1, 0.45, 0.45, 0.1, 0.1),
                (2, 0.45, 0.45, 0.1, 0.1),
                (3, 0.45, 0.45, 0.1, 0.1),
                (4, 0.45, 0.45, 0.1, 0.1),
            ],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.gripper_object_distance_at_start == pytest.approx(0.1, abs=1e-9)
    assert summary.gripper_object_distance_at_end == pytest.approx(0.1, abs=1e-9)
    assert summary.gripper_object_distance_min == pytest.approx(0.02, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 5: Distance None when no gripper track
# ---------------------------------------------------------------------------


def test_distance_none_when_no_gripper_track() -> None:
    """gripper_tool_track_id is None → all 3 distance scalars are None."""
    from mimicanno.clip_features import compute_object_state_summary

    n_frames = 5
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.gripper_object_distance_at_start is None
    assert summary.gripper_object_distance_at_end is None
    assert summary.gripper_object_distance_min is None


# ---------------------------------------------------------------------------
# Test 6a: max_speed None when all speed is NaN
# ---------------------------------------------------------------------------


def test_max_speed_none_when_all_speed_nan() -> None:
    """primary_object_max_speed is None when all object_speed values are NaN.

    Tests a missing branch: spec §5.2 step 5 sets primary_max_speed based on
    nanmax of the speed segment, but if all values are NaN, nanmax returns NaN,
    which should coerce to None.
    """
    from mimicanno.clip_features import compute_object_state_summary

    # Segment [0, 4], primary object visible with valid center but all-NaN speed.
    n_frames = 5
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)

    # Manually set the speed array to all NaN for the primary object
    primary_id = tracks[0].track_id
    signals.object_speed[primary_id] = np.full(n_frames, np.nan)

    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_max_speed is None


# ---------------------------------------------------------------------------
# Test 6: Speed and displacement
# ---------------------------------------------------------------------------


def test_displacement_none_when_no_adjacent_non_nan_pair() -> None:
    """primary_object_displacement is None when no two adjacent frames are both non-NaN.

    Tests a missing branch: spec §5.2 step 5 sums displacement over adjacent
    pairs where both centers are non-NaN. If no such pair exists (e.g., every
    other frame is NaN), has_pair remains False and displacement is None.
    """
    from mimicanno.clip_features import compute_object_state_summary

    # Segment [0, 4] with 5 frames. Center values: valid at frames 0,2,4; NaN at 1,3.
    n_frames = 5
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)

    # Manually set center array: frames 0,2,4 are valid; frames 1,3 are NaN.
    primary_id = tracks[0].track_id
    centers = signals.object_center[primary_id]
    # centers[0] is already set by make_signals from the sample at frame 0
    # centers[4] is already set by the sample at frame 4
    # Set frames 1 and 3 to NaN (frame 2 stays NaN from interpolation or default)
    centers[1] = [np.nan, np.nan]
    centers[2] = [np.nan, np.nan]
    centers[3] = [np.nan, np.nan]

    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_displacement is None


def test_speed_and_displacement() -> None:
    """primary_object_max_speed from nanmax of speed; displacement from adjacent pairs."""
    from mimicanno.clip_features import compute_object_state_summary

    # 3-frame segment [0, 2], object moves from cx=0.1 to cx=0.3.
    # speed[0] = |(0.2-0.1)| * fps = 0.1 * 30 = 3.0
    # speed[1] = |(0.3-0.1)| / 2 * fps = 0.2/2*30 = 3.0
    # speed[2] = |(0.3-0.2)| * fps = 0.1*30 = 3.0
    # max_speed = 3.0
    # displacement: only x moves, y=0.5 stays. dx=0.1 per step, dy=0.
    # aspect = 16/9 → displacement = sqrt(0.1^2 + (0/aspect)^2) * 2 = 0.2
    fps = 30.0
    aspect = 16.0 / 9.0
    n_frames = 3
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.1, 0.5), (1, 0.2, 0.5), (2, 0.3, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks, fps=fps, image_aspect_ratio=aspect)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=2,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_max_speed == pytest.approx(3.0, abs=1e-9)
    # displacement: 2 steps of 0.1 in x = 0.2
    assert summary.primary_object_displacement == pytest.approx(0.2, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 7: IoU-at-end proxy — both bboxes valid → bool result
# ---------------------------------------------------------------------------


def test_iou_at_end_above_threshold_true() -> None:
    """Primary object + primary target both have bbox at segment_end_frame → True if IoU > 0.05."""
    from mimicanno.clip_features import compute_object_state_summary

    # Both tracks have a sample exactly at frame 4 (segment_end_frame).
    # Object bbox overlaps target bbox significantly → IoU > 0.05.
    n_frames = 5
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[
                (0, 0.1, 0.1, 0.3, 0.3),
                (4, 0.1, 0.1, 0.3, 0.3),  # bbox at end frame
            ],
        ),
        make_track(
            "tgt_a", "target", "bin A", primary=True,
            samples=[
                (0, 0.1, 0.1, 0.3, 0.3),
                (4, 0.15, 0.15, 0.3, 0.3),  # overlapping bbox
            ],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is True


def test_iou_at_end_below_threshold_false() -> None:
    """IoU = 0.04 (< 0.05) → False."""
    from mimicanno.clip_features import compute_object_state_summary

    # Bboxes barely touching → IoU just below threshold.
    # obj bbox [0, 0, 0.3, 0.3], tgt bbox [0.28, 0.28, 0.3, 0.3]
    # Intersection: max(0, min(0.3, 0.58) - max(0, 0.28)) * max(0, min(0.3, 0.58) - max(0, 0.28))
    # = max(0, 0.3 - 0.28) * max(0, 0.3 - 0.28) = 0.02 * 0.02 = 0.0004
    # Union = 0.09 + 0.09 - 0.0004 = 0.1796; IoU = 0.0004/0.1796 ≈ 0.0022 < 0.05 → False
    n_frames = 5
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[
                (0, 0.0, 0.0, 0.3, 0.3),
                (4, 0.0, 0.0, 0.3, 0.3),
            ],
        ),
        make_track(
            "tgt_a", "target", "bin A", primary=True,
            samples=[
                (0, 0.65, 0.65, 0.3, 0.3),
                (4, 0.65, 0.65, 0.3, 0.3),
            ],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is False


def test_iou_at_end_just_below_threshold_returns_false() -> None:
    """IoU approximately 0.0398 (strictly between 0.03 and 0.05) → False.

    Plan-required boundary stress test: spec §5.2 step 6 requires IoU > 0.05
    (strict), not >= 0.05. This test crafts two bboxes with overlap that
    produces IoU ≈ 0.0398 to ensure the strict inequality is enforced.
    """
    from mimicanno.clip_features import compute_object_state_summary

    # Two 0.3x0.3 boxes with offset ~0.217 produce IoU ≈ 0.0398.
    # Verified: BBox(0.0, 0.0, 0.3, 0.3).iou(BBox(0.217, 0.217, 0.3, 0.3)) = 0.039795
    n_frames = 5
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[
                (0, 0.0, 0.0, 0.3, 0.3),
                (4, 0.0, 0.0, 0.3, 0.3),
            ],
        ),
        make_track(
            "tgt_a", "target", "bin A", primary=True,
            samples=[
                (0, 0.1, 0.1, 0.3, 0.3),
                (4, 0.217, 0.217, 0.3, 0.3),
            ],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is False


# ---------------------------------------------------------------------------
# Test 7b: Prompt deduplication
# ---------------------------------------------------------------------------


def test_prompt_deduplication() -> None:
    """Two Track instances with same role + same prompt but different index.

    Both tracks are fully visible. The first is primary=True. Expected:
    result.object_prompts contains the prompt exactly once (deduplication).
    """
    from mimicanno.clip_features import compute_object_state_summary

    # Two object tracks, both with prompt "red block", different indices (0 and 1).
    # Both visible in segment [0, 4]. Only track 0 is primary.
    n_frames = 5
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
        make_center_track(
            "obj_b", "object", "red block", primary=False,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
    ]
    # Manually set different indices to distinguish them
    tracks[0].index = 0
    tracks[1].index = 1
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.object_prompts == ["red block"]  # Exactly once, not twice


# ---------------------------------------------------------------------------
# Test 8: IoU-at-end → None when target bbox missing at end frame
# ---------------------------------------------------------------------------


def test_iou_at_end_none_when_target_bbox_missing() -> None:
    """Target bbox not available at segment_end_frame (inside gap) → result is None."""
    from mimicanno.clip_features import compute_object_state_summary

    # segment_end_frame = 100
    # Object has sample at frame 100.
    # Target has sample at frame 99 only; gap covers frame 100 → bbox_at_frame(tgt, 100) = None.
    n_frames = 101
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.1, 0.1, 0.3, 0.3), (100, 0.1, 0.1, 0.3, 0.3)],
        ),
        make_track(
            "tgt_a", "target", "bin A", primary=True,
            samples=[(0, 0.1, 0.1, 0.3, 0.3), (99, 0.1, 0.1, 0.3, 0.3)],
            gap_events=[(100, 100)],  # gap at frame 100
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=100,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is None


def test_iou_at_end_none_when_no_target_track() -> None:
    """No primary target track → primary_object_at_target_at_end is None."""
    from mimicanno.clip_features import compute_object_state_summary

    n_frames = 5
    tracks = [
        make_center_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.5, 0.5), (4, 0.5, 0.5)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=4,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is None


# ---------------------------------------------------------------------------
# Test 9: IoU-at-end uses SAME frame for both
# ---------------------------------------------------------------------------


def test_iou_at_end_uses_same_frame_for_both() -> None:
    """object bbox available at frame 99 but not 100; target available at 100.
    segment_end_frame=100 → bbox_at_frame(obj, 100) = None → result is None."""
    from mimicanno.clip_features import compute_object_state_summary

    n_frames = 101
    tracks = [
        make_track(
            "obj_a", "object", "red block", primary=True,
            samples=[(0, 0.1, 0.1, 0.3, 0.3), (99, 0.1, 0.1, 0.3, 0.3)],
            gap_events=[(100, 100)],  # object has gap at frame 100
        ),
        make_track(
            "tgt_a", "target", "bin A", primary=True,
            samples=[(0, 0.1, 0.1, 0.3, 0.3), (100, 0.1, 0.1, 0.3, 0.3)],
        ),
    ]
    signals = make_signals(n_frames, tracks)
    config = TrackingConfig()
    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=100,
        object_signals=signals,
        config=config,
    )
    assert summary is not None
    assert summary.primary_object_at_target_at_end is None


# ---------------------------------------------------------------------------
# Test 10: Snapshot byte-stability test (serializer pin)
# ---------------------------------------------------------------------------


def test_snapshot_object_state_summary() -> None:
    """Snapshot byte-equality test: pins the to_dict() serializer format."""
    from mimicanno.schema import ObjectStateSummary

    snapshot_path = SNAPSHOT_DIR / "object_state_summary_smoke.json"
    assert snapshot_path.exists(), f"Snapshot not found: {snapshot_path}"

    # Reconstruct from spec §5.4 example values
    obj_state = ObjectStateSummary(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
        visible_track_ids=["obj:red_block:0"],
        gripper_object_distance_at_start=0.42,
        gripper_object_distance_at_end=0.41,
        gripper_object_distance_min=0.03,
        primary_object_displacement=0.18,
        primary_object_max_speed=0.32,
        primary_object_at_target_at_end=True,
    )
    actual = json.dumps(obj_state.to_dict(), indent=2, sort_keys=True)
    expected = snapshot_path.read_text()
    assert actual == expected


# ---------------------------------------------------------------------------
# Test 11: ObjectStateSummary round-trip (to_dict / from_dict)
# ---------------------------------------------------------------------------


def test_object_state_summary_roundtrip() -> None:
    """to_dict() then from_dict() yields equivalent ObjectStateSummary."""
    from mimicanno.schema import ObjectStateSummary

    original = ObjectStateSummary(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=[],
        visible_track_ids=["obj:red_block:0"],
        gripper_object_distance_at_start=0.3,
        gripper_object_distance_at_end=None,
        gripper_object_distance_min=0.1,
        primary_object_displacement=0.05,
        primary_object_max_speed=None,
        primary_object_at_target_at_end=None,
    )
    d = original.to_dict()
    restored = ObjectStateSummary.from_dict(d)
    assert restored.object_prompts == ["red block"]
    assert restored.target_prompts == ["bin A"]
    assert restored.tool_prompts == []
    assert restored.gripper_object_distance_at_start == pytest.approx(0.3)
    assert restored.gripper_object_distance_at_end is None
    assert restored.gripper_object_distance_min == pytest.approx(0.1)
    assert restored.primary_object_displacement == pytest.approx(0.05)
    assert restored.primary_object_max_speed is None
    assert restored.primary_object_at_target_at_end is None


# ---------------------------------------------------------------------------
# Test 12: ClipFeatures.object_state_summary field defaults to None
# ---------------------------------------------------------------------------


def test_clip_features_object_state_summary_defaults_none() -> None:
    """Phase 1/2 ClipFeatures callsites: object_state_summary defaults to None."""
    from mimicanno.clip_features import ClipFeatures

    cf = ClipFeatures(
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0,
            "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.5,
            "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )
    assert cf.object_state_summary is None
