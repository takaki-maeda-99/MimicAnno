"""FixtureVLMLabeler scenario replay tests (spec §5.5)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelerError,
    LabelerRuntimeError,
    VLMRequest,
)

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _req(segment_index: int = 1) -> VLMRequest:
    return VLMRequest(
        task_text="t", allowed_labels=["idle", "approach_object", "grasp_object"],
        label_version="manipulation.v1", robot_type="aloha", fps=30.0,
        episode_duration_sec=10.0, segment_index=segment_index, segment_total=8,
        segment_id="s_000",
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0, "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.5, "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )


def test_ok_first_try() -> None:
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    req = _req()
    req["segment_id"] = "s_000"
    r = lab.label_segment(req, attempt=1)
    assert r["phase"] == "approach_object"


def test_retry_then_ok_first_attempt_raises_then_succeeds() -> None:
    lab = FixtureVLMLabeler(FIXT / "retry_then_ok.json")
    req = _req(); req["segment_id"] = "s_001"
    with pytest.raises(LabelerError) as ei:
        lab.label_segment(req, attempt=1)
    assert ei.value.reject_reason == "json_parse_error"
    with pytest.raises(LabelerError) as ei:
        lab.label_segment(req, attempt=2, last_reject_reason="json_parse_error")
    assert ei.value.reject_reason == "invalid_label"
    r = lab.label_segment(req, attempt=3, last_reject_reason="invalid_label")
    assert r["phase"] == "grasp_object"


def test_fallback_unknown_three_attempts_all_raise() -> None:
    lab = FixtureVLMLabeler(FIXT / "fallback_unknown.json")
    req = _req(); req["segment_id"] = "s_002"
    for attempt in (1, 2, 3):
        with pytest.raises(LabelerError):
            lab.label_segment(req, attempt=attempt)


def test_runtime_oom_raises_labeler_runtime_error() -> None:
    lab = FixtureVLMLabeler(FIXT / "runtime_oom.json")
    req = _req(); req["segment_id"] = "s_007"
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(req, attempt=1)
    assert ei.value.reason == "cuda_oom"


def test_init_should_raise_makes_constructor_fail() -> None:
    with pytest.raises(RuntimeError):
        FixtureVLMLabeler(FIXT / "init_should_raise.json")


def test_model_identity_uses_file_sha256() -> None:
    """Spec §5.5: vlm_checkpoint = sha256 of fixture file content."""
    import hashlib
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    expected = hashlib.sha256((FIXT / "ok_first_try.json").read_bytes()).hexdigest()
    assert lab.model_identity()["vlm_checkpoint"] == expected
    assert lab.model_identity()["vlm_model"] == "fixture"


def test_wildcard_segment_match() -> None:
    """Star-key '*' applies to any segment_id not explicitly listed."""
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    req = _req(); req["segment_id"] = "any_segment_id_at_all"
    r = lab.label_segment(req, attempt=1)
    assert r["phase"] == "approach_object"
