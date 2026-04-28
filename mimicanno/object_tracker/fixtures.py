"""Test fixtures — FixtureTrackingPlanner + FixtureSAM3Tracker (spec §2.6).

These fixtures provide no-GPU, no-model-weights test doubles for the core
tracking loop. They support canned happy-path returns and configurable
failure injection (e.g., raise on first call, raise at a specific frame).

FramePropagationResult is the dataclass contract shared between fixtures
and the real SAM3Runtime (which lands in Task 14).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import BBox


@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    """Output of SAM3Runtime.propagate() — one frame's detection results.

    frame: the integer frame index
    detections: dict[prompt] -> (BBox, score) | None, where None means
        the prompt was not detected or tracking was lost.
    """

    frame: int
    detections: dict[str, tuple[BBox, float] | None]


class FixtureTrackingPlanner:
    """Test double for TrackingPlanner (spec §2.2).

    Implements the TrackingPlanner Protocol. Returns canned EntityPlan
    from extract_entities; supports failure injection via raise_on_extract.
    """

    def __init__(
        self,
        entities: EntityPlan,
        raise_on_extract: Exception | None = None,
    ) -> None:
        self.entities = entities
        self.raise_on_extract = raise_on_extract
        self._first_call = True

    def extract_entities(
        self,
        *,
        task_text: str,
        initial_frame: np.ndarray,
        allowed_labels: LabelSet,
        attempt_max: int = 3,
    ) -> EntityPlan:
        """Returns the canned EntityPlan. Raises once if configured.

        If raise_on_extract was set in __init__, raises that exception
        on the first call, then returns canned entities on subsequent calls.
        (Used to test retry logic in Task 8.)

        Args:
            task_text: ignored
            initial_frame: ignored
            allowed_labels: ignored
            attempt_max: ignored

        Returns:
            The canned EntityPlan.

        Raises:
            The configured exception on first call only.
        """
        if self._first_call and self.raise_on_extract is not None:
            self._first_call = False
            raise self.raise_on_extract
        self._first_call = False
        return self.entities


class FixtureSAM3Tracker:
    """Test double for SAM3Runtime (spec §2.3).

    Provides canned grounding results and propagation frames; supports
    failure injection via raise_on_load, raise_on_propagate_at_frame.

    The load() method is an instance method (not classmethod like the real
    SAM3Runtime), to allow configuration of raise_on_load. This is a
    deliberate deviation documented here; tests do not depend on the
    construction pattern.
    """

    def __init__(
        self,
        *,
        initial_detections: dict[str, list[tuple[BBox, float]]] | None = None,
        propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] | None = None,
        raise_on_load: Exception | None = None,
        raise_on_propagate_at_frame: int | None = None,
        raise_with: Exception | None = None,
    ) -> None:
        self.initial_detections = initial_detections or {}
        self.propagation_results = propagation_results or {}
        self.raise_on_load = raise_on_load
        self.raise_on_propagate_at_frame = raise_on_propagate_at_frame
        self.raise_with = raise_with
        self._closed = False

    def load(self) -> FixtureSAM3Tracker:
        """Load (initialize) the tracker.

        Raises the configured exception if raise_on_load was set in __init__.

        Returns:
            self (for chainability in tests).

        Raises:
            The configured exception if raise_on_load is not None.
        """
        if self.raise_on_load is not None:
            raise self.raise_on_load
        return self

    def ground_on_frame(
        self,
        frame: np.ndarray,
        prompt: str,
    ) -> list[tuple[BBox, float]]:
        """Return canned detections for a prompt on the given frame.

        Args:
            frame: ignored (test double does not process images)
            prompt: the prompt string (used as dict key in initial_detections)

        Returns:
            list of (BBox, score) tuples, or empty list if prompt not found.
        """
        return self.initial_detections.get(prompt, [])

    def propagate(
        self,
        *,
        frames: Any,  # Iterator[tuple[int, np.ndarray]]; Any for test flexibility
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        stride: int,
    ) -> Iterator[FramePropagationResult]:
        """Yield canned propagation results for each frame.

        Iterates over frames and yields canned FramePropagationResult
        for each. Raises raise_with when yielding raise_on_propagate_at_frame.

        Args:
            frames: Iterable of (frame_idx, frame_array) tuples. Ignored.
            prompts_with_initial_bbox: ignored
            stride: ignored

        Yields:
            FramePropagationResult for each frame in frames, in order.

        Raises:
            raise_with if raise_on_propagate_at_frame is set and matches
            the frame being yielded.
        """
        for frame_idx, _ in frames:
            if (
                self.raise_on_propagate_at_frame is not None
                and frame_idx == self.raise_on_propagate_at_frame
                and self.raise_with is not None
            ):
                raise self.raise_with

            detections = self.propagation_results.get(frame_idx, {})
            yield FramePropagationResult(frame=frame_idx, detections=detections)

    def close(self) -> None:
        """Close (clean up) the tracker. Idempotent.

        Multiple calls do not raise.
        """
        self._closed = True
