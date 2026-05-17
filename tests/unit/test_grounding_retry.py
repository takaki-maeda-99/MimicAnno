"""Tests for ground_initial_detections_with_retry (spec §5.1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mimicanno.object_tracker.fixtures import FixtureSAM3Tracker
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    GroundingAttempt,
    ground_initial_detections_with_retry,
)


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


# ---------------------------------------------------------------------------
# ground_initial_detections_with_retry tests (spec §5.1)
# ---------------------------------------------------------------------------


def _entities() -> EntityPlan:
    # One "object" prompt: "tape". No targets, no tools.
    return EntityPlan(
        object_prompts=["tape"], target_prompts=[], tool_prompts=[],
    )


def _video_stub(monkeypatch, frames: dict[int, np.ndarray]) -> Path:
    """Stub mimicanno.object_tracker.propagator._extract_frame_at to return canned frames.

    The retry helper calls _extract_frame_at internally; for unit tests
    we patch the loader so tests don't need a real video file.
    """
    import mimicanno.object_tracker.propagator as prop_mod

    def fake_extract(video_path: Path, n_frames: int, frame_index: int) -> np.ndarray:
        if frame_index not in frames:
            raise OSError(f"frame {frame_index} not in stub")
        return frames[frame_index]

    monkeypatch.setattr(prop_mod, "_extract_frame_at", fake_extract)
    return Path("/dev/null/stub.mp4")


def test_retry_frame_zero_succeeds(monkeypatch) -> None:
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={0: {"tape": [(BBox(0.1, 0.1, 0.2, 0.2), 0.9)]}},
    )
    video = _video_stub(monkeypatch, {0: _frame()})
    idx, used_frame, plan, attempts = ground_initial_detections_with_retry(
        runtime=fx, video_path=video, n_frames=150, entities=_entities(),
        retry_fractions=[0.5, 0.25, 0.75],
    )
    assert idx == 0
    assert len(attempts) == 1
    assert attempts[0] == GroundingAttempt(
        frame_index=0, n_object_grounded=1, n_total_grounded=1,
        adopted=True, skipped_reason=None,
    )
    assert ("object", "tape") in plan.initial_detections


def test_retry_succeeds_at_midpoint(monkeypatch) -> None:
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={
            0: {"tape": []},
            75: {"tape": [(BBox(0.1, 0.1, 0.2, 0.2), 0.9)]},
        },
    )
    video = _video_stub(monkeypatch, {0: _frame(), 75: _frame()})
    idx, _, plan, attempts = ground_initial_detections_with_retry(
        runtime=fx, video_path=video, n_frames=150, entities=_entities(),
        retry_fractions=[0.5, 0.25, 0.75],
    )
    assert idx == 75
    # Two attempts: frame 0 (failed), frame 75 (adopted)
    assert len(attempts) == 2
    assert attempts[0].adopted is False and attempts[0].frame_index == 0
    assert attempts[1].adopted is True and attempts[1].frame_index == 75
    assert ("object", "tape") in plan.initial_detections


def test_retry_total_failure_returns_none(monkeypatch) -> None:
    # All four attempts (0, 75, 37, 112) return empty for "tape".
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={
            0: {"tape": []}, 75: {"tape": []},
            37: {"tape": []}, 112: {"tape": []},
        },
    )
    video = _video_stub(
        monkeypatch,
        {0: _frame(), 75: _frame(), 37: _frame(), 112: _frame()},
    )
    idx, _, plan, attempts = ground_initial_detections_with_retry(
        runtime=fx, video_path=video, n_frames=150, entities=_entities(),
        retry_fractions=[0.5, 0.25, 0.75],
    )
    assert idx is None
    # All adopted=False
    assert all(a.adopted is False for a in attempts)
    # All four frame indices were attempted
    assert [a.frame_index for a in attempts] == [0, 75, 37, 112]
    # Plan's initial_detections has no object role
    object_grounded = [
        (r, p) for (r, p) in plan.initial_detections if r == "object"
    ]
    assert object_grounded == []


def test_retry_skipped_due_to_empty_fractions(monkeypatch) -> None:
    # retry_fractions=[] disables retry; frame 0 alone is tried.
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={0: {"tape": []}},
    )
    video = _video_stub(monkeypatch, {0: _frame()})
    idx, _, plan, attempts = ground_initial_detections_with_retry(
        runtime=fx, video_path=video, n_frames=150, entities=_entities(),
        retry_fractions=[],
    )
    assert idx is None
    assert len(attempts) == 1
    assert attempts[0].frame_index == 0


def test_retry_io_error_is_skipped(monkeypatch) -> None:
    # Frame 75 fails to read; helper should skip and continue to 37.
    fx = FixtureSAM3Tracker(
        initial_detections_by_frame={
            0: {"tape": []},
            37: {"tape": [(BBox(0.1, 0.1, 0.2, 0.2), 0.9)]},
        },
    )
    # 75 is intentionally missing from the stub → OSError
    video = _video_stub(monkeypatch, {0: _frame(), 37: _frame()})
    idx, _, plan, attempts = ground_initial_detections_with_retry(
        runtime=fx, video_path=video, n_frames=150, entities=_entities(),
        retry_fractions=[0.5, 0.25, 0.75],
    )
    assert idx == 37
    # Three attempts: frame 0 (failed empty), frame 75 (io_error), frame 37 (adopted)
    assert len(attempts) == 3
    assert attempts[1].frame_index == 75
    assert attempts[1].skipped_reason == "io_error"
    assert attempts[1].adopted is False
    assert attempts[2].adopted is True
