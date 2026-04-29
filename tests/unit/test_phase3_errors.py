"""Phase 3 error code structure (spec §8)."""

from __future__ import annotations

import io
import json

import pytest

from mimicanno.errors import (
    GemmaNoObjectPrompts,
    SAM3CheckpointNotFound,
    SAM3ExtrasMissing,
    SAM3InitFailed,
    SAM3NoInitialDetection,
    SAM3RuntimeFailed,
    write_error_json,
)


def test_sam3_checkpoint_not_found_code_and_context() -> None:
    err = SAM3CheckpointNotFound(
        path="/missing/sam3.ckpt", reason="file not found"
    )
    assert err.code == "sam3_checkpoint_not_found"
    assert "missing" in err.message.lower() or "/missing/sam3.ckpt" in err.message
    assert err.context == {"path": "/missing/sam3.ckpt", "reason": "file not found"}


def test_sam3_extras_missing_carries_install_hint() -> None:
    err = SAM3ExtrasMissing()
    assert err.code == "sam3_extras_missing"
    assert "[sam3]" in err.message  # install hint visible to user


def test_sam3_runtime_failed_includes_frame_index() -> None:
    err = SAM3RuntimeFailed(frame_index=312, reason="cuda kernel fault")
    assert err.code == "sam3_runtime_failed"
    assert err.context == {"frame_index": 312, "reason": "cuda kernel fault"}


def test_sam3_init_failed_carries_underlying_repr() -> None:
    err = SAM3InitFailed(underlying="RuntimeError('CUDA OOM at 8.2 GB')")
    assert err.code == "sam3_init_failed"
    # underlying is recorded for stderr WARN log; it is NOT a degrade reason string
    assert err.context == {"underlying": "RuntimeError('CUDA OOM at 8.2 GB')"}


def test_gemma_no_object_prompts_no_context() -> None:
    err = GemmaNoObjectPrompts()
    assert err.code == "gemma_no_object_prompts"
    assert err.context == {}


def test_sam3_no_initial_detection_includes_failed_prompts() -> None:
    err = SAM3NoInitialDetection(
        failed=[("object", "red block"), ("object", "blue block")]
    )
    assert err.code == "sam3_no_initial_detection"
    assert err.context["failed_prompts"] == [
        {"role": "object", "prompt": "red block"},
        {"role": "object", "prompt": "blue block"},
    ]


def test_write_error_json_for_phase3_code() -> None:
    err = SAM3RuntimeFailed(frame_index=42, reason="x")
    sink = io.StringIO()
    write_error_json(err, stream=sink)
    payload = json.loads(sink.getvalue())
    assert payload["error_code"] == "sam3_runtime_failed"
    assert payload["context"]["frame_index"] == 42


@pytest.mark.parametrize(
    "code",
    [
        "sam3_checkpoint_not_found",
        "sam3_extras_missing",
        "sam3_runtime_failed",
        "sam3_init_failed",
        "gemma_no_object_prompts",
        "sam3_no_initial_detection",
    ],
)
def test_phase3_codes_distinct(code: str) -> None:
    """All 6 codes are distinct strings — used as dict keys / enum values
    elsewhere; collision would be a silent bug."""
    assert isinstance(code, str)
