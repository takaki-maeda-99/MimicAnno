"""Tests for ground_initial_detections_with_retry (spec §5.1)."""

from __future__ import annotations

import numpy as np

from mimicanno.object_tracker.fixtures import FixtureSAM3Tracker
from mimicanno.object_tracker.propagator import BBox


def _frame(value: int = 0) -> np.ndarray:
    # A tiny RGB frame; FixtureSAM3Tracker ignores pixel content,
    # so this is just a placeholder.
    return np.full((4, 4, 3), value, dtype=np.uint8)


def test_fixture_frame_aware_lookup() -> None:
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={
            0: {"tape": []},  # frame 0: tape not found
            75: {"tape": [(BBox(0.1, 0.1, 0.2, 0.2), 0.9)]},  # frame 75: tape found
        },
    )
    assert fx.ground_on_frame(_frame(), "tape", frame_index=0) == []
    results = fx.ground_on_frame(_frame(), "tape", frame_index=75)
    assert len(results) == 1
    assert results[0][1] == 0.9


def test_fixture_backward_compatible_initial_detections() -> None:
    # When only the legacy `initial_detections` is set, all frame_index
    # values resolve to frame 0's table.
    fx = FixtureSAM3Tracker(
        initial_detections={"tape": [(BBox(0.0, 0.0, 0.5, 0.5), 0.8)]},
    )
    legacy = fx.ground_on_frame(_frame(), "tape")  # no frame_index kwarg
    assert legacy == [(BBox(0.0, 0.0, 0.5, 0.5), 0.8)]
    same = fx.ground_on_frame(_frame(), "tape", frame_index=42)
    assert same == [(BBox(0.0, 0.0, 0.5, 0.5), 0.8)]


def test_fixture_unknown_frame_returns_empty() -> None:
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={0: {"tape": []}},
    )
    # frame 99 not in dict → empty list (not KeyError)
    assert fx.ground_on_frame(_frame(), "tape", frame_index=99) == []
