"""Test fixtures — FixtureTrackingPlanner + FixtureSAM3Tracker (spec §2.6).

These fixtures provide no-GPU, no-model-weights test doubles for the core
tracking loop. They support canned happy-path returns and configurable
failure injection (e.g., raise on first call, raise at a specific frame).
"""

from __future__ import annotations

import pytest

from mimicanno.object_tracker import FramePropagationResult as ExportedFramePropagationResult
from mimicanno.object_tracker.fixtures import (
    FixtureSAM3Tracker,
    FixtureTrackingPlanner,
    FramePropagationResult,
)
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import BBox

# ---- FixtureTrackingPlanner ----


def test_planner_returns_canned_entities() -> None:
    """Happy path: extract_entities returns the canned EntityPlan."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=[],
    )
    planner = FixtureTrackingPlanner(entities=entities)

    # Call with any arguments — should return canned entities unchanged.
    import numpy as np

    result = planner.extract_entities(
        task_text="pick up the red block",
        initial_frame=np.zeros((1, 1, 3), dtype=np.uint8),
        allowed_labels=None,  # type: ignore
        attempt_max=3,
    )
    assert result is entities


def test_planner_raise_on_first_call_then_succeeds() -> None:
    """Failure injection: raise_on_extract raises on first call, then succeeds."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=[],
        tool_prompts=[],
    )
    exc = ValueError("test error")
    planner = FixtureTrackingPlanner(entities=entities, raise_on_extract=exc)

    import numpy as np

    # First call raises the injected exception.
    with pytest.raises(ValueError, match="test error"):
        planner.extract_entities(
            task_text="x",
            initial_frame=np.zeros((1, 1, 3), dtype=np.uint8),
            allowed_labels=None,  # type: ignore
            attempt_max=3,
        )

    # Second call succeeds and returns canned entities.
    result = planner.extract_entities(
        task_text="x",
        initial_frame=np.zeros((1, 1, 3), dtype=np.uint8),
        allowed_labels=None,  # type: ignore
        attempt_max=3,
    )
    assert result is entities


# ---- FixtureSAM3Tracker ----


def test_tracker_ground_on_frame_canned_populated() -> None:
    """Happy path: ground_on_frame returns canned (bbox, score) pairs."""
    bbox1 = BBox(0.1, 0.1, 0.2, 0.2)
    bbox2 = BBox(0.5, 0.5, 0.3, 0.3)
    initial_detections = {
        "red block": [(bbox1, 0.95), (bbox2, 0.80)],
    }
    tracker = FixtureSAM3Tracker(initial_detections=initial_detections)

    import numpy as np

    result = tracker.ground_on_frame(
        frame=np.zeros((1, 1, 3), dtype=np.uint8),
        prompt="red block",
    )
    assert result == [(bbox1, 0.95), (bbox2, 0.80)]


def test_tracker_ground_on_frame_canned_empty() -> None:
    """ground_on_frame returns empty list if no initial detections for a prompt."""
    initial_detections: dict[str, list[tuple[BBox, float]]] = {
        "red block": [],
        "bin A": [],
    }
    tracker = FixtureSAM3Tracker(initial_detections=initial_detections)

    import numpy as np

    result = tracker.ground_on_frame(
        frame=np.zeros((1, 1, 3), dtype=np.uint8),
        prompt="bin A",
    )
    assert result == []


def test_tracker_propagate_yields_canned_results() -> None:
    """Happy path: propagate yields FramePropagationResult for each frame."""
    bbox1 = BBox(0.1, 0.1, 0.2, 0.2)
    bbox2 = BBox(0.5, 0.5, 0.3, 0.3)

    propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (bbox1, 0.95), "bin A": None},
        1: {"red block": (bbox2, 0.85), "bin A": (BBox(0.0, 0.0, 0.1, 0.1), 0.9)},
    }
    tracker = FixtureSAM3Tracker(propagation_results=propagation_results)

    from pathlib import Path

    results = list(
        tracker.propagate(
            video_path=Path("/dev/null"),  # ignored by fixture
            prompts_with_initial_bbox=[
                ("red block", BBox(0.1, 0.1, 0.2, 0.2)),
                ("bin A", BBox(0.0, 0.0, 0.1, 0.1)),
            ],
            expected_frames={0, 1},
        )
    )

    assert len(results) == 2
    assert results[0].frame == 0
    assert results[0].detections == {
        "red block": (bbox1, 0.95),
        "bin A": None,
    }
    assert results[1].frame == 1
    assert results[1].detections == {
        "red block": (bbox2, 0.85),
        "bin A": (BBox(0.0, 0.0, 0.1, 0.1), 0.9),
    }


