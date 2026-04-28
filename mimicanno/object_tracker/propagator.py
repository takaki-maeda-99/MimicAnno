"""Phase 3 propagator dataclasses (spec §2.4).

Step B (`ground_initial_detections`) lands in Task 16; Step C (`Propagator.run`)
lands in Task 8. This file holds the dataclasses they share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.track_id import ROLE

GapReason = Literal["sam3_lost", "sam3_low_conf"]


@dataclass(slots=True, frozen=True)
class BBox:
    """Normalized image coords (spec §2.4). (0,0) = top-left, (1,1) = bottom-right.
    All four floats in [0, 1]; w > 0; h > 0; x + w <= 1; y + h <= 1."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        if self.w <= 0.0 or self.h <= 0.0:
            raise ValueError(
                f"BBox w/h must be > 0; got w={self.w}, h={self.h}"
            )
        if not (self.x >= 0.0 and self.x + self.w <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox x out of unit square; x={self.x}, w={self.w}"
            )
        if not (self.y >= 0.0 and self.y + self.h <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox y out of unit square; y={self.y}, h={self.h}"
            )

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def iou(self, other: BBox) -> float:
        """Intersection-over-union in normalized image coords."""
        ix0 = max(self.x, other.x)
        iy0 = max(self.y, other.y)
        ix1 = min(self.x + self.w, other.x + other.w)
        iy1 = min(self.y + self.h, other.y + other.h)
        iw = max(0.0, ix1 - ix0)
        ih = max(0.0, iy1 - iy0)
        inter = iw * ih
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0.0 else 0.0


@dataclass(slots=True, frozen=True)
class TrackSample:
    """One sub-sampled propagation result for a single track (spec §2.4)."""

    frame: int
    time_sec: float
    bbox: BBox
    score: float


@dataclass(slots=True, frozen=True)
class GapEvent:
    """Contiguous frame range where the bbox is invalid / missing (spec §2.4).

    Re-acquisition is implicit (the next sample after a gap), NOT recorded
    here. Mixing range semantics with point semantics ('this single frame
    was a track event') would conflict with `compute_object_signals`'
    'NaN inside gap_events' rule (spec §2.5).
    """

    from_frame: int
    to_frame: int
    reason: GapReason


@dataclass(slots=True)
class Track:
    """One propagated track for one (role, prompt) seed (spec §2.4)."""

    track_id: str
    role: ROLE
    prompt: str
    slug: str
    index: int
    primary: bool
    samples: list[TrackSample] = field(default_factory=list)
    gap_events: list[GapEvent] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class TrackingPlan:
    """Step A + Step B combined; consumed by Propagator.run (spec §2.4.0)."""

    entities: EntityPlan
    initial_detections: dict[tuple[ROLE, str], BBox]
    failed_prompts: list[tuple[ROLE, str]]
