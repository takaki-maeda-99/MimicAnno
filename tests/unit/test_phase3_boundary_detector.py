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


# ---------------------------------------------------------------------------
# 4. Exact-threshold edge cases (spec §4.1.1 np.sign semantics)
# ---------------------------------------------------------------------------

class TestExactThresholdCrossing:
    """d(t-1) == threshold must emit when np.sign differs (sign 0 != sign ±)."""

    THRESHOLD = 0.05  # TrackingConfig default

    def _run_distance(self, d: np.ndarray) -> set[int]:
        """Return set of crossing frame indices from detect()."""
        n = len(d)
        gripper, eef_vel, eef_accel = _flat_signals(n)
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
            action_norm=np.zeros(n, dtype=np.float64),
            object_signals=signals,
            tracks=tracks,
        )
        return {c.frame for c in candidates}

    def test_d_prev_equals_threshold_d_cur_above_emits(self) -> None:
        """d[t-1] == threshold, d[t] > threshold → emit (sign 0 != sign +1).

        Signal: below threshold [0:49), exactly threshold at 49, above [50:n).
        t=49: sign(d[48]-th)=-1, sign(d[49]-th)=0 → cross.
        t=50: sign(d[49]-th)=0, sign(d[50]-th)=+1 → cross.
        Both emit; merge window may collapse them. Assert at least one nearby frame fires.
        """
        n = 100
        # w = round(0.10 * 30) = 3; window at t=49: [46:52]
        d = np.full(n, 0.01, dtype=np.float64)   # below threshold
        d[49] = self.THRESHOLD                     # exactly on threshold
        d[50:] = 0.10                              # above threshold
        frames = self._run_distance(d)
        assert frames & {49, 50}, (
            f"Expected crossing near d[49]==threshold to emit (frame 49 or 50), got {frames}"
        )

    def test_d_prev_equals_threshold_d_cur_below_emits(self) -> None:
        """d[t-1] == threshold, d[t] < threshold → emit (sign 0 != sign -1).

        Signal: above threshold [0:49), exactly threshold at 49, below [50:n).
        t=49: sign(d[48]-th)=+1, sign(d[49]-th)=0 → cross.
        t=50: sign(d[49]-th)=0, sign(d[50]-th)=-1 → cross.
        Both emit; merge window may collapse them. Assert at least one nearby frame fires.
        """
        n = 100
        d = np.full(n, 0.10, dtype=np.float64)   # above threshold
        d[49] = self.THRESHOLD                     # exactly on threshold
        d[50:] = 0.01                              # below threshold
        frames = self._run_distance(d)
        assert frames & {49, 50}, (
            f"Expected crossing near d[49]==threshold to emit (frame 49 or 50), got {frames}"
        )

    def test_d_prev_equals_threshold_d_cur_equals_threshold_no_emit(self) -> None:
        """d[t-1] == threshold, d[t] == threshold → no emit (sign 0 == sign 0)."""
        n = 100
        d = np.full(n, self.THRESHOLD, dtype=np.float64)  # all exactly on threshold
        frames = self._run_distance(d)
        assert len(frames) == 0, (
            f"All-threshold signal should produce no crossings, got frames {frames}"
        )

    def test_d_prev_above_threshold_d_cur_equals_threshold_emits(self) -> None:
        """d[t-1] > threshold, d[t] == threshold → emit (sign +1 != sign 0)."""
        n = 100
        d = np.full(n, 0.10, dtype=np.float64)  # above threshold
        d[50:] = self.THRESHOLD  # exactly on threshold from frame 50
        # t=50: sign(d[49]-th)=+1, sign(d[50]-th)=0 → emit at frame 50
        frames = self._run_distance(d)
        assert 50 in frames, (
            f"Expected crossing at frame 50 (d[49]>th, d[50]==th), got frames {frames}"
        )


# ---------------------------------------------------------------------------
# 5. Per-frame NaN skip tests (spec §4.1.1 and §4.1.2)
# ---------------------------------------------------------------------------