def test_tracker_load_raises_when_configured() -> None:
    """Failure injection: load raises configured exception."""
    exc = RuntimeError("CUDA OOM")
    tracker = FixtureSAM3Tracker(raise_on_load=exc)

    with pytest.raises(RuntimeError, match="CUDA OOM"):
        tracker.load()


def test_tracker_load_succeeds_when_not_configured() -> None:
    """load returns self on success (instance method, not classmethod)."""
    tracker = FixtureSAM3Tracker()
    result = tracker.load()
    assert result is tracker


def test_tracker_propagate_raises_at_specific_frame() -> None:
    """Failure injection: propagate yields normal results, raises at frame 42."""
    propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] = {
        0: {"red block": (BBox(0.1, 0.1, 0.2, 0.2), 0.95)},
        1: {"red block": (BBox(0.15, 0.15, 0.2, 0.2), 0.90)},
    }
    exc = RuntimeError("kernel fault")
    tracker = FixtureSAM3Tracker(
        propagation_results=propagation_results,
        raise_on_propagate_at_frame=42,
        raise_with=exc,
    )

    from pathlib import Path

    gen = tracker.propagate(
        video_path=Path("/dev/null"),
        prompts_with_initial_bbox=[("red block", BBox(0.1, 0.1, 0.2, 0.2))],
        expected_frames={0, 1, 42},
    )

    # Frames 0 and 1 yield normally.
    result_0 = next(gen)
    assert result_0.frame == 0

    result_1 = next(gen)
    assert result_1.frame == 1

    # Frame 42 raises.
    with pytest.raises(RuntimeError, match="kernel fault"):
        next(gen)


def test_tracker_close_is_idempotent() -> None:
    """close() can be called multiple times without error."""
    tracker = FixtureSAM3Tracker()
    tracker.close()
    tracker.close()  # Should not raise.


def test_frame_propagation_result_immutable() -> None:
    """FramePropagationResult is frozen."""
    bbox = BBox(0.1, 0.1, 0.2, 0.2)
    result = FramePropagationResult(
        frame=0,
        detections={"red block": (bbox, 0.95)},
    )

    with pytest.raises(AttributeError):
        result.frame = 1  # type: ignore


def test_tracker_init_with_defaults() -> None:
    """FixtureSAM3Tracker with no args uses empty dicts."""
    tracker = FixtureSAM3Tracker()
    # Should not raise; using defaults.
    import numpy as np

    result = tracker.ground_on_frame(
        frame=np.zeros((1, 1, 3), dtype=np.uint8),
        prompt="anything",
    )
    assert result == []


def test_tracker_load_accepts_checkpoint_and_device_kwargs() -> None:
    """load() accepts checkpoint and device kwargs (happy path)."""
    tracker = FixtureSAM3Tracker()
    result = tracker.load(checkpoint="/path/to/model.pt", device="cuda")
    assert result is tracker


def test_tracker_load_still_raises_with_kwargs_present() -> None:
    """raise_on_load still fires when checkpoint/device kwargs are passed."""
    exc = RuntimeError("Model load failure")
    tracker = FixtureSAM3Tracker(raise_on_load=exc)

    with pytest.raises(RuntimeError, match="Model load failure"):
        tracker.load(checkpoint="/path/to/model.pt", device="cuda")


def test_frame_propagation_result_exported_from_package() -> None:
    """FramePropagationResult is accessible from mimicanno.object_tracker package."""
    assert ExportedFramePropagationResult is FramePropagationResult
