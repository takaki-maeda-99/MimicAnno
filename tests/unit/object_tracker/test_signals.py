"""Tests for compute_object_signals (spec §2.5)."""

from __future__ import annotations

import math

import numpy as np

from mimicanno.object_tracker.propagator import BBox, GapEvent, Track, TrackSample
from mimicanno.object_tracker.signals import compute_object_signals

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_track(
    track_id: str,
    role: str,
    primary: bool,
    samples: list[tuple[int, float, float]] | None = None,
    gap_events: list[tuple[int, int]] | None = None,
) -> Track:
    """Convenience: build a Track from (frame, cx, cy) tuples."""
    ts_list: list[TrackSample] = []
    if samples:
        for frame, cx, cy in samples:
            # Build a BBox so that center == (cx, cy); w=h=0.1
            w, h = 0.1, 0.1
            x = cx - w / 2
            y = cy - h / 2
            # Clamp to [0, 1 - w/h] to satisfy BBox invariant
            x = max(0.0, min(x, 1.0 - w))
            y = max(0.0, min(y, 1.0 - h))
            bbox = BBox(x=x, y=y, w=w, h=h)
            ts_list.append(TrackSample(frame=frame, time_sec=frame / 30.0, bbox=bbox, score=1.0))
    ge_list: list[GapEvent] = []
    if gap_events:
        for from_frame, to_frame in gap_events:
            ge_list.append(GapEvent(from_frame=from_frame, to_frame=to_frame, reason="sam3_lost"))

    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=track_id,
        slug=track_id,
        index=0,
        primary=primary,
        samples=ts_list,
        gap_events=ge_list,
    )


# ---------------------------------------------------------------------------
# Test 1: object_center populated for all roles
# ---------------------------------------------------------------------------


def test_object_center_populated_for_all_roles() -> None:
    tracks = [
        make_track("obj_a", "object", primary=True, samples=[(0, 0.5, 0.5), (10, 0.5, 0.5)]),
        make_track("tgt_a", "target", primary=True, samples=[(0, 0.3, 0.3), (10, 0.3, 0.3)]),
        make_track("tool_a", "tool", primary=True, samples=[(0, 0.7, 0.7), (10, 0.7, 0.7)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=11, image_aspect_ratio=16 / 9)

    assert "obj_a" in signals.object_center
    assert "tgt_a" in signals.object_center
    assert "tool_a" in signals.object_center


# ---------------------------------------------------------------------------
# Test 2: Linear interpolation between samples
# ---------------------------------------------------------------------------


def test_linear_interpolation_between_samples() -> None:
    # Samples at frames [0, 10, 20] with cx = [0.0, 0.1, 0.2]
    # Because bbox center = x + w/2, and we want cx exactly, use the helper.
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.1, 0.5), (10, 0.2, 0.5), (20, 0.3, 0.5)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=21, image_aspect_ratio=16 / 9)

    centers = signals.object_center["obj_a"]
    # frame 5: interpolate between (0, cx=0.1) and (10, cx=0.2) → 0.15
    assert abs(centers[5, 0] - 0.15) < 1e-9
    # frame 15: interpolate between (10, cx=0.2) and (20, cx=0.3) → 0.25
    assert abs(centers[15, 0] - 0.25) < 1e-9


# ---------------------------------------------------------------------------
# Test 3: NaN inside gaps — object_center
# ---------------------------------------------------------------------------


def test_nan_inside_gaps_object_center() -> None:
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.5, 0.5), (25, 0.5, 0.5)],
            gap_events=[(10, 20)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=30, image_aspect_ratio=16 / 9)
    centers = signals.object_center["obj_a"]
    for t in range(10, 21):
        assert np.isnan(centers[t, 0]), f"frame {t} should be NaN"
    # Outside the gap but inside domain: not NaN
    assert not np.isnan(centers[0, 0])
    assert not np.isnan(centers[25, 0])


# ---------------------------------------------------------------------------
# Test 4: NaN inside gaps — object_speed
# ---------------------------------------------------------------------------


