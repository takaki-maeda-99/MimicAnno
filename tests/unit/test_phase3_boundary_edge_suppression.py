# tests/unit/test_phase3_boundary_edge_suppression.py
"""Edge-suppression rules for new Phase 3 boundary detectors (spec §4.1.1 / §4.1.2).

§4.1.1: crossing inside [0, w) or [n_frames - w, n_frames) → no event.
§4.1.2: sustained transition where t - window < 0 or t + window - 1 >= n_frames → no event.
"""

from __future__ import annotations

import numpy as np

from mimicanno.boundaries import (
    detect_gripper_object_distance_threshold_crossing,
    detect_object_motion_start_stop,
)

FPS = 30.0
# w = max(1, round(0.10 * 30)) = 3
W = max(1, round(0.10 * FPS))
# window = round(0.10 * 30) = 3
WINDOW = round(0.10 * FPS)
THRESHOLD = 0.05
MOTION_THRESHOLD = 0.02


# ---------------------------------------------------------------------------
# §4.1.1 distance crossing edge suppression
# ---------------------------------------------------------------------------

class TestDistanceCrossingEdgeSuppression:
    def test_crossing_inside_leading_window_no_event(self) -> None:
        """Crossing at frame w-1 (inside [0, w)) → no event emitted."""
        n = 60
        d = np.full(n, 0.10, dtype=np.float64)
        # Crossing at frame W-1 (last frame inside leading window [0, W))
        crossing = W - 1
        d[crossing:] = 0.01
        per_track = {"obj1": d}
        events = detect_gripper_object_distance_threshold_crossing(
            per_track, fps=FPS, threshold=THRESHOLD
        )
        # No event at or before frame W-1+1 (the crossing frame)
        assert all(e.frame >= W for e in events), (
            f"Expected no events inside leading window [0, {W}), "
            f"got frames: {[e.frame for e in events]}"
        )

    def test_crossing_at_leading_boundary_no_event(self) -> None:
        """Crossing at frame 1 (inside [0, w)) → no event (windowed delta undefined)."""
        n = 60
        d = np.full(n, 0.10, dtype=np.float64)
        d[1:] = 0.01  # crossing at frame 1
        per_track = {"obj1": d}
        events = detect_gripper_object_distance_threshold_crossing(
            per_track, fps=FPS, threshold=THRESHOLD
        )
        # Frame 1 has t - w = 1 - 3 = -2 < 0 → no event
        assert not any(e.frame == 1 for e in events), (
            f"Expected no event at frame 1 (inside leading window), "
            f"got: {[e.frame for e in events]}"
        )

    def test_crossing_inside_trailing_window_no_event(self) -> None:
        """Crossing at frame n_frames - w (inside trailing window) → no event."""
        n = 60
        d = np.full(n, 0.10, dtype=np.float64)
        # Crossing at frame n - W (t + w = n - W + W = n >= n_frames → no event)
        crossing = n - W
        d[crossing:] = 0.01
        per_track = {"obj1": d}
        events = detect_gripper_object_distance_threshold_crossing(
            per_track, fps=FPS, threshold=THRESHOLD
        )
        assert not any(e.frame >= crossing for e in events), (
            f"Expected no events at frame >= {crossing} (inside trailing window), "
            f"got frames: {[e.frame for e in events]}"
        )

    def test_crossing_at_trailing_boundary_no_event(self) -> None:
        """Crossing at frame n_frames - 2 → no event (t+w >= n_frames)."""
        n = 60
        d = np.full(n, 0.10, dtype=np.float64)
        crossing = n - 2  # t + w = (n-2) + 3 = n+1 >= n_frames
        d[crossing:] = 0.01
        per_track = {"obj1": d}
        events = detect_gripper_object_distance_threshold_crossing(
            per_track, fps=FPS, threshold=THRESHOLD
        )
        assert not any(e.frame == crossing for e in events), (
            f"Expected no event at frame {crossing} (trailing window), "
            f"got: {[e.frame for e in events]}"
        )

    def test_crossing_in_valid_interior_emits_event(self) -> None:
        """Crossing at a frame safely inside both windows → event emitted."""
        n = 60
        d = np.full(n, 0.10, dtype=np.float64)
        crossing = 30  # far from edges
        d[crossing:] = 0.01
        per_track = {"obj1": d}
        events = detect_gripper_object_distance_threshold_crossing(
            per_track, fps=FPS, threshold=THRESHOLD
        )
        assert any(e.frame == crossing for e in events), (
            f"Expected event at frame {crossing}, got: {[e.frame for e in events]}"
        )


