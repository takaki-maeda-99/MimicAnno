"""Phase 3 entity-extraction Step A — planner Protocol + EntityPlan dataclass
(spec §2.2). LocalGemmaTrackingPlanner is implemented in Task 15;
this file lands the dataclass + Protocol stub so downstream tasks can import."""

from __future__ import annotations

import contextlib
import json
import re
import signal
from collections.abc import Iterator
from dataclasses import dataclass
from types import FrameType
from typing import Literal, Protocol, get_args

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.track_id import ROLE
from mimicanno.vlm_labeler import GemmaHandle


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


# ---------------------------------------------------------------------------
# LocalGemmaTrackingPlanner (spec §2.2.1, Task 15)
# ---------------------------------------------------------------------------

PlannerRejectReason = Literal[
    "json_parse_error",
    "schema_violation",
    "duplicate_prompt_within_role",
    "timeout",
]
_PLANNER_REJECT_REASONS: tuple[str, ...] = get_args(PlannerRejectReason)

_PLANNER_REJECT_AMENDMENT_BY_REASON: dict[str, str] = {
    "json_parse_error": (
        "Re-emit the JSON object only. No prose, no markdown fences."
    ),
    "schema_violation": (
        'All required fields MUST be present: "objects": [string], '
        '"targets": [string], "tools": [string].'
    ),
    "duplicate_prompt_within_role": (
        "Each role list MUST contain unique strings (case-insensitive). "
        "Remove duplicate entries within objects, targets, and tools."
    ),
    "timeout": "",  # no copy change; just retry
}
assert set(_PLANNER_REJECT_AMENDMENT_BY_REASON) == set(_PLANNER_REJECT_REASONS), (
    "_PLANNER_REJECT_AMENDMENT_BY_REASON keys must match PlannerRejectReason exhaustively"
)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


class _PlannerLabelerError(Exception):
    """Local planner parse/schema failure — retry-eligible. Does NOT extend
    LabelerError (Phase 2 hash invariant must stay closed)."""

    def __init__(self, reject_reason: str) -> None:
        super().__init__(f"Planner output rejected: {reject_reason}")
        self.reject_reason: str = reject_reason


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def _build_planner_prompt(
    task_text: str,
    allowed_labels: LabelSet,
    last_reject_reason: str | None,
) -> str:
    """Build the Step A prompt for entity extraction."""
    label_ids = sorted(allowed_labels.label_ids())
    has_place = any(lid.startswith("place") for lid in label_ids)
    place_hint = (
        " (labels include 'place_*' — targets likely exist)"
        if has_place
        else " (no 'place_*' labels — targets may be empty)"
    )

    body = (
        "SYSTEM:\n"
        "You are identifying objects for a robot manipulation task.\n"
        f'Task instruction: "{task_text}"\n'
        f"Allowed phase labels: {', '.join(label_ids)}{place_hint}\n"
        "\n"
        "USER:\n"
        "[FRAME]\n"
        "\n"
        "Identify all objects that need to be tracked. Respond with ONE JSON "
        "object, no prose, no markdown fences:\n"
        "{\n"
        '  "objects": ["<object to manipulate>", ...],\n'
        '  "targets": ["<placement target>", ...],\n'
        '  "tools":   ["<tool used by robot>", ...]\n'
        "}\n"
        "Use empty lists for roles with no relevant entities.\n"
        "Within each list, all entries must be unique (case-insensitive).\n"
    )

    if last_reject_reason and _PLANNER_REJECT_AMENDMENT_BY_REASON.get(last_reject_reason):
        body += (
            "\n"
            f"Your previous response was rejected: reject_reason={last_reject_reason}.\n"
            f"{_PLANNER_REJECT_AMENDMENT_BY_REASON[last_reject_reason]}\n"
            "Re-emit the JSON object exactly per the schema.\n"
        )
    return body


