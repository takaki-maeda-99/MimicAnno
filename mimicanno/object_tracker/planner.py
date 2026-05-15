"""Phase 3 entity-extraction Step A — planner Protocol + EntityPlan dataclass
+ LocalGemmaTrackingPlanner over a shared Gemma handle (spec §2.2)."""

from __future__ import annotations

import contextlib
import json
import signal
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Literal, Protocol, get_args

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.track_id import ROLE
from mimicanno.vlm_labeler import GemmaHandle, _strip_markdown_fences


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

class _PlannerLabelerError(Exception):
    """Local planner parse/schema failure — retry-eligible. Does NOT extend
    LabelerError (Phase 2 hash invariant must stay closed)."""

    def __init__(self, reject_reason: str) -> None:
        super().__init__(f"Planner output rejected: {reject_reason}")
        self.reject_reason: str = reject_reason


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
        "Identify all objects that need to be tracked. Use visually descriptive "
        "noun phrases optimised for an open-vocabulary segmentation model "
        "(include colour, material, or shape when helpful for visual grounding "
        "— e.g. 'yellow tape', 'transparent plastic bottle', 'robotic claw' or "
        "'metal end effector' instead of just 'gripper'). Respond with ONE JSON "
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
    """Call the Gemma model with the given prompt and frame image.

    Runtime faults (CUDA OOM, device errors, etc.) propagate unwrapped — the
    orchestrator (Task 19) classifies them. Only inference-level `TimeoutError`
    is translated to a retry-eligible ``_PlannerLabelerError("timeout")``,
    matching Phase 2's `LocalGemmaVLMLabeler.label_segment` separation between
    `LabelerError` (retry-eligible) and `LabelerRuntimeError` (not).

    NOTE(Task 19): timeouts are retry-eligible HERE but Phase 2 maps the same
    `TimeoutError` to a runtime fault (not retry-eligible). Task 19 must wrap
    this call in a `_raise_classified`-equivalent so non-timeout torch/HF
    errors get the same `LabelerRuntimeError("cuda_oom" / "device_unavailable" /
    "model_unreachable")` shape as Phase 2 callers downstream.
    """
    from PIL import Image

    pil_image = Image.fromarray(frame)
    try:
        # Use apply_chat_template so the processor inserts the correct
        # number of <image> placeholder tokens for transformers 5.x Gemma 4
        # (which otherwise raises "Image features and image tokens do not
        # match"). Mirrors LocalGemmaVLMLabeler.label_segment's path.
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": pil_image},
                {"type": "text", "text": prompt},
            ],
        }]
        templated = handle.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = handle.processor(
            text=templated, images=[pil_image], return_tensors="pt"
        ).to(handle.config.device)
        input_len = inputs["input_ids"].shape[1]
        with _timeout_guard(handle.config.timeout_sec):
            tokens = handle.model.generate(
                **inputs,
                do_sample=False,
                temperature=handle.config.temperature,
                max_new_tokens=handle.config.max_output_tokens,
            )
        # Slice off the input prompt before decoding — Gemma 4's chat-template
        # output prepends the templated prompt verbatim, which breaks the
        # `json.loads(text)` step in `_parse_planner_response`. Mirrors
        # `LocalGemmaVLMLabeler.label_segment`.
        generated_only = tokens[:, input_len:]
        decoded: str = handle.processor.batch_decode(
            generated_only, skip_special_tokens=True
        )[0]
    except TimeoutError:
        raise _PlannerLabelerError("timeout") from None

    if decoded.startswith(prompt):
        decoded = decoded[len(prompt):]
    _maybe_dump_planner_io(prompt, decoded, frame)
    return decoded.strip()


def _maybe_dump_planner_io(prompt: str, decoded: str, frame: np.ndarray) -> None:
    import os
    dump_root = os.environ.get("MIMICANNO_VLM_DUMP_DIR")
    if not dump_root:
        return
    from PIL import Image
    out = Path(dump_root) / "_planner"
    out.mkdir(parents=True, exist_ok=True)
    n = len(list(out.glob("call_*")))
    call_dir = out / f"call_{n:03d}"
    call_dir.mkdir(parents=True, exist_ok=True)
    (call_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (call_dir / "response.txt").write_text(decoded, encoding="utf-8")
    Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(call_dir / "frame.png")


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
            except _PlannerLabelerError as e:
                last_reject = e.reject_reason
                continue
            # Spec §2.2.1: empty `objects` collapses to the all-empty sentinel
            # so caller's `object_prompts == []` check uniformly triggers the
            # §7.2 gemma_no_object_prompts degrade regardless of whether
            # targets/tools came back populated.
            if not plan.object_prompts:
                return EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])
            return plan
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
