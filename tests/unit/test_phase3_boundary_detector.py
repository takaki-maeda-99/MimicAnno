# tests/unit/test_phase3_boundary_detector.py
"""Phase3BoundaryDetector — new sources + disabled_sources rules (spec §4.4)."""

from __future__ import annotations

import numpy as np

from mimicanno.boundaries import Phase3BoundaryDetector
from mimicanno.config import BoundaryWeights, TrackingConfig
from mimicanno.object_tracker.propagator import BBox, Track, TrackSample
from mimicanno.object_tracker.signals import ObjectSignals

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FPS = 30.0
TRACKING_CFG = TrackingConfig()  # defaults: threshold=0.05, motion_threshold=0.02, min_sec=0.10
WEIGHTS = BoundaryWeights.phase3_defaults()
SCORE_THRESHOLD = 0.30
MERGE_WINDOW_SEC = 0.10

# Use a lower threshold when we want single-source events (score=0.25 or score=0.10)
# to promote through integrated_candidates in "fires" tests.
LOW_SCORE_THRESHOLD = 0.05


def _make_detector(
    disabled_sources: list[str] | None = None,
    score_threshold: float = SCORE_THRESHOLD,
) -> Phase3BoundaryDetector:
    return Phase3BoundaryDetector(
        fps=FPS,
        weights=WEIGHTS,
        score_threshold=score_threshold,
        merge_window_sec=MERGE_WINDOW_SEC,
        disabled_sources=disabled_sources or [],
        tracking_config=TRACKING_CFG,
    )


def _make_track(track_id: str, role: str, primary: bool = True) -> Track:
    """Minimal Track with a single sample."""
    bbox = BBox(x=0.1, y=0.1, w=0.1, h=0.1)
    sample = TrackSample(frame=0, time_sec=0.0, bbox=bbox, score=1.0)
    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=track_id,
        slug=track_id,
        index=0,
        primary=primary,
        samples=[sample],
        gap_events=[],
    )


def _flat_signals(n_frames: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """flat gripper, eef_vel, eef_accel signals that produce no events."""
    gripper = np.full(n_frames, 0.5, dtype=np.float64)
    eef_vel = np.full(n_frames, 0.5, dtype=np.float64)
    eef_accel = np.full(n_frames, 0.0, dtype=np.float64)
    return gripper, eef_vel, eef_accel


# ---------------------------------------------------------------------------
# 1. gripper_object_distance_threshold_crossing fires at crossing
# ---------------------------------------------------------------------------

class TestDistanceCrossingFires:
    def test_fires_at_threshold_crossing(self) -> None:
        """d crosses 0.05 from above to below — event emitted at the crossing frame.

        Uses LOW_SCORE_THRESHOLD so the distance source (weight=0.25) alone promotes.
        """
        n = 100
        # w = round(0.10 * 30) = 3
        # crossing at frame 50; need t-w >= 0 and t+w < n
        d = np.full(n, 0.10, dtype=np.float64)  # above threshold
        d[50:] = 0.01  # below threshold at frame 50 onwards
        gripper, eef_vel, eef_accel = _flat_signals(n)
        action_norm = np.zeros(n, dtype=np.float64)

        signals = ObjectSignals(
            gripper_object_distance={"obj1": d},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("obj1", "object"), _make_track("tool1", "tool")]

        det = _make_detector(score_threshold=LOW_SCORE_THRESHOLD)
        candidates, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=action_norm,
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_object_distance_threshold_crossing" not in final_disabled
        source_names = {src for c in candidates for src in c.sources}
        assert "gripper_object_distance_threshold_crossing" in source_names

    def test_fires_at_crossing_below_to_above(self) -> None:
        """d crosses 0.05 from below to above — event emitted.

        Uses LOW_SCORE_THRESHOLD so the distance source (weight=0.25) alone promotes.
        """
        n = 100
        d = np.full(n, 0.01, dtype=np.float64)  # below threshold
        d[50:] = 0.10  # above threshold at frame 50 onwards
        gripper, eef_vel, eef_accel = _flat_signals(n)
        action_norm = np.zeros(n, dtype=np.float64)

        signals = ObjectSignals(
            gripper_object_distance={"obj1": d},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("obj1", "object"), _make_track("tool1", "tool")]

        det = _make_detector(score_threshold=LOW_SCORE_THRESHOLD)
        candidates, _ = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=action_norm,
            object_signals=signals,
            tracks=tracks,
        )

        source_names = {src for c in candidates for src in c.sources}
        assert "gripper_object_distance_threshold_crossing" in source_names


# ---------------------------------------------------------------------------
# 2. object_motion_start_stop fires after sustained transition
# ---------------------------------------------------------------------------