def _timeout_guard(timeout_sec: float) -> contextlib.AbstractContextManager[None]:
    @contextlib.contextmanager
    def _gm() -> Iterator[None]:
        def _handler(signum: int, frame: FrameType | None) -> None:
            raise TimeoutError(f"inference exceeded {timeout_sec}s")

        old = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_sec)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)

    return _gm()


def _call_gemma(handle: GemmaHandle, prompt: str, frame: np.ndarray) -> str:
    """Call the Gemma model with the given prompt and frame image."""
    from PIL import Image

    pil_image = Image.fromarray(frame)
    try:
        inputs = handle.processor(
            text=prompt, images=[pil_image], return_tensors="pt"
        ).to(handle.config.device)
        with _timeout_guard(handle.config.timeout_sec):
            tokens = handle.model.generate(
                **inputs,
                do_sample=False,
                temperature=handle.config.temperature,
                max_new_tokens=handle.config.max_output_tokens,
            )
        decoded: str = handle.processor.batch_decode(
            tokens, skip_special_tokens=True
        )[0]
    except TimeoutError:
        raise _PlannerLabelerError("timeout") from None
    except Exception as e:
        raise _PlannerLabelerError("json_parse_error") from e

    if decoded.startswith(prompt):
        decoded = decoded[len(prompt):]
    return decoded.strip()


def _parse_planner_response(raw: str) -> EntityPlan:
    """Parse and validate Gemma's JSON response into an EntityPlan."""
    text = _strip_markdown_fences(raw)

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise _PlannerLabelerError("json_parse_error") from e

    if not isinstance(obj, dict):
        raise _PlannerLabelerError("schema_violation")

    for role in ("objects", "targets", "tools"):
        if role not in obj or not isinstance(obj[role], list):
            raise _PlannerLabelerError("schema_violation")
        for item in obj[role]:
            if not isinstance(item, str):
                raise _PlannerLabelerError("schema_violation")

    # Within-role case-insensitive dedup check
    for role in ("objects", "targets", "tools"):
        seen: set[str] = set()
        for item in obj[role]:
            lower = item.lower()
            if lower in seen:
                raise _PlannerLabelerError("duplicate_prompt_within_role")
            seen.add(lower)

    return EntityPlan(
        object_prompts=list(obj["objects"]),
        target_prompts=list(obj["targets"]),
        tool_prompts=list(obj["tools"]),
    )


class LocalGemmaTrackingPlanner:
    """Step A entity-extraction over a shared Gemma handle (spec §2.2.1).

    Does not load its own model — constructed with a GemmaHandle returned
    by ``LocalGemmaVLMLabeler.shared_handle()``.
    """

    def __init__(self, gemma_handle: GemmaHandle) -> None:
        self._handle = gemma_handle

    def extract_entities(
        self,
        *,
        task_text: str,
        initial_frame: np.ndarray,
        allowed_labels: LabelSet,
        attempt_max: int = 3,
    ) -> EntityPlan:
        """Extract objects/targets/tools from task_text + initial_frame.

        On terminal failure (all attempt_max attempts fail) or if objects
        list is empty, returns EntityPlan([], [], []) — caller interprets
        object_prompts==[] as the §7.2 gemma_no_object_prompts degrade.
        """
        last_reject: str | None = None
        for _attempt in range(1, attempt_max + 1):
            prompt = _build_planner_prompt(task_text, allowed_labels, last_reject)
            try:
                raw = _call_gemma(self._handle, prompt, initial_frame)
                plan = _parse_planner_response(raw)
                return plan
            except _PlannerLabelerError as e:
                last_reject = e.reject_reason
                continue
        return EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])


# Re-export GemmaHandle so importers can get it from planner without reaching
# into vlm_labeler directly (optional convenience; vlm_labeler is canonical).
__all__ = [
    "EntityPlan",
    "GemmaHandle",
    "LocalGemmaTrackingPlanner",
    "PlannerRejectReason",
    "TrackingPlanner",
]
