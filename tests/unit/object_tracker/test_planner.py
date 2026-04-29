"""Tests for LocalGemmaTrackingPlanner.extract_entities (Task 15, spec §2.2.1).

Covers:
1. Happy path — valid JSON → correct EntityPlan.
2. Parse failure → retry → success (2 calls, correct result).
3. All 3 attempts fail → empty EntityPlan.
4. Duplicate within role → reject_reason="duplicate_prompt_within_role" + retry.
5. Cross-role duplicates allowed.
6. shared_handle() identity — same Python objects as labeler internals.
7. attempt_max=1 short-circuits on parse failure.
8. Retry prompt contains amendment text.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import numpy as np

from mimicanno.config import VLMConfig
from mimicanno.labelset import Label, LabelSet
from mimicanno.object_tracker.planner import (
    EntityPlan,
    LocalGemmaTrackingPlanner,
    _build_planner_prompt,
)
from mimicanno.vlm_labeler import GemmaHandle, LocalGemmaVLMLabeler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRAME = np.zeros((4, 4, 3), dtype=np.uint8)


def _make_handle(model: Any = None, processor: Any = None) -> GemmaHandle:
    cfg = VLMConfig(
        model_id="test/gemma",
        resolved_checkpoint="abc123",
        device="cpu",
        temperature=1.0,
        max_output_tokens=128,
        timeout_sec=5.0,
    )
    return GemmaHandle(
        model=model or mock.MagicMock(),
        processor=processor or mock.MagicMock(),
        config=cfg,
    )


def _make_label_set(label_ids: list[str] | None = None) -> LabelSet:
    ids = label_ids or ["pick_object", "place_object", "transport"]
    return LabelSet(
        schema_version="manipulation.v1",
        task_type="manipulation",
        labels=[Label(id=lid, verbs=[], requires_object=False) for lid in ids],
        unknown_task_fallback=None,
        path=mock.MagicMock(),
        sha256="sha256:test",
    )


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_happy_path() -> None:
    handle = _make_handle()
    raw_json = '{"objects": ["red block"], "targets": ["bin A"], "tools": ["gripper"]}'

    with mock.patch(
        "mimicanno.object_tracker.planner._call_gemma", return_value=raw_json
    ):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="put the red block in bin A",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    assert plan == EntityPlan(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
    )


# ---------------------------------------------------------------------------
# 2. Parse failure → retry → success
# ---------------------------------------------------------------------------

def test_parse_failure_retry_success() -> None:
    handle = _make_handle()
    responses = ["NOT JSON!!!", '{"objects": ["cube"], "targets": [], "tools": []}']
    call_count = 0

    def fake_call(h: Any, prompt: str, frame: Any) -> str:
        nonlocal call_count
        call_count += 1
        return responses[call_count - 1]

    with mock.patch("mimicanno.object_tracker.planner._call_gemma", side_effect=fake_call):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="pick the cube",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    assert call_count == 2
    assert plan == EntityPlan(
        object_prompts=["cube"],
        target_prompts=[],
        tool_prompts=[],
    )


# ---------------------------------------------------------------------------
# 3. All 3 attempts fail → empty EntityPlan
# ---------------------------------------------------------------------------

def test_all_attempts_fail_returns_empty() -> None:
    handle = _make_handle()

    with mock.patch(
        "mimicanno.object_tracker.planner._call_gemma", return_value="garbage"
    ):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
            attempt_max=3,
        )

    assert plan == EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])


# ---------------------------------------------------------------------------
# 4. Duplicate within role → retry with stricter amendment
# ---------------------------------------------------------------------------

def test_duplicate_within_role_retries() -> None:
    handle = _make_handle()
    # attempt 1: case-insensitive dup; attempt 2: clean
    responses = [
        '{"objects": ["red block", "Red Block"], "targets": [], "tools": []}',
        '{"objects": ["red block"], "targets": [], "tools": []}',
    ]
    call_count = 0
    captured_prompts: list[str] = []

    def fake_call(h: Any, prompt: str, frame: Any) -> str:
        nonlocal call_count
        call_count += 1
        captured_prompts.append(prompt)
        return responses[call_count - 1]

    with mock.patch("mimicanno.object_tracker.planner._call_gemma", side_effect=fake_call):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    assert call_count == 2
    assert plan.object_prompts == ["red block"]
    # Second prompt should contain the amendment text for duplicate_prompt_within_role
    assert "duplicate" in captured_prompts[1].lower()


# ---------------------------------------------------------------------------
# 5. Cross-role duplicates allowed
# ---------------------------------------------------------------------------

def test_cross_role_duplicates_allowed() -> None:
    handle = _make_handle()
    raw_json = (
        '{"objects": ["red block"], "targets": ["red block"], "tools": []}'
    )

    with mock.patch(
        "mimicanno.object_tracker.planner._call_gemma", return_value=raw_json
    ):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    assert plan.object_prompts == ["red block"]
    assert plan.target_prompts == ["red block"]
    assert plan.tool_prompts == []


def test_empty_objects_collapses_to_all_empty_sentinel() -> None:
    """Spec §2.2.1: empty `objects` returns EntityPlan([], [], []) even when
    targets/tools are populated, so the caller's `object_prompts == []`
    degrade trigger fires uniformly."""
    handle = _make_handle()
    raw_json = '{"objects": [], "targets": ["bin A"], "tools": ["gripper"]}'

    with mock.patch(
        "mimicanno.object_tracker.planner._call_gemma", return_value=raw_json
    ):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    assert plan.object_prompts == []
    assert plan.target_prompts == []
    assert plan.tool_prompts == []


# ---------------------------------------------------------------------------
# 6. shared_handle() identity
# ---------------------------------------------------------------------------

def test_shared_handle_identity() -> None:
    """GemmaHandle holds references to the same objects as the labeler."""
    config = VLMConfig(
        model_id="test/gemma",
        resolved_checkpoint="abc123",
        device="cpu",
    )
    fake_model = object()
    fake_processor = object()

    with mock.patch(
        "mimicanno.vlm_labeler._hf_load_model_and_processor",
        return_value=(fake_model, fake_processor),
    ):
        labeler = LocalGemmaVLMLabeler(config)

    handle = labeler.shared_handle()

    assert id(handle.model) == id(labeler._model)
    assert id(handle.processor) == id(labeler._processor)
    assert id(handle.config) == id(labeler._config)

    # Planner constructed with handle doesn't load a new model
    planner = LocalGemmaTrackingPlanner(handle)
    assert id(planner._handle.model) == id(labeler._model)


# ---------------------------------------------------------------------------
# 7. attempt_max=1 short-circuits
# ---------------------------------------------------------------------------

def test_attempt_max_1_short_circuits() -> None:
    handle = _make_handle()
    call_count = 0

    def fake_call(h: Any, prompt: str, frame: Any) -> str:
        nonlocal call_count
        call_count += 1
        return "not json"

    with mock.patch("mimicanno.object_tracker.planner._call_gemma", side_effect=fake_call):
        planner = LocalGemmaTrackingPlanner(handle)
        plan = planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
            attempt_max=1,
        )

    assert call_count == 1
    assert plan == EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])


# ---------------------------------------------------------------------------
# 8. Retry prompt contains amendment text
# ---------------------------------------------------------------------------

def test_retry_prompt_contains_amendment() -> None:
    handle = _make_handle()
    responses = [
        "garbage",  # attempt 1 → json_parse_error
        '{"objects": ["x"], "targets": [], "tools": []}',  # attempt 2 success
    ]
    call_count = 0
    captured_prompts: list[str] = []

    def fake_call(h: Any, prompt: str, frame: Any) -> str:
        nonlocal call_count
        call_count += 1
        captured_prompts.append(prompt)
        return responses[call_count - 1]

    with mock.patch("mimicanno.object_tracker.planner._call_gemma", side_effect=fake_call):
        planner = LocalGemmaTrackingPlanner(handle)
        planner.extract_entities(
            task_text="task",
            initial_frame=_FRAME,
            allowed_labels=_make_label_set(),
        )

    # First prompt should have no amendment
    assert "rejected" not in captured_prompts[0]
    # Second prompt should contain the json_parse_error amendment
    assert "json_parse_error" in captured_prompts[1]
    assert "Re-emit" in captured_prompts[1]


# ---------------------------------------------------------------------------
# 9. Prompt includes place-label hint
# ---------------------------------------------------------------------------

def test_prompt_includes_place_hint() -> None:
    labels_with_place = _make_label_set(["pick_object", "place_object"])
    labels_without_place = _make_label_set(["pick_object", "transport"])

    prompt_with = _build_planner_prompt("task", labels_with_place, None)
    prompt_without = _build_planner_prompt("task", labels_without_place, None)

    assert "place" in prompt_with.lower()
    # place_* hint present
    assert "targets likely exist" in prompt_with
    # no place labels hint
    assert "targets may be empty" in prompt_without
