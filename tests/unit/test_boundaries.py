# tests/unit/test_boundaries.py
import numpy as np
import pytest

from mimicanno.boundaries import (
    DEFAULT_PHASE1_WEIGHTS,
    RawEvent,
    detect_action_norm_change,
    detect_eef_acceleration_peak,
    detect_eef_velocity_valley,
    detect_gripper_transition,
    integrated_candidates,
)


def _smooth_step(n: int, edge: int, low: float, high: float) -> np.ndarray:
    out = np.full(n, low, dtype=np.float64)
    out[edge:] = high
    return out


class TestGripperTransition:
    def test_detects_close_event(self):
        # gripper goes from 1.0 (open) to 0.0 (closed) sharply at frame 50
        g = np.concatenate([np.ones(50), np.zeros(70)])
        events = detect_gripper_transition(g, fps=30.0, delta_threshold=0.30)
        assert any(40 <= e.frame <= 60 for e in events)
        for e in events:
            assert e.source == "gripper_transition"
            assert 0.0 <= e.source_score <= 1.0

    def test_no_event_when_flat(self):
        g = np.full(120, 0.5)
        events = detect_gripper_transition(g, fps=30.0, delta_threshold=0.30)
        assert events == []


class TestVelocityValley:
    def test_valley_below_threshold_is_detected(self):
        # Triangle: high → near-zero (valley) → high
        v = np.abs(np.linspace(-0.5, 0.5, 120)) * 0.4
        events = detect_eef_velocity_valley(
            v, fps=30.0, valley_threshold=0.05, min_valley_sec=0.10,
        )
        # Valley centered around frame 60
        assert any(50 <= e.frame <= 70 for e in events)


class TestAccelPeak:
    def test_peak_above_threshold(self):
        a = np.zeros(120)
        a[60] = 10.0  # spike
        events = detect_eef_acceleration_peak(a, fps=30.0, peak_threshold=1.0)
        assert any(e.frame == 60 for e in events)


class TestActionNormChange:
    def test_change_detected(self):
        norms = np.concatenate([np.full(60, 0.1), np.full(60, 0.5)])
        events = detect_action_norm_change(
            norms, fps=30.0, change_threshold=0.2, window_sec=0.5,
        )
        assert any(50 <= e.frame <= 70 for e in events)


class TestIntegrated:
    def test_max_merge_for_same_source(self):
        # Two same-source events in the merge window → max wins, not last
        events = [
            RawEvent(frame=10, time=10 / 30, source="gripper_transition", source_score=0.9),
            RawEvent(frame=11, time=11 / 30, source="gripper_transition", source_score=0.4),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert len(candidates) == 1
        c = candidates[0]
        assert c.scores["gripper_transition"] == pytest.approx(0.9)
        assert c.score == pytest.approx(0.9 * 0.5, abs=1e-9)

    def test_threshold_filters_below(self):
        events = [RawEvent(frame=5, time=5/30, source="eef_velocity_valley", source_score=1.0)]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        # eef_velocity_valley alone caps at 0.25 < 0.30 → dropped
        assert candidates == []

    def test_two_non_gripper_can_promote(self):
        # gripper-biased policy (§5.3): velocity 0.25 + accel 0.15 = 0.40 > 0.30
        events = [
            RawEvent(frame=10, time=10/30, source="eef_velocity_valley", source_score=1.0),
            RawEvent(frame=10, time=10/30, source="eef_acceleration_peak", source_score=1.0),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert len(candidates) == 1
        assert candidates[0].score == pytest.approx(0.40, abs=1e-9)
        assert sorted(candidates[0].sources) == [
            "eef_acceleration_peak", "eef_velocity_valley",
        ]

    def test_disabled_source_contributes_zero_no_renormalization(self):
        # If gripper detector were enabled it would self-promote; here we leave
        # it out and confirm the weight stays at 0.5 (no renormalization).
        weights = dict(DEFAULT_PHASE1_WEIGHTS)
        events = [
            RawEvent(frame=10, time=10/30, source="eef_velocity_valley", source_score=1.0),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=weights, score_threshold=0.30,
        )
        assert candidates == []  # 0.25 still below 0.30 — gripper weight is NOT redistributed.

    def test_candidate_id_is_zero_padded(self):
        events = [
            RawEvent(frame=i, time=i/30, source="gripper_transition", source_score=1.0)
            for i in range(0, 120, 30)
        ]
        cands = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.05,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert [c.id for c in cands] == ["b_001", "b_002", "b_003", "b_004"]
