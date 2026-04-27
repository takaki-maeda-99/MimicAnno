"""LocalGemmaVLMLabeler constructor + model_identity — mock-based unit tests.

The real model load is tested in tests/test_phase2_real_vlm.py (env-gated)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import LocalGemmaVLMLabeler


def _cfg(**overrides) -> VLMConfig:
    return VLMConfig(
        model_id=overrides.get("model_id", "google/gemma-x"),
        resolved_checkpoint=overrides.get("resolved_checkpoint", "abc123" + "0" * 34),
        device=overrides.get("device", "cpu"),
        dtype=overrides.get("dtype", "bfloat16"),
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
               side_effect=boom):
        with pytest.raises(OSError, match="weights file missing"):
            LocalGemmaVLMLabeler(_cfg())


def test_resolved_checkpoint_required() -> None:
    with pytest.raises(ValueError, match="resolved_checkpoint"):
        LocalGemmaVLMLabeler(VLMConfig(model_id="x", resolved_checkpoint=None))
