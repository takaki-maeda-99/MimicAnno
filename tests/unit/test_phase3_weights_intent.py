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
"""

from __future__ import annotations

import pytest

from mimicanno.boundaries import RawEvent, integrated_candidates
from mimicanno.config import BoundaryWeights

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
