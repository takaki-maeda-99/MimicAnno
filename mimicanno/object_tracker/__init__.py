"""Object tracking module — orchestration, fixtures, and shared types."""

from mimicanno.object_tracker.propagator import (
    ground_initial_detections,
)
from mimicanno.object_tracker.sam3_runtime import FramePropagationResult, SAM3Runtime

__all__ = ["FramePropagationResult", "SAM3Runtime", "ground_initial_detections"]