# ---------------------------------------------------------------------------
# §4.1.2 object motion start/stop edge suppression
# ---------------------------------------------------------------------------

class TestObjectMotionStartStopEdgeSuppression:
    def test_start_transition_at_leading_edge_no_event(self) -> None:
        """Start transition where t - window < 0 → no event (§4.1.2)."""
        n = 60
        v = np.full(n, 0.0, dtype=np.float64)
        # Put transition at frame WINDOW - 1 (t - window = -1 < 0)
        t = WINDOW - 1
        v[t:] = 0.05  # above threshold from t onwards
        per_track = {"obj1": v}
        events = detect_object_motion_start_stop(
            per_track,
            fps=FPS,
            threshold=MOTION_THRESHOLD,
            min_sec=0.10,
        )
        assert not any(e.frame == t for e in events), (
            f"Expected no start event at frame {t} (leading edge), "
            f"got: {[e.frame for e in events]}"
        )

    def test_start_transition_at_frame_zero_no_event(self) -> None:
        """Start transition at frame 0 → no event (t - window < 0)."""
        n = 60
        # All frames above threshold: would-be start at frame 0
        v = np.full(n, 0.05, dtype=np.float64)
        per_track = {"obj1": v}
        events = detect_object_motion_start_stop(
            per_track,
            fps=FPS,
            threshold=MOTION_THRESHOLD,
            min_sec=0.10,
        )
        # No event at frame 0 because t - window = 0 - 3 = -3 < 0
        assert not any(e.frame == 0 for e in events)

    def test_stop_transition_at_trailing_edge_no_event(self) -> None:
        """Stop transition where t + window - 1 >= n_frames → no event (§4.1.2)."""
        n = 60
        v = np.full(n, 0.05, dtype=np.float64)
        # Put stop transition at frame n - WINDOW (t + window - 1 = n - 1 = n_frames - 1, ok)
        # Put it at frame n - WINDOW + 1 (t + window - 1 = n >= n_frames → no event)
        t = n - WINDOW + 1
        v[t:] = 0.0  # stationary from t onwards
        per_track = {"obj1": v}
        events = detect_object_motion_start_stop(
            per_track,
            fps=FPS,
            threshold=MOTION_THRESHOLD,
            min_sec=0.10,
        )
        assert not any(e.frame == t for e in events), (
            f"Expected no stop event at frame {t} (trailing edge), "
            f"got: {[e.frame for e in events]}"
        )

    def test_stop_transition_at_last_frame_no_event(self) -> None:
        """Stop transition at last frame → no event."""
        n = 60
        v = np.full(n, 0.05, dtype=np.float64)
        v[-1] = 0.0  # only last frame below threshold — can't form sustained window
        per_track = {"obj1": v}
        events = detect_object_motion_start_stop(
            per_track,
            fps=FPS,
            threshold=MOTION_THRESHOLD,
            min_sec=0.10,
        )
        assert not any(e.frame == n - 1 for e in events)

    def test_interior_transition_emits_event(self) -> None:
        """Transition well inside the frame range → event emitted."""
        n = 120
        v = np.full(n, 0.0, dtype=np.float64)
        v[60:] = 0.05  # start event at frame 60
        per_track = {"obj1": v}
        events = detect_object_motion_start_stop(
            per_track,
            fps=FPS,
            threshold=MOTION_THRESHOLD,
            min_sec=0.10,
        )
        assert any(e.frame == 60 for e in events), (
            f"Expected start event at frame 60, got: {[e.frame for e in events]}"
        )