class TestObjectMotionStartStop:
    def test_start_event_fires_after_sustained_motion(self) -> None:
        """Object transitions from stationary to moving (sustained window).

        Uses LOW_SCORE_THRESHOLD so the motion source (weight=0.10) alone promotes.
        """
        n = 120
        # window = round(0.10 * 30) = 3
        # Start event at frame t requires v[t-3:t] all < 0.02 and v[t:t+3] all >= 0.02
        # Put transition at frame 60
        v = np.full(n, 0.0, dtype=np.float64)  # stationary initially
        v[60:] = 0.05  # moving after frame 60

        gripper, eef_vel, eef_accel = _flat_signals(n)
        action_norm = np.zeros(n, dtype=np.float64)

        signals = ObjectSignals(
            gripper_object_distance={},
            object_speed={"obj1": v},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id=None,  # no gripper needed for this source
        )
        tracks = [_make_track("obj1", "object")]

        det = _make_detector(score_threshold=LOW_SCORE_THRESHOLD)
        candidates, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=action_norm,
            object_signals=signals,
            tracks=tracks,
        )

        assert "object_motion_start_stop" not in final_disabled
        source_names = {src for c in candidates for src in c.sources}
        assert "object_motion_start_stop" in source_names

    def test_stop_event_fires_after_sustained_stillness(self) -> None:
        """Object transitions from moving to stationary.

        Uses LOW_SCORE_THRESHOLD so the motion source (weight=0.10) alone promotes.
        """
        n = 120
        v = np.full(n, 0.05, dtype=np.float64)  # moving initially
        v[60:] = 0.0  # stationary after frame 60

        gripper, eef_vel, eef_accel = _flat_signals(n)
        action_norm = np.zeros(n, dtype=np.float64)

        signals = ObjectSignals(
            gripper_object_distance={},
            object_speed={"obj1": v},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id=None,
        )
        tracks = [_make_track("obj1", "object")]

        det = _make_detector(score_threshold=LOW_SCORE_THRESHOLD)
        candidates, _ = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=action_norm,
            object_signals=signals,
            tracks=tracks,
        )

        source_names = {src for c in candidates for src in c.sources}
        assert "object_motion_start_stop" in source_names


# ---------------------------------------------------------------------------
# 3. disabled_sources rules (spec §4.4)
# ---------------------------------------------------------------------------

class TestDisabledSourcesRules:
    def test_disabled_when_no_gripper_tool_track_id(self) -> None:
        """gripper_tool_track_id is None → distance source disabled."""
        n = 60
        gripper, eef_vel, eef_accel = _flat_signals(n)
        signals = ObjectSignals(
            gripper_object_distance={"obj1": np.full(n, 0.03, dtype=np.float64)},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id=None,  # ← None
        )
        tracks = [_make_track("obj1", "object")]

        det = _make_detector()
        _, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n),
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_object_distance_threshold_crossing" in final_disabled

    def test_disabled_when_no_object_role_tracks(self) -> None:
        """No tracks with role='object' → both new sources disabled."""
        n = 60
        gripper, eef_vel, eef_accel = _flat_signals(n)
        signals = ObjectSignals(
            gripper_object_distance={},
            object_speed={},
            object_center={},
            primary_object_track_id=None,
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("tool1", "tool")]  # no object role

        det = _make_detector()
        _, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n),
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_object_distance_threshold_crossing" in final_disabled
        assert "object_motion_start_stop" in final_disabled

    def test_disabled_when_all_distance_nan(self) -> None:
        """All gripper_object_distance arrays are entirely NaN → distance source disabled."""
        n = 60
        gripper, eef_vel, eef_accel = _flat_signals(n)
        signals = ObjectSignals(
            gripper_object_distance={"obj1": np.full(n, np.nan, dtype=np.float64)},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("obj1", "object"), _make_track("tool1", "tool")]

        det = _make_detector()
        _, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n),
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_object_distance_threshold_crossing" in final_disabled

    def test_disabled_when_all_speed_nan(self) -> None:
        """All object_speed arrays are entirely NaN → motion source disabled."""
        n = 60
        gripper, eef_vel, eef_accel = _flat_signals(n)
        signals = ObjectSignals(
            gripper_object_distance={"obj1": np.full(n, 0.03, dtype=np.float64)},
            object_speed={"obj1": np.full(n, np.nan, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("obj1", "object"), _make_track("tool1", "tool")]

        det = _make_detector()
        _, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n),
            object_signals=signals,
            tracks=tracks,
        )

        assert "object_motion_start_stop" in final_disabled

    def test_empty_tracks_disables_both_new_sources(self) -> None:
        """Empty tracks list (vacuously no role='object') → both new sources disabled."""
        n = 60
        gripper, eef_vel, eef_accel = _flat_signals(n)
        signals = ObjectSignals(
            gripper_object_distance={},
            object_speed={},
            object_center={},
            primary_object_track_id=None,
            primary_target_track_id=None,
            gripper_tool_track_id=None,
        )
        tracks: list[Track] = []

        det = _make_detector()
        _, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n),
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_object_distance_threshold_crossing" in final_disabled
        assert "object_motion_start_stop" in final_disabled
