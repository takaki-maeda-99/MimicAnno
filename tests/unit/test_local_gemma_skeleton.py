"""LocalGemmaVLMLabeler constructor + model_identity — mock-based unit tests.

The real model load is tested in tests/test_phase2_real_vlm.py (env-gated)."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import LocalGemmaVLMLabeler

# ---------------------------------------------------------------------------
# Stub out torch so tests run without the heavy GPU dependency.
# _raise_classified does `import torch` at classification time; by injecting a
# fake module here we make torch.cuda.OutOfMemoryError available both in the
# test and inside _raise_classified.
# ---------------------------------------------------------------------------

class _FakeCudaOOMError(Exception):
    """Stand-in for torch.cuda.OutOfMemoryError."""


def _make_fake_torch() -> types.ModuleType:
    fake = types.ModuleType("torch")
    fake_cuda = types.ModuleType("torch.cuda")
    fake_cuda.OutOfMemoryError = _FakeCudaOOMError  # type: ignore[attr-defined]
    fake.cuda = fake_cuda  # type: ignore[attr-defined]
    return fake


_FAKE_TORCH = _make_fake_torch()
sys.modules.setdefault("torch", _FAKE_TORCH)
sys.modules.setdefault("torch.cuda", _FAKE_TORCH.cuda)

import torch  # type: ignore[import-untyped]  # noqa: E402  (fake module above)


def _cfg(**overrides) -> VLMConfig:
    return VLMConfig(
        model_id=overrides.get("model_id", "google/gemma-x"),
        resolved_checkpoint=overrides.get("resolved_checkpoint", "abc123" + "0" * 34),
        device=overrides.get("device", "cpu"),
        dtype=overrides.get("dtype", "bfloat16"),
    )


def _minimal_request(segment_id: str = "s_000"):
    import numpy as np

    from mimicanno.vlm_labeler import VLMRequest
    return VLMRequest(
        task_text="t", allowed_labels=["idle"], label_version="manipulation.v1",
        robot_type="aloha", fps=30.0, episode_duration_sec=1.0,
        segment_index=1, segment_total=1, segment_id=segment_id,
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0, "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.0, "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_constructor_calls_loader_with_resolved_revision(load_mock: MagicMock) -> None:
    load_mock.return_value = (MagicMock(), MagicMock())
    cfg = _cfg(model_id="google/gemma-x", resolved_checkpoint="b" * 40)
    LocalGemmaVLMLabeler(cfg)
    load_mock.assert_called_once_with(
        model_id="google/gemma-x", revision="b" * 40,
        device="cpu", dtype="bfloat16",
    )


def test_model_identity_uses_pre_flight_resolved_pair() -> None:
    with patch("mimicanno.vlm_labeler._hf_load_model_and_processor",
               return_value=(MagicMock(), MagicMock())):
        cfg = _cfg(model_id="google/gemma-x", resolved_checkpoint="d" * 40)
        lab = LocalGemmaVLMLabeler(cfg)
    mi = lab.model_identity()
    assert mi == {"vlm_model": "google/gemma-x", "vlm_checkpoint": "d" * 40}


def test_constructor_propagates_loader_exception_unwrapped() -> None:
    """Constructor failures bubble unchanged; label_run wraps them as
    vlm_init_failed (§2.3)."""
    boom = OSError("weights file missing")
    with patch("mimicanno.vlm_labeler._hf_load_model_and_processor",
               side_effect=boom), pytest.raises(OSError, match="weights file missing"):
        LocalGemmaVLMLabeler(_cfg())


def test_resolved_checkpoint_required() -> None:
    with pytest.raises(ValueError, match="resolved_checkpoint"):
        LocalGemmaVLMLabeler(VLMConfig(model_id="x", resolved_checkpoint=None))


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_classifies_cuda_oom(load_mock: MagicMock) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.side_effect = torch.cuda.OutOfMemoryError("CUDA OOM")
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)
    request = _minimal_request(segment_id="s_000")

    from mimicanno.vlm_labeler import LabelerRuntimeError
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(request, attempt=1)
    assert ei.value.reason == "cuda_oom"


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_classifies_timeout(load_mock: MagicMock) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.side_effect = TimeoutError("inference > timeout_sec")
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)

    from mimicanno.vlm_labeler import LabelerRuntimeError
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(_minimal_request(segment_id="s_000"), attempt=1)
    assert ei.value.reason == "inference_timeout"


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_returns_validated_response_on_clean_decode(
    load_mock: MagicMock,
) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.return_value = MagicMock()  # token ids
    processor.apply_chat_template.return_value = "<chat-template-string>"
    processor.batch_decode.return_value = [
        '{"phase": "idle", "vlm_confidence": 0.5}'
    ]
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)
    r = lab.label_segment(_minimal_request(segment_id="s_000"), attempt=1)
    assert r["phase"] == "idle"


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_includes_retry_amendment_on_attempt_2(
    load_mock: MagicMock,
) -> None:
    """Spec §3.3: when attempt > 1 and last_reject_reason is provided, the
    chat-template messages MUST include the retry-strict amendment in their
    text content."""
    import json as _json

    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    captured_messages: list[list[dict]] = []

    def _capture_template(messages, *, tokenize, add_generation_prompt):
        captured_messages.append(messages)
        return "<chat-template-string>"

    processor.apply_chat_template.side_effect = _capture_template

    def _capture(text, images, return_tensors):
        return MagicMock(to=lambda d: MagicMock())
    processor.side_effect = _capture
    model.generate.return_value = MagicMock()
    processor.batch_decode.return_value = [
        '{"phase": "idle", "vlm_confidence": 0.5}'
    ]
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)
    lab.label_segment(_minimal_request(segment_id="s_000"), attempt=2,
                      last_reject_reason="invalid_label")
    # Walk the messages list and concat all text-block content.
    assert captured_messages, "apply_chat_template never called"
    flattened = _json.dumps(captured_messages[0])
    assert "reject_reason=invalid_label" in flattened