def test_nan_inside_gaps_object_speed() -> None:
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.5, 0.5), (25, 0.5, 0.5)],
            gap_events=[(10, 20)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=30, image_aspect_ratio=16 / 9)
    speed = signals.object_speed["obj_a"]
    for t in range(10, 21):
        assert np.isnan(speed[t]), f"frame {t} speed should be NaN"


# ---------------------------------------------------------------------------
# Test 5: Distance image-width-normalized — x-axis only
# ---------------------------------------------------------------------------


def test_distance_image_width_normalized_x_axis() -> None:
    """gripper at (0.5, 0.5), object at (0.6, 0.5) → distance = 0.1."""
    aspect = 16 / 9
    tracks = [
        make_track("obj_a", "object", primary=True, samples=[(0, 0.6, 0.5)]),
        make_track("tool_a", "tool", primary=True, samples=[(0, 0.5, 0.5)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=1, image_aspect_ratio=aspect)
    dist = signals.gripper_object_distance["obj_a"]
    assert abs(dist[0] - 0.1) < 1e-9


# ---------------------------------------------------------------------------
# Test 6: Distance with aspect-ratio correction — y-axis only
# ---------------------------------------------------------------------------


def test_distance_aspect_ratio_correction_y_axis() -> None:
    """gripper at (0.5, 0.5), object at (0.5, 0.6), aspect=16/9 → sqrt((0.1/aspect)²)."""
    aspect = 16 / 9
    expected = math.sqrt((0.1 / aspect) ** 2)
    tracks = [
        make_track("obj_a", "object", primary=True, samples=[(0, 0.5, 0.6)]),
        make_track("tool_a", "tool", primary=True, samples=[(0, 0.5, 0.5)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=1, image_aspect_ratio=aspect)
    dist = signals.gripper_object_distance["obj_a"]
    assert abs(dist[0] - expected) < 1e-9


# ---------------------------------------------------------------------------
# Test 7: Speed central difference
# ---------------------------------------------------------------------------


def test_speed_central_difference() -> None:
    """Samples at frames [0,1,2] cx=[0,0.1,0.2], fps=30.
    speed at frame 1: |(0.2-0.0)|/2 * 30 = 3.0.
    """
    aspect = 16 / 9
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.1, 0.5), (1, 0.2, 0.5), (2, 0.3, 0.5)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=3, image_aspect_ratio=aspect)
    speed = signals.object_speed["obj_a"]
    # dx = 0.3 - 0.1 = 0.2, vx = 0.2/2 * 30 = 3.0, dy=0, speed=3.0
    assert abs(speed[1] - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: Speed at boundary frame 0 uses forward difference
# ---------------------------------------------------------------------------


def test_speed_boundary_forward_difference() -> None:
    """At frame 0, speed = |(center[1] - center[0])| * fps."""
    aspect = 16 / 9
    fps = 30.0
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.1, 0.5), (1, 0.2, 0.5), (2, 0.3, 0.5)],
        )
    ]
    signals = compute_object_signals(tracks, fps=fps, n_frames=3, image_aspect_ratio=aspect)
    speed = signals.object_speed["obj_a"]
    # dx = 0.2 - 0.1 = 0.1, vx = 0.1 * 30 = 3.0
    assert abs(speed[0] - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 9: Speed at boundary frame n_frames-1 uses backward difference
# ---------------------------------------------------------------------------


def test_speed_boundary_backward_difference() -> None:
    """At frame n_frames-1, speed = |(center[-1] - center[-2])| * fps."""
    aspect = 16 / 9
    fps = 30.0
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.1, 0.5), (1, 0.2, 0.5), (2, 0.3, 0.5)],
        )
    ]
    signals = compute_object_signals(tracks, fps=fps, n_frames=3, image_aspect_ratio=aspect)
    speed = signals.object_speed["obj_a"]
    # dx = 0.3 - 0.2 = 0.1, vx = 0.1 * 30 = 3.0
    assert abs(speed[2] - 3.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 10: Speed adjacent to gap uses one-sided difference
# ---------------------------------------------------------------------------


def test_speed_adjacent_to_gap_one_sided() -> None:
    """Frame 9 is adjacent to gap [10,20]. Its 'next' at frame 10 is NaN.
    So frame 9 uses backward diff: (center[9] - center[8]) * fps.
    """
    fps = 30.0
    aspect = 16 / 9
    # samples at 0 and 9 only (gap covers 10-20, then 25 after)
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(0, 0.1, 0.5), (9, 0.19, 0.5), (25, 0.3, 0.5)],
            gap_events=[(10, 20)],
        )
    ]
    signals = compute_object_signals(tracks, fps=fps, n_frames=30, image_aspect_ratio=aspect)
    speed = signals.object_speed["obj_a"]
    # Frame 9 speed: backward diff from frame 8 to 9
    centers = signals.object_center["obj_a"]
    expected_speed = abs(centers[9, 0] - centers[8, 0]) * fps
    assert abs(speed[9] - expected_speed) < 1e-9