class TestPerFrameNaNSkip:
    def test_distance_crossing_isolated_nan_at_t_minus_1_suppresses_only_that_crossing(
        self,
    ) -> None:
        """Single NaN at t-1 of one crossing suppresses only that crossing; others fire."""
        n = 200
        # Two crossings: above→below at 60, below→above at 150
        # NaN at frame 59 (t-1 of crossing 60) → crossing 60 suppressed; crossing 150 fires
        d = np.full(n, 0.10, dtype=np.float64)  # above threshold
        d[60:150] = 0.01  # below threshold between 60 and 150
        d[59] = np.nan  # suppress crossing at frame 60

        gripper, eef_vel, eef_accel = _flat_signals(n)
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
            action_norm=np.zeros(n, dtype=np.float64),
            object_signals=signals,
            tracks=tracks,
        )
        frames = {c.frame for c in candidates}
        assert 60 not in frames, "Crossing at frame 60 should be suppressed (NaN at 59)"
        assert 150 in frames, f"Crossing at frame 150 should still fire, got frames {frames}"

    def test_motion_window_with_internal_nan_suppresses_only_that_event(self) -> None:
        """NaN inside one transition's window suppresses that event; adjacent clean one fires."""
        n = 200
        # window = round(0.10 * 30) = 3
        # Start event at frame 60 (v[57:60] all < 0.02, v[60:63] all >= 0.02)
        # Stop event at frame 150 (v[147:150] all >= 0.02, v[150:153] all < 0.02)
        # Inject NaN at frame 58 (inside before-window [57:60) for t=60) → suppresses start at 60
        v = np.full(n, 0.0, dtype=np.float64)  # stationary
        v[60:150] = 0.05  # moving between 60 and 150
        v[58] = np.nan  # inside before-window of start event at frame 60

        gripper, eef_vel, eef_accel = _flat_signals(n)
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
            action_norm=np.zeros(n, dtype=np.float64),
            object_signals=signals,
            tracks=tracks,
        )
        frames = {c.frame for c in candidates}
        assert 60 not in frames, "Start event at frame 60 should be suppressed (NaN at 58)"
        assert 150 in frames, f"Stop event at frame 150 should still fire, got frames {frames}"


# ---------------------------------------------------------------------------
# 6. user-supplied disabled_sources UNION with auto-derived
# ---------------------------------------------------------------------------

class TestUserDisabledUnionAutoDisabled:
    def test_user_supplied_disabled_unioned_with_auto_derived(self) -> None:
        """User passes disabled_sources=['gripper_transition']; no object-role tracks →
        auto-derives both Phase 3 sources disabled. Final disabled must contain all three."""
        n = 100
        d = np.full(n, 0.10, dtype=np.float64)
        d[50:] = 0.01  # would cross threshold if not disabled

        # Sharp gripper transition so gripper_transition would fire if enabled
        gripper = np.full(n, 0.5, dtype=np.float64)
        gripper[50:] = 0.0
        eef_vel = np.full(n, 0.5, dtype=np.float64)
        eef_accel = np.full(n, 0.0, dtype=np.float64)

        # No role="object" tracks → auto-disables both Phase 3 sources
        signals = ObjectSignals(
            gripper_object_distance={"obj1": d},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id=None,
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track("tool1", "tool")]  # no role="object" track

        det = _make_detector(disabled_sources=["gripper_transition"])
        candidates, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=np.zeros(n, dtype=np.float64),
            object_signals=signals,
            tracks=tracks,
        )

        assert "gripper_transition" in final_disabled, "user-supplied source must be in final_disabled"
        assert "gripper_object_distance_threshold_crossing" in final_disabled, "auto-derived (no object role)"
        assert "object_motion_start_stop" in final_disabled, "auto-derived (no object role)"

        source_names = {src for c in candidates for src in c.sources}
        assert "gripper_transition" not in source_names, (
            "gripper_transition was user-disabled — its events must not appear in candidates"
        )
