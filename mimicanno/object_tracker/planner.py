"""Phase 3 entity-extraction Step A — planner Protocol + EntityPlan dataclass
(spec §2.2). LocalGemmaTrackingPlanner is implemented in Task 15;
this file lands the dataclass + Protocol stub so downstream tasks can import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.track_id import ROLE


@dataclass(slots=True, frozen=True)
class EntityPlan:
    """Step A output. No SAM3 contact yet (spec §2.2)."""

    object_prompts: list[str]
    target_prompts: list[str]
    tool_prompts: list[str]

    def all_prompts_with_role(self) -> list[tuple[ROLE, str]]:
        """Stable ordering: objects, then targets, then tools; within each
        role, original order from Gemma. Used by Step B grounding to walk
        the full prompt set."""
        out: list[tuple[ROLE, str]] = []
        for prompt in self.object_prompts:
            out.append(("object", prompt))
        for prompt in self.target_prompts:
            out.append(("target", prompt))
        for prompt in self.tool_prompts:
            out.append(("tool", prompt))
        return out


class TrackingPlanner(Protocol):
    """Step A planner Protocol (spec §2.2)."""

    def extract_entities(
        self,
        *,
        task_text: str,
        initial_frame: np.ndarray,
        allowed_labels: LabelSet,
        attempt_max: int = 3,
    ) -> EntityPlan: ...
