# tests/unit/test_phase3_weights_intent.py
"""Encodes the §4.3 promotion truth table.

Phase 3 weights (BoundaryWeights.phase3_defaults()):
  gripper_transition                       = 0.45
  gripper_object_distance_threshold_crossing = 0.25
  eef_velocity_valley                      = 0.15
  object_motion_start_stop                 = 0.10
  eef_acceleration_peak                    = 0.03
  action_norm_change                       = 0.02

score_threshold = 0.30

Truth table:
  gripper_transition alone            -> 0.45 -> promotes  (>= 0.30)
  distance_threshold_crossing alone   -> 0.25 -> does NOT promote (< 0.30)
  gripper + distance                  -> 0.70 -> strongly promotes
  object_motion_start_stop + velocity -> 0.10 + 0.15 = 0.25 -> does NOT promote
  distance + velocity                 -> 0.25 + 0.15 = 0.40 -> promotes
  distance + object_motion_start_stop -> 0.25 + 0.10 = 0.35 -> promotes (§4.3 canonical)
"""

from __future__ import annotations

import numpy as np
import pytest

from mimicanno.boundaries import Phase3BoundaryDetector, RawEvent, integrated_candidates
from mimicanno.config import BoundaryWeights, TrackingConfig
from mimicanno.object_tracker.propagator import BBox, Track, TrackSample
from mimicanno.object_tracker.signals import ObjectSignals

WEIGHTS = BoundaryWeights.phase3_defaults()
SCORE_THRESHOLD = 0.30
MERGE_WINDOW_SEC = 0.10
FPS = 30.0


def _weights_dict() -> dict[str, float]:
    """Full Phase 3 weights keyed by detector source names."""
    return {
        "gripper_transition": WEIGHTS.gripper,
        "gripper_object_distance_threshold_crossing": (
            WEIGHTS.gripper_object_distance_threshold_crossing
        ),
        "eef_velocity_valley": WEIGHTS.velocity,
        "object_motion_start_stop": WEIGHTS.object_motion_start_stop,
        "eef_acceleration_peak": WEIGHTS.acceleration,
        "action_norm_change": WEIGHTS.action,
    }


def _single_source_event(source: str, source_score: float = 1.0) -> list[RawEvent]:
    """One event from a single source at time=1.0 sec."""
    return [RawEvent(frame=30, time=1.0, source=source, source_score=source_score)]


def _two_source_events(src_a: str, src_b: str, source_score: float = 1.0) -> list[RawEvent]:
    """Two events from different sources, co-located at time=1.0 sec."""
    return [
        RawEvent(frame=30, time=1.0, source=src_a, source_score=source_score),
        RawEvent(frame=30, time=1.0, source=src_b, source_score=source_score),
    ]


class TestPhase3WeightsTruthTable:
    def test_gripper_transition_alone_promotes(self) -> None:
        """gripper_transition score 1.0 * weight 0.45 = 0.45 -> promotes (>= 0.30)."""
        events = _single_source_event("gripper_transition")
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 1, "Expected exactly 1 candidate from gripper_transition"
        assert candidates[0].score == pytest.approx(0.45, rel=1e-6)

    def test_distance_crossing_alone_does_not_promote(self) -> None:
        """distance_crossing score 1.0 * weight 0.25 = 0.25 -> below threshold 0.30."""
        events = _single_source_event("gripper_object_distance_threshold_crossing")
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 0, (
            f"Expected 0 candidates (score 0.25 < threshold 0.30), got {len(candidates)}"
        )

    def test_gripper_plus_distance_strongly_promotes(self) -> None:
        """gripper_transition + distance_crossing = 0.45 + 0.25 = 0.70 → strongly promotes."""
        events = _two_source_events(
            "gripper_transition", "gripper_object_distance_threshold_crossing"
        )
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 1
        assert candidates[0].score == pytest.approx(0.70, rel=1e-6)

    def test_object_motion_plus_velocity_does_not_promote(self) -> None:
        """object_motion_start_stop + eef_velocity_valley = 0.10 + 0.15 = 0.25 < 0.30."""
        events = _two_source_events("object_motion_start_stop", "eef_velocity_valley")
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 0, (
            f"Expected 0 candidates (score 0.25 < threshold 0.30), got {len(candidates)}"
        )

    def test_distance_plus_velocity_promotes(self) -> None:
        """distance_crossing + eef_velocity_valley = 0.25 + 0.15 = 0.40 → promotes."""
        events = _two_source_events(
            "gripper_object_distance_threshold_crossing", "eef_velocity_valley"
        )
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 1
        assert candidates[0].score == pytest.approx(0.40, rel=1e-6)

    def test_phase3_weights_sum_to_one(self) -> None:
        """Phase 3 weights sum to 1.0 (normalization sanity check)."""
        w = _weights_dict()
        total = sum(w.values())
        assert total == pytest.approx(1.0, rel=1e-6), (
            f"Phase 3 weights sum to {total}, expected 1.0"
        )

    def test_distance_plus_motion_start_stop_promotes(self) -> None:
        """distance_crossing + object_motion_start_stop = 0.25 + 0.10 = 0.35 → promotes (§4.3)."""
        events = _two_source_events(
            "gripper_object_distance_threshold_crossing", "object_motion_start_stop"
        )
        candidates = integrated_candidates(
            events,
            fps=FPS,
            merge_window_sec=MERGE_WINDOW_SEC,
            weights=_weights_dict(),
            score_threshold=SCORE_THRESHOLD,
        )
        assert len(candidates) == 1, (
            f"Expected 1 candidate (score 0.35 >= threshold 0.30), got {len(candidates)}"
        )
        assert candidates[0].score == pytest.approx(0.35, rel=1e-6)