# ---------------------------------------------------------------------------
# Test 11: Primary object track_id resolution
# ---------------------------------------------------------------------------


def test_primary_object_track_id_resolution() -> None:
    tracks = [
        make_track("obj_a", "object", primary=True, samples=[(0, 0.5, 0.5)]),
        make_track("obj_b", "object", primary=False, samples=[(0, 0.4, 0.4)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=1, image_aspect_ratio=16 / 9)
    assert signals.primary_object_track_id == "obj_a"
    assert signals.primary_target_track_id is None


# ---------------------------------------------------------------------------
# Test 12: primary_object_track_id is None when no primary object
# ---------------------------------------------------------------------------


def test_primary_object_track_id_none_when_no_primary() -> None:
    tracks = [
        make_track("obj_a", "object", primary=False, samples=[(0, 0.5, 0.5)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=1, image_aspect_ratio=16 / 9)
    assert signals.primary_object_track_id is None


# ---------------------------------------------------------------------------
# Test 13: Empty gripper signals when no tool track
# ---------------------------------------------------------------------------


def test_empty_gripper_signals_when_no_tool_track() -> None:
    tracks = [
        make_track("obj_a", "object", primary=True, samples=[(0, 0.5, 0.5)]),
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=1, image_aspect_ratio=16 / 9)
    assert signals.gripper_object_distance == {}
    assert signals.gripper_tool_track_id is None


# ---------------------------------------------------------------------------
# Test 14: Empty samples track is all NaN
# ---------------------------------------------------------------------------


def test_empty_samples_track_all_nan() -> None:
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[],
            gap_events=[(0, 9)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=10, image_aspect_ratio=16 / 9)
    centers = signals.object_center["obj_a"]
    assert np.all(np.isnan(centers))
    speed = signals.object_speed["obj_a"]
    assert np.all(np.isnan(speed))


# ---------------------------------------------------------------------------
# Test 15: Outside interp domain is NaN
# ---------------------------------------------------------------------------


def test_outside_interp_domain_is_nan() -> None:
    """Samples at frames [10, 20]. Frames 0-9 and 21-29 should be NaN."""
    tracks = [
        make_track(
            "obj_a",
            "object",
            primary=True,
            samples=[(10, 0.5, 0.5), (20, 0.6, 0.5)],
        )
    ]
    signals = compute_object_signals(tracks, fps=30.0, n_frames=30, image_aspect_ratio=16 / 9)
    centers = signals.object_center["obj_a"]
    for t in range(0, 10):
        assert np.isnan(centers[t, 0]), f"frame {t} should be NaN (before interp domain)"
    for t in range(21, 30):
        assert np.isnan(centers[t, 0]), f"frame {t} should be NaN (after interp domain)"
    # Within domain: not NaN
    assert not np.isnan(centers[10, 0])
    assert not np.isnan(centers[15, 0])
    assert not np.isnan(centers[20, 0])
