"""Test fixtures — FixtureTrackingPlanner + FixtureSAM3Tracker (spec §2.6).

These fixtures provide no-GPU, no-model-weights test doubles for the core
tracking loop. They support canned happy-path returns and configurable
failure injection (e.g., raise on first call, raise at a specific frame).

FramePropagationResult is defined in sam3_runtime (production owner) and
re-exported here for backwards compatibility.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import BBox
from mimicanno.object_tracker.sam3_runtime import FramePropagationResult

__all__ = ["FixtureSAM3Tracker", "FixtureTrackingPlanner", "FramePropagationResult"]


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
        initial_detections_by_frame: dict[
            int, dict[str, list[tuple[BBox, float]]]
        ] | None = None,
        propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] | None = None,
        raise_on_load: Exception | None = None,
        raise_on_propagate_at_frame: int | None = None,
        raise_with: Exception | None = None,
    ) -> None:
        self.initial_detections = initial_detections or {}
        self.initial_detections_by_frame = initial_detections_by_frame or {}
        self.propagation_results = propagation_results or {}
        self.raise_on_load = raise_on_load
        self.raise_on_propagate_at_frame = raise_on_propagate_at_frame
        self.raise_with = raise_with
        self._closed = False
        self._propagate_call_count: int = 0
        self.last_anchor_frame_index: int = 0
        self.last_propagation_direction: str = "forward"

    @property
    def propagate_call_count(self) -> int:
        """Number of times propagate() has been called. Used in tests to verify
        the single-call contract (spec §2.4.1 step 2)."""
        return self._propagate_call_count

    def load(
        self,
        *,
        checkpoint: object = None,
        device: object = "cpu",
    ) -> FixtureSAM3Tracker:
        """Load (initialize) the tracker.

        Accepts checkpoint and device kwargs to match SAM3Runtime.load signature
        for drop-in test substitution (kwargs are silently ignored).

        Raises the configured exception if raise_on_load was set in __init__.

        Args:
            checkpoint: ignored (for SAM3Runtime compatibility)
            device: ignored (for SAM3Runtime compatibility)

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
        *,
        frame_index: int | None = None,
    ) -> list[tuple[BBox, float]]:
        """Return canned detections for a prompt on the given frame.

        When ``frame_index`` is provided and ``initial_detections_by_frame``
        has an entry for that frame, look up there. Otherwise fall back to
        the legacy ``initial_detections`` dict (treated as frame-agnostic).

        Args:
            frame: ignored (test double does not process images)
            prompt: the prompt string (used as dict key)
            frame_index: optional; if provided, look up by frame

        Returns:
            list of (BBox, score) tuples, or empty list if not found.
        """
        if frame_index is not None and self.initial_detections_by_frame:
            return self.initial_detections_by_frame.get(frame_index, {}).get(
                prompt, []
            )
        return self.initial_detections.get(prompt, [])

    def propagate(  # type: ignore[override]
        self,
        *,
        video_path: Path,
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        expected_frames: set[int],
        mask_size_hw: tuple[int, int] | None = None,
        anchor_frame_index: int = 0,  # accepted, recorded for assertions
        propagation_direction: str = "forward",  # accepted, recorded
    ) -> Iterator[FramePropagationResult]:
        """Yield canned propagation results for each frame in expected_frames.

        New shape (2026-05-04): the real ``SAM3Runtime.propagate`` no longer
        consumes a frames iterator — sam3's session-based predictor reads the
        video itself from ``video_path``. The fixture mirrors this contract:
        ``video_path`` is ignored (no real I/O), and ``expected_frames`` drives
        which frames are yielded.

        Args:
            video_path: ignored (test double does not read images).
            prompts_with_initial_bbox: ignored (canned per-frame results are
                supplied via ``propagation_results`` at construction time).
            expected_frames: integer frame indices to yield, in ascending
                order. Frames not present in ``propagation_results`` yield an
                empty detection dict.

        Yields:
            FramePropagationResult for each frame in ``sorted(expected_frames)``.

        Raises:
            ``raise_with`` if ``raise_on_propagate_at_frame`` matches a frame
            *that would otherwise have been yielded*. Frames outside
            ``expected_frames`` cannot trigger the raise — keeping the failure
            point predictable for tests.
        """
        self._propagate_call_count += 1
        # Record for test assertions
        self.last_anchor_frame_index = anchor_frame_index
        self.last_propagation_direction = propagation_direction
        # documentation; not used. mask_size_hw is accepted to keep the
        # fixture signature in lock-step with SAM3Runtime — tests that
        # exercise mask collection should construct masks directly via
        # ``propagation_masks`` (none for now).
        del video_path, prompts_with_initial_bbox, mask_size_hw
        for frame_idx in sorted(expected_frames):
            if (
                self.raise_on_propagate_at_frame is not None
                and frame_idx == self.raise_on_propagate_at_frame
                and self.raise_with is not None
            ):
                raise self.raise_with

            detections = self.propagation_results.get(frame_idx, {})
            # Fixture default: no masks. Task 5+ pipeline tests that need
            # masks should construct FramePropagationResult directly via
            # `make_test_propagation_result` instead of going through this
            # fixture.
            masks: dict[str, np.ndarray | None] = {p: None for p in detections}
            yield FramePropagationResult(
                frame=frame_idx, detections=detections, masks=masks,
            )

    def close(self) -> None:
        """Close (clean up) the tracker. Idempotent.

        Multiple calls do not raise.
        """
        self._closed = True