# ---------------------------------------------------------------------------
# End-to-end integration test: Phase3BoundaryDetector.detect() weights wiring
# ---------------------------------------------------------------------------

def _make_track_w(track_id: str, role: str) -> Track:
    bbox = BBox(x=0.1, y=0.1, w=0.1, h=0.1)
    sample = TrackSample(frame=0, time_sec=0.0, bbox=bbox, score=1.0)
    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=track_id,
        slug=track_id,
        index=0,
        primary=True,
        samples=[sample],
        gap_events=[],
    )


class TestPhase3DetectorEndToEnd:
    def test_phase3_detector_end_to_end_promotes_grasp_event(self) -> None:
        """gripper_transition + distance_crossing co-fire → score 0.70 via .detect().

        Verifies that Phase3BoundaryDetector.detect() correctly wires BoundaryWeights
        field values into the source-name-keyed dict consumed by integrated_candidates.
        A bug in boundaries.py:443-451 would produce wrong scores here.
        """
        fps = 30.0
        n = 100
        # w_dist = round(0.10 * 30) = 3; crossing at frame 50 needs room both sides
        threshold = 0.05  # TrackingConfig default

        # Distance signal: above threshold [0:50), below [50:n) → crossing at t=50
        d = np.full(n, 0.10, dtype=np.float64)
        d[50:] = 0.01

        # Gripper signal: sharp open→close at frame 50
        gripper = np.full(n, 1.0, dtype=np.float64)
        gripper[50:] = 0.0

        eef_vel = np.full(n, 0.5, dtype=np.float64)
        eef_accel = np.full(n, 0.0, dtype=np.float64)
        action_norm = np.zeros(n, dtype=np.float64)

        signals = ObjectSignals(
            gripper_object_distance={"obj1": d},
            object_speed={"obj1": np.full(n, 0.01, dtype=np.float64)},
            object_center={},
            primary_object_track_id="obj1",
            primary_target_track_id=None,
            gripper_tool_track_id="tool1",
        )
        tracks = [_make_track_w("obj1", "object"), _make_track_w("tool1", "tool")]

        det = Phase3BoundaryDetector(
            fps=fps,
            weights=BoundaryWeights.phase3_defaults(),
            score_threshold=0.30,
            merge_window_sec=0.10,
            disabled_sources=[],
            tracking_config=TrackingConfig(gripper_object_distance_threshold=threshold),
        )
        candidates, final_disabled = det.detect(
            gripper=gripper,
            eef_vel=eef_vel,
            eef_accel=eef_accel,
            action_norm=action_norm,
            object_signals=signals,
            tracks=tracks,
        )

        # Both sources must be enabled
        assert "gripper_transition" not in final_disabled
        assert "gripper_object_distance_threshold_crossing" not in final_disabled

        # At least one candidate must have both sources co-fired at score 0.70
        grasp_candidates = [
            c for c in candidates
            if "gripper_transition" in c.sources
            and "gripper_object_distance_threshold_crossing" in c.sources
        ]
        assert len(grasp_candidates) >= 1, (
            f"Expected a merged grasp candidate with both sources, got candidates: {candidates}"
        )
        assert grasp_candidates[0].score == pytest.approx(0.70, rel=1e-6), (
            f"Expected score 0.70 (gripper 0.45 + distance 0.25), got {grasp_candidates[0].score}"
        )
