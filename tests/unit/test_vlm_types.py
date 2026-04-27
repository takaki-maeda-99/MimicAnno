"""VLMLabeler protocol surface — exception classes, enums, dataclasses.

We do NOT test the protocol class itself (it's structural); we test that
the concrete error/enum/dataclass surface matches spec §2.1 + §2.3.
"""
from __future__ import annotations

import pytest

from mimicanno.vlm_labeler import (
    LabelAttempt,
    LabelerError,
    LabelerRuntimeError,
    ModelIdentity,
    REJECT_REASONS,
    RUNTIME_FAULT_REASONS,
    RunOutcome,
    VLMResponse,
)


def test_reject_reasons_exhaustive() -> None:
    assert set(REJECT_REASONS) == {
        "json_parse_error",
        "schema_violation",
        "invalid_label",
        "out_of_range_confidence",
        "timeout",
    }


def test_runtime_fault_reasons_exhaustive() -> None:
    assert set(RUNTIME_FAULT_REASONS) == {
        "model_unreachable",
        "device_unavailable",
        "cuda_oom",
        "inference_timeout",
    }


def test_labeler_error_carries_reject_reason() -> None:
    e = LabelerError(reject_reason="invalid_label")
    assert e.reject_reason == "invalid_label"


def test_labeler_runtime_error_carries_reason() -> None:
    e = LabelerRuntimeError(reason="cuda_oom")
    assert e.reason == "cuda_oom"


def test_label_attempt_default_construction() -> None:
    resp = VLMResponse(phase="idle", verb=None, object=None, target=None,
                       vlm_confidence=0.5, evidence=None)
    a = LabelAttempt(
        segment_id="s_001",
        attempt_count=1,
        final_status="ok",
        reject_reasons=[],
        runtime_errors=[],
        response=resp,
    )
    assert a.final_status == "ok"


def test_run_outcome_ok_has_no_degrade_reason() -> None:
    o = RunOutcome(kind="ok", degrade_reason=None, underlying_error=None)
    assert o.kind == "ok"
    assert o.degrade_reason is None


def test_run_outcome_degraded_with_reason() -> None:
    o = RunOutcome(
        kind="degraded",
        degrade_reason="vlm_init_failed",
        underlying_error="OSError(...)",
    )
    assert o.kind == "degraded"


def test_model_identity_shape() -> None:
    m = ModelIdentity(vlm_model="x", vlm_checkpoint="y")
    assert m["vlm_model"] == "x"
    assert m["vlm_checkpoint"] == "y"
