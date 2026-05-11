"""Unit tests for the Phase 4 finer-segmentation ZC detector.

spec: docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md §4.3
"""

from __future__ import annotations

import numpy as np
import pytest

from mimicanno.boundaries import (
    _merge_close_zc_events,
    _resolve_zc_ref,
    detect_gripper_zero_crossing,
)
from mimicanno.config import ZeroCrossingConfig


def _trapezoid(n_pre: int, n_ramp: int, n_plateau: int, *, lo: float, hi: float) -> np.ndarray:
    """One trapezoid cycle: [lo]*n_pre + ramp_up + [hi]*n_plateau + ramp_down."""
    pre = np.full(n_pre, lo)
    up = np.linspace(lo, hi, n_ramp, endpoint=False)
    top = np.full(n_plateau, hi)
    down = np.linspace(hi, lo, n_ramp, endpoint=False)
    return np.concatenate([pre, up, top, down])


def _enabled(**kw) -> ZeroCrossingConfig:
    base = {"enabled": True, "hysteresis": 0.10, "span_eps": 0.05, "weight": 0.5}
    base.update(kw)
    return ZeroCrossingConfig(**base)


# --- Core behaviour ---------------------------------------------------------


def test_single_cycle_produces_two_boundaries() -> None:
    # one open+close: low -> high -> low
    cycle = _trapezoid(5, 10, 10, lo=0.0, hi=0.4)
    tail = np.full(20, 0.0)
    g = np.concatenate([cycle, tail])
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled())
    assert len(events) == 2
    assert all(e.source == "gripper_zero_crossing" for e in events)
    # boundary times should be strictly increasing
    assert events[0].time < events[1].time


def test_two_cycles_produces_four_boundaries() -> None:
    c1 = _trapezoid(5, 10, 10, lo=0.0, hi=0.4)
    gap = np.full(10, 0.0)
    c2 = _trapezoid(0, 10, 10, lo=0.0, hi=0.4)
    g = np.concatenate([c1, gap, c2, np.full(5, 0.0)])
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled())
    assert len(events) == 4


def test_flat_signal_produces_no_boundaries() -> None:
    g = np.full(100, 0.2)
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(span_eps=0.05))
    assert events == []


def test_shallow_excursion_below_hysteresis_filtered() -> None:
    # excursion peak 0.07 but hysteresis 0.10 → no events
    g = _trapezoid(5, 6, 6, lo=0.0, hi=0.07)
    g = np.concatenate([g, np.full(10, 0.0)])
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(hysteresis=0.10))
    assert events == []


def test_excursion_just_above_hysteresis_fires() -> None:
    # midpoint ref ⇒ max excursion = (hi-lo)/2 = 0.125 > hyst 0.10.
    g = _trapezoid(5, 8, 6, lo=0.0, hi=0.25)
    g = np.concatenate([g, np.full(10, 0.0)])
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(hysteresis=0.10))
    assert len(events) == 2


def test_disabled_returns_empty() -> None:
    g = _trapezoid(5, 10, 10, lo=0.0, hi=0.4)
    cfg = ZeroCrossingConfig(enabled=False)
    assert detect_gripper_zero_crossing(g, fps=50.0, cfg=cfg) == []


def test_too_short_signal_returns_empty() -> None:
    assert detect_gripper_zero_crossing(np.array([0.3]), fps=50.0, cfg=_enabled()) == []
    assert detect_gripper_zero_crossing(np.array([]), fps=50.0, cfg=_enabled()) == []


def test_source_score_within_unit_interval() -> None:
    g = _trapezoid(5, 10, 10, lo=0.0, hi=0.4)
    g = np.concatenate([g, np.full(5, 0.0)])
    events = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled())
    for e in events:
        assert 0.0 <= e.source_score <= 1.0


# --- Ref modes --------------------------------------------------------------


def test_ref_midpoint() -> None:
    g = np.array([0.0, 0.1, 0.4, 0.1, 0.0])
    assert _resolve_zc_ref(g, "midpoint") == pytest.approx(0.2)


def test_ref_median() -> None:
    g = np.array([0.0, 0.0, 0.3, 0.0, 0.0])
    assert _resolve_zc_ref(g, "median") == pytest.approx(0.0)


def test_ref_fixed() -> None:
    g = np.zeros(10)
    assert _resolve_zc_ref(g, "fixed:0.18") == pytest.approx(0.18)


def test_ref_modes_drive_different_event_timing() -> None:
    # Symmetric signal with two trapezoids of different heights. midpoint =
    # (0.6+0)/2 = 0.30, while fixed:0.15 crosses earlier in the ramp.
    g = _trapezoid(5, 10, 10, lo=0.0, hi=0.6)
    g = np.concatenate([g, np.full(10, 0.0)])
    ev_mid = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(ref="midpoint"))
    ev_fixed = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(ref="fixed:0.15"))
    assert len(ev_mid) == 2 and len(ev_fixed) == 2
    # fixed:0.15 crosses earlier on the rising ramp than midpoint=0.30.
    assert ev_fixed[0].time < ev_mid[0].time


# --- Merge window -----------------------------------------------------------


def test_merge_close_events_drops_neighbours() -> None:
    from mimicanno.boundaries import RawEvent

    evs = [
        RawEvent(frame=10, time=0.20, source="gripper_zero_crossing", source_score=0.5),
        RawEvent(frame=12, time=0.24, source="gripper_zero_crossing", source_score=0.4),
        RawEvent(frame=50, time=1.00, source="gripper_zero_crossing", source_score=0.6),
    ]
    merged = _merge_close_zc_events(evs, merge_window_sec=0.30)
    assert len(merged) == 2
    assert merged[0].time == pytest.approx(0.20)
    assert merged[1].time == pytest.approx(1.00)


def test_merge_window_zero_keeps_all() -> None:
    g = _trapezoid(5, 4, 2, lo=0.0, hi=0.4)
    g = np.concatenate([g, _trapezoid(0, 4, 2, lo=0.0, hi=0.4), np.full(5, 0.0)])
    evs = detect_gripper_zero_crossing(g, fps=50.0, cfg=_enabled(merge_window_sec=0.0))
    assert len(evs) >= 3


# --- Sub-frame interpolation ------------------------------------------------


def test_linear_interpolation_subframe_precision() -> None:
    # Ref=0; samples [-0.4, 0.4] at i=0,1 → crossing at frame 0.5 → t=0.5/fps
    g = np.array([-0.4, 0.4, 0.4, -0.4, -0.4])  # cycle: pos, neg, pos
    evs = detect_gripper_zero_crossing(
        g, fps=10.0, cfg=_enabled(ref="fixed:0.0", hysteresis=0.1, span_eps=0.01)
    )
    assert len(evs) >= 1
    # First crossing should be midway between samples 0 and 1 → t≈0.05s.
    assert evs[0].time == pytest.approx(0.05, abs=1e-6)
