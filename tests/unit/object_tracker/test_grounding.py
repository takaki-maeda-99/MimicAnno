"""Tests for ground_initial_detections (spec §2.4.0, Task 16).

Covers Step B grounding: iterates EntityPlan prompts, grounds on initial frame,
takes highest-scoring bbox, builds TrackingPlan with initial_detections and
failed_prompts. Tests cover:

1. Happy path: all prompts grounded successfully.
2. Partial failure: some prompts return no detections.
3. All object prompts failed: full failure scenario.
4. Cross-role duplicates: same prompt in different roles -> separate entries.
5. Highest-score selection: multiple detections per prompt -> best wins.
"""

from __future__ import annotations

from unittest import mock

import numpy as np

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    TrackingPlan,
    ground_initial_detections,
)

# ---------------------------------------------------------------------------
# Test 1: Happy path — all grounded
# ---------------------------------------------------------------------------


def test_happy_path_all_grounded() -> None:
    """All prompts grounded successfully: 3 prompts, 3 detections."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
    )

    # Mock runtime returning one detection per prompt
    mock_runtime = mock.MagicMock()
    mock_runtime.ground_on_frame.side_effect = [
        [(BBox(0.1, 0.1, 0.2, 0.2), 0.95)],  # object: red block
        [(BBox(0.5, 0.5, 0.3, 0.3), 0.90)],  # target: bin A
        [(BBox(0.7, 0.1, 0.15, 0.15), 0.85)],  # tool: gripper
    ]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = ground_initial_detections(
        runtime=mock_runtime,
        initial_frame=frame,
        entities=entities,
    )

    # Verify TrackingPlan structure
    assert isinstance(result, TrackingPlan)
    assert result.entities is entities
    assert len(result.initial_detections) == 3
    assert len(result.failed_prompts) == 0

    # Verify each detection
    assert result.initial_detections[("object", "red block")] == BBox(0.1, 0.1, 0.2, 0.2)
    assert result.initial_detections[("target", "bin A")] == BBox(0.5, 0.5, 0.3, 0.3)
    assert result.initial_detections[("tool", "gripper")] == BBox(0.7, 0.1, 0.15, 0.15)


# ---------------------------------------------------------------------------
# Test 2: Partial failure — one prompt in failed_prompts
# ---------------------------------------------------------------------------


def test_partial_failure_target_in_failed_prompts() -> None:
    """One target returns no detections; ends in failed_prompts, not initial_detections."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=[],
    )

    mock_runtime = mock.MagicMock()
    mock_runtime.ground_on_frame.side_effect = [
        [(BBox(0.1, 0.1, 0.2, 0.2), 0.95)],  # object: red block -> success
        [],  # target: bin A -> failure (empty list)
    ]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = ground_initial_detections(
        runtime=mock_runtime,
        initial_frame=frame,
        entities=entities,
    )

    # Only 1 detection (object)
    assert len(result.initial_detections) == 1
    assert result.initial_detections[("object", "red block")] == BBox(0.1, 0.1, 0.2, 0.2)

    # Failed target in failed_prompts
    assert len(result.failed_prompts) == 1
    assert ("target", "bin A") in result.failed_prompts


# ---------------------------------------------------------------------------
# Test 3: All object prompts failed — caller handles degrade
# ---------------------------------------------------------------------------


def test_all_object_prompts_failed_caller_handles_degrade() -> None:
    """All 3 object prompts return empty; all in failed_prompts.
    Caller (orchestrator) responsible for whole-run degrade, NOT this function."""
    entities = EntityPlan(
        object_prompts=["red block", "blue cube", "green sphere"],
        target_prompts=[],
        tool_prompts=[],
    )

    mock_runtime = mock.MagicMock()
    mock_runtime.ground_on_frame.side_effect = [
        [],  # red block -> failure
        [],  # blue cube -> failure
        [],  # green sphere -> failure
    ]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = ground_initial_detections(
        runtime=mock_runtime,
        initial_frame=frame,
        entities=entities,
    )

    # No detections
    assert len(result.initial_detections) == 0

    # All 3 object prompts in failed_prompts
    assert len(result.failed_prompts) == 3
    assert ("object", "red block") in result.failed_prompts
    assert ("object", "blue cube") in result.failed_prompts
    assert ("object", "green sphere") in result.failed_prompts


# ---------------------------------------------------------------------------
# Test 4: Cross-role duplicates preserved
# ---------------------------------------------------------------------------


def test_cross_role_duplicates_preserved() -> None:
    """Same prompt in object and target roles; two distinct entries in initial_detections."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["red block"],  # Same prompt, different role
        tool_prompts=[],
    )

    mock_runtime = mock.MagicMock()
    # Return different bboxes for each call (emulating the grounding returning
    # different results for the same prompt in different frames/contexts)
    mock_runtime.ground_on_frame.side_effect = [
        [(BBox(0.1, 0.1, 0.2, 0.2), 0.95)],  # object: red block
        [(BBox(0.4, 0.4, 0.15, 0.15), 0.92)],  # target: red block (different bbox)
    ]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = ground_initial_detections(
        runtime=mock_runtime,
        initial_frame=frame,
        entities=entities,
    )

    # Two distinct entries, one per (role, prompt) tuple
    assert len(result.initial_detections) == 2
    assert result.initial_detections[("object", "red block")] == BBox(0.1, 0.1, 0.2, 0.2)
    assert result.initial_detections[("target", "red block")] == BBox(0.4, 0.4, 0.15, 0.15)
    assert len(result.failed_prompts) == 0


# ---------------------------------------------------------------------------
# Test 5: Highest-score wins
# ---------------------------------------------------------------------------


def test_highest_score_wins() -> None:
    """When ground_on_frame returns multiple detections, highest-score bbox is chosen."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=[],
        tool_prompts=[],
    )

    # Multiple detections with different scores; highest is 0.95 (second one)
    mock_runtime = mock.MagicMock()
    mock_runtime.ground_on_frame.return_value = [
        (BBox(0.0, 0.0, 0.1, 0.1), 0.90),  # Score 0.90
        (BBox(0.2, 0.2, 0.15, 0.15), 0.95),  # Score 0.95 <- highest
        (BBox(0.5, 0.5, 0.2, 0.2), 0.85),  # Score 0.85
    ]

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = ground_initial_detections(
        runtime=mock_runtime,
        initial_frame=frame,
        entities=entities,
    )

    # Should select the second one (highest score)
    assert len(result.initial_detections) == 1
    assert result.initial_detections[("object", "red block")] == BBox(0.2, 0.2, 0.15, 0.15)
    assert len(result.failed_prompts) == 0
