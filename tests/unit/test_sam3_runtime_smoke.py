"""SAM3Runtime smoke + import-wiring tests (spec §2.3, Task 14).

Gated tests (require real weights + CUDA) are skipped unless
MIMICANNO_RUN_SAM3_SMOKE=1.  Non-gated tests verify import wiring +
error class plumbing without needing any model weights.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Non-gated: import surface
# ---------------------------------------------------------------------------


def test_frame_propagation_result_exported_from_package() -> None:
    """FramePropagationResult is re-exported from mimicanno.object_tracker."""
    from mimicanno.object_tracker import FramePropagationResult
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult as Source

    assert FramePropagationResult is Source


def test_sam3_runtime_exported_from_package() -> None:
    """SAM3Runtime is exported from mimicanno.object_tracker."""
    from mimicanno.object_tracker import SAM3Runtime

    assert SAM3Runtime is not None


def test_frame_propagation_result_dataclass_fields() -> None:
    """FramePropagationResult has the expected fields with correct types."""
    from mimicanno.object_tracker.propagator import BBox
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult

    bbox = BBox(x=0.1, y=0.1, w=0.2, h=0.2)
    result = FramePropagationResult(
        frame=5,
        detections={"red block": (bbox, 0.9), "bin A": None},
    )
    assert result.frame == 5
    assert result.detections["red block"] == (bbox, 0.9)
    assert result.detections["bin A"] is None


def test_frame_propagation_result_is_frozen() -> None:
    """FramePropagationResult is frozen (immutable)."""
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult

    result = FramePropagationResult(frame=0, detections={})
    with pytest.raises((AttributeError, TypeError)):
        result.frame = 1  # type: ignore[misc]


def test_sam3_runtime_load_raises_extras_missing_when_transformers_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SAM3Runtime.load() raises SAM3ExtrasMissing when import guard fails."""
    from mimicanno.errors import SAM3ExtrasMissing
    from mimicanno.object_tracker import sam3_runtime
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    with mock.patch.object(
        sam3_runtime,
        "_ensure_transformers_sam3_importable",
        side_effect=SAM3ExtrasMissing(),
    ), pytest.raises(SAM3ExtrasMissing):
        SAM3Runtime.load(checkpoint="facebook/sam3", device="cpu")


def test_sam3_runtime_load_raises_init_failed_on_pretrained_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SAM3Runtime.load() wraps from_pretrained errors in SAM3InitFailed.

    Sam3Processor.from_pretrained is called first in load(), so failing it
    here exercises the try/except wrapper without needing to also fail
    Sam3Model.from_pretrained (it is never reached).
    """
    from mimicanno.errors import SAM3InitFailed
    from mimicanno.object_tracker import sam3_runtime
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    monkeypatch.setattr(sam3_runtime, "_ensure_transformers_sam3_importable", lambda: None)

    fake_processor = mock.MagicMock()
    fake_processor.from_pretrained.side_effect = RuntimeError("weights not found")

    with mock.patch.dict(
        sys.modules,
        {
            "transformers": mock.MagicMock(
                Sam3Processor=fake_processor,
                Sam3Model=mock.MagicMock(),
                Sam3TrackerVideoModel=mock.MagicMock(),
            )
        },
    ), pytest.raises(SAM3InitFailed) as exc_info:
        SAM3Runtime.load(checkpoint="facebook/sam3", device="cpu")

    assert exc_info.value.context["underlying"] != ""


def test_sam3_runtime_close_is_idempotent() -> None:
    """SAM3Runtime.close() can be called multiple times without error."""
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    runtime = SAM3Runtime(
        _model=mock.MagicMock(),
        _processor=mock.MagicMock(),
        _tracker_model=mock.MagicMock(),
        _device="cpu",
    )
    runtime.close()
    runtime.close()  # Second call must not raise


def test_fixtures_frame_propagation_result_is_same_class() -> None:
    """fixtures.FramePropagationResult is the same object as sam3_runtime.FramePropagationResult."""
    from mimicanno.object_tracker.fixtures import FramePropagationResult as FromFixtures
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult as FromRuntime

    assert FromFixtures is FromRuntime


# ---------------------------------------------------------------------------
# Gated: real SAM3 smoke test (needs MIMICANNO_RUN_SAM3_SMOKE=1 + CUDA)
# ---------------------------------------------------------------------------

_SMOKE_ENABLED = os.environ.get("MIMICANNO_RUN_SAM3_SMOKE", "") == "1"


@pytest.mark.skipif(
    not _SMOKE_ENABLED,
    reason="real-SAM3 smoke is opt-in via MIMICANNO_RUN_SAM3_SMOKE=1",
)
def test_sam3_runtime_smoke_load_and_ground() -> None:  # pragma: no cover
    """Smoke test: load SAM3, run grounding on a tiny frame.

    Requires MIMICANNO_RUN_SAM3_SMOKE=1, a CUDA device, and the
    facebook/sam3 weights in the HF cache.

    TODO(Task 25): once this test can be run against real weights, verify:
    - ground_on_frame() returns a non-empty list for a clear image+prompt.
    - propagate() yields FramePropagationResult for each input frame.
    - BBox coords are in normalized [0, 1] range.
    - close() releases CUDA memory (check torch.cuda.memory_allocated drops).
    """
    import numpy as np

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    checkpoint = os.environ.get("SAM3_CHECKPOINT", "facebook/sam3")
    device = "cuda" if __import__("torch").cuda.is_available() else "cpu"

    runtime = SAM3Runtime.load(checkpoint=checkpoint, device=device)
    try:
        frame = np.zeros((224, 224, 3), dtype=np.uint8)
        detections = runtime.ground_on_frame(frame, "red block")
        # May return empty list on a blank frame — just check type
        assert isinstance(detections, list)
    finally:
        runtime.close()
        runtime.close()  # idempotent
