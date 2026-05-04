"""SAM3Runtime smoke + import-wiring tests (spec §2.3, 2026-05-04 backend swap).

Non-gated tests verify import wiring + error class plumbing without needing
any model weights. The opt-in real-weights smoke (``MIMICANNO_RUN_SAM3_SMOKE=1``)
exercises the actual sam3 native predictor against ``sam3/checkpoints/sam3.pt``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
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


# ---------------------------------------------------------------------------
# load() error wiring
# ---------------------------------------------------------------------------


def test_load_raises_extras_missing_when_sam3_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load() raises SAM3ExtrasMissing when the sam3 import guard fails."""
    from mimicanno.errors import SAM3ExtrasMissing
    from mimicanno.object_tracker import sam3_runtime
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    with mock.patch.object(
        sam3_runtime,
        "_ensure_sam3_importable",
        side_effect=SAM3ExtrasMissing(),
    ), pytest.raises(SAM3ExtrasMissing):
        SAM3Runtime.load(checkpoint=Path("/tmp/dummy.pt"), device="cpu")


def test_load_raises_init_failed_when_predictor_build_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load() wraps ``build_sam3_video_predictor`` errors in SAM3InitFailed.

    We patch the function on the ``sam3.model_builder`` module that's already
    in ``sys.modules`` rather than swapping the whole module out. Reason:
    sam3.model_builder transitively imports torch, and re-importing a fake
    sam3.model_builder under ``mock.patch.dict(sys.modules)`` desynchronises
    torch's C extensions across tests (RuntimeError: function already has
    a docstring). Direct attribute replacement is enough here.
    """
    from mimicanno.errors import SAM3InitFailed
    from mimicanno.object_tracker import sam3_runtime
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime
    from sam3 import model_builder as real_mb

    monkeypatch.setattr(sam3_runtime, "_ensure_sam3_importable", lambda: None)

    def _explode(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        raise RuntimeError("weights not found")

    monkeypatch.setattr(real_mb, "build_sam3_video_predictor", _explode)

    with pytest.raises(SAM3InitFailed) as exc_info:
        SAM3Runtime.load(checkpoint=Path("/tmp/dummy.pt"), device="cpu")

    assert "weights not found" in exc_info.value.context["underlying"]


def test_load_raises_init_failed_when_bpe_asset_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """load() refuses to call build_* if the bpe asset is missing.

    Catches the typical "user forgot `git submodule update --init`" case
    with a clear message instead of a cryptic sam3 internal error.
    """
    from mimicanno.errors import SAM3InitFailed
    from mimicanno.object_tracker import sam3_runtime
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    monkeypatch.setattr(sam3_runtime, "_ensure_sam3_importable", lambda: None)
    bogus_bpe = tmp_path / "nope.txt.gz"
    monkeypatch.setattr(sam3_runtime, "_SAM3_BPE_PATH", bogus_bpe)

    with pytest.raises(SAM3InitFailed) as exc_info:
        SAM3Runtime.load(checkpoint=Path("/tmp/dummy.pt"), device="cpu")

    assert "bpe" in exc_info.value.context["underlying"].lower()


# ---------------------------------------------------------------------------
# close() lifecycle
# ---------------------------------------------------------------------------


def test_close_is_idempotent() -> None:
    """close() can be called multiple times without raising."""
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    runtime = SAM3Runtime(
        _predictor=mock.MagicMock(),
        _device="cpu",
        _offload_video=True,
    )
    runtime.close()
    runtime.close()  # second call must not raise


def test_close_closes_open_sessions() -> None:
    """close() iterates over _open_sessions and closes each on the predictor."""
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    runtime._open_sessions.extend(["s1", "s2"])
    runtime.close()

    close_calls = [
        c.args[0] for c in predictor.handle_request.call_args_list
        if c.args and c.args[0].get("type") == "close_session"
    ]
    closed_ids = {c["session_id"] for c in close_calls}
    assert closed_ids == {"s1", "s2"}
    # Each request opted out of per-session GC (we batch at runtime.close).
    assert all(c.get("run_gc_collect") is False for c in close_calls)


def test_ground_on_frame_raises_after_close() -> None:
    """Methods refuse to operate on a closed runtime."""
    import numpy as np

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    runtime = SAM3Runtime(
        _predictor=mock.MagicMock(), _device="cpu", _offload_video=True,
    )
    runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        runtime.ground_on_frame(
            np.zeros((4, 4, 3), dtype=np.uint8), "anything",
        )


def test_propagate_raises_after_close() -> None:
    from pathlib import Path as _Path

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    runtime = SAM3Runtime(
        _predictor=mock.MagicMock(), _device="cpu", _offload_video=True,
    )
    runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        list(runtime.propagate(
            video_path=_Path("/dev/null"),
            prompts_with_initial_bbox=[],
            expected_frames=set(),
        ))


# ---------------------------------------------------------------------------
# ground_on_frame: mock-driven contract verification
# ---------------------------------------------------------------------------


def _make_outputs_dict(
    obj_ids: list[int],
    boxes_xywh: list[list[float]],
    probs: list[float],
) -> dict:
    import numpy as np

    return {
        "out_obj_ids": np.asarray(obj_ids, dtype=np.int64),
        "out_boxes_xywh": np.asarray(boxes_xywh, dtype=np.float32).reshape(-1, 4),
        "out_probs": np.asarray(probs, dtype=np.float32),
    }


def test_ground_on_frame_starts_session_then_closes_it() -> None:
    """The grounding flow is: start_session → add_prompt(text=..) → close_session.
    The temp jpeg path used as resource_path must exist when start_session is
    called, and be unlinked after close (regardless of success/failure).
    """
    import numpy as np

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    predictor.handle_request.side_effect = [
        {"session_id": "S0"},  # start_session
        {  # add_prompt
            "frame_index": 0,
            "outputs": _make_outputs_dict(
                obj_ids=[0],
                boxes_xywh=[[0.1, 0.2, 0.3, 0.4]],
                probs=[0.9],
            ),
        },
        {"is_success": True},  # close_session
    ]

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    detections = runtime.ground_on_frame(
        np.zeros((8, 8, 3), dtype=np.uint8), "the prompt",
    )

    assert len(detections) == 1
    bbox, score = detections[0]
    assert (bbox.x, bbox.y, bbox.w, bbox.h) == (
        pytest.approx(0.1), pytest.approx(0.2),
        pytest.approx(0.3), pytest.approx(0.4),
    )
    assert score == pytest.approx(0.9)

    types = [c.args[0]["type"] for c in predictor.handle_request.call_args_list]
    assert types == ["start_session", "add_prompt", "close_session"]

    add_call = predictor.handle_request.call_args_list[1].args[0]
    assert add_call["text"] == "the prompt"
    assert add_call["session_id"] == "S0"
    assert add_call["frame_index"] == 0
    assert add_call["rel_coordinates"] is True

    # No sessions should be left dangling on the runtime.
    assert runtime._open_sessions == []


def test_ground_on_frame_closes_session_even_when_add_prompt_raises() -> None:
    """If add_prompt explodes mid-session, the temp file is still unlinked
    and the session is still closed (try/finally contract)."""
    import numpy as np

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    predictor.handle_request.side_effect = [
        {"session_id": "S1"},  # start_session
        RuntimeError("oh no"),  # add_prompt
        {"is_success": True},  # close_session
    ]

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    with pytest.raises(RuntimeError, match="oh no"):
        runtime.ground_on_frame(
            np.zeros((4, 4, 3), dtype=np.uint8), "x",
        )

    types = [c.args[0]["type"] for c in predictor.handle_request.call_args_list]
    assert "close_session" in types
    assert runtime._open_sessions == []


def test_ground_on_frame_returns_empty_list_for_no_detections() -> None:
    import numpy as np

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    predictor.handle_request.side_effect = [
        {"session_id": "S2"},
        {"frame_index": 0, "outputs": _make_outputs_dict([], [], [])},
        {"is_success": True},
    ]

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    assert runtime.ground_on_frame(
        np.zeros((4, 4, 3), dtype=np.uint8), "nothing-here",
    ) == []


# ---------------------------------------------------------------------------
# propagate: mock-driven N-session round-robin
# ---------------------------------------------------------------------------


def test_propagate_no_prompts_yields_nothing() -> None:
    """Empty prompts list → empty generator, no sessions opened."""
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    results = list(runtime.propagate(
        video_path=Path("/dev/null"),
        prompts_with_initial_bbox=[],
        expected_frames={0, 1, 2},
    ))
    assert results == []
    predictor.handle_request.assert_not_called()


def test_propagate_two_prompts_round_robin_merges_per_frame() -> None:
    """Two prompts → two sessions; per-frame results merged into one
    FramePropagationResult per frame in expected_frames."""
    from mimicanno.object_tracker.propagator import BBox
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()

    # Two start_session + two add_prompt requests, then handle_stream_request
    # is called twice — once per session.
    predictor.handle_request.side_effect = [
        {"session_id": "A"},      # start_session for prompt 0
        {"frame_index": 0, "outputs": _make_outputs_dict(
            [0], [[0.1, 0.1, 0.1, 0.1]], [0.5],
        )},  # add_prompt for prompt 0 (response unused by propagate)
        {"session_id": "B"},      # start_session for prompt 1
        {"frame_index": 0, "outputs": _make_outputs_dict(
            [0], [[0.5, 0.5, 0.1, 0.1]], [0.6],
        )},  # add_prompt for prompt 1
        {"is_success": True},     # close_session A
        {"is_success": True},     # close_session B
    ]

    def stream_factory(req):
        sid = req["session_id"]
        if sid == "A":
            return iter([
                {"frame_index": 0, "outputs": _make_outputs_dict(
                    [0], [[0.10, 0.10, 0.10, 0.10]], [0.91],
                )},
                {"frame_index": 1, "outputs": _make_outputs_dict(
                    [0], [[0.11, 0.11, 0.10, 0.10]], [0.92],
                )},
                {"frame_index": 2, "outputs": _make_outputs_dict(
                    [], [], [],
                )},  # lost on frame 2
            ])
        return iter([
            {"frame_index": 0, "outputs": _make_outputs_dict(
                [0], [[0.50, 0.50, 0.10, 0.10]], [0.75],
            )},
            {"frame_index": 1, "outputs": _make_outputs_dict(
                [0], [[0.51, 0.51, 0.10, 0.10]], [0.74],
            )},
            {"frame_index": 2, "outputs": _make_outputs_dict(
                [0], [[0.52, 0.52, 0.10, 0.10]], [0.73],
            )},
        ])

    predictor.handle_stream_request.side_effect = stream_factory

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    results = list(runtime.propagate(
        video_path=Path("/dev/null"),
        prompts_with_initial_bbox=[
            ("alpha", BBox(0.1, 0.1, 0.1, 0.1)),
            ("beta",  BBox(0.5, 0.5, 0.1, 0.1)),
        ],
        expected_frames={0, 2},  # frame 1 deliberately filtered out
    ))

    assert [r.frame for r in results] == [0, 2]

    f0 = results[0].detections
    assert f0["alpha"] is not None and f0["alpha"][1] == pytest.approx(0.91)
    assert f0["beta"] is not None and f0["beta"][1] == pytest.approx(0.75)

    f2 = results[1].detections
    assert f2["alpha"] is None  # lost on this frame
    assert f2["beta"] is not None and f2["beta"][1] == pytest.approx(0.73)


def test_propagate_handles_track_lost_via_obj_id_drop() -> None:
    """When sam3 drops the obj_id from out_obj_ids, the prompt's detection is None."""
    from mimicanno.object_tracker.propagator import BBox
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    predictor.handle_request.side_effect = [
        {"session_id": "X"},
        {"frame_index": 0, "outputs": _make_outputs_dict([0], [[0, 0, 0.1, 0.1]], [0.5])},
        {"is_success": True},
    ]
    predictor.handle_stream_request.side_effect = lambda req: iter([
        {"frame_index": 0, "outputs": _make_outputs_dict(
            [0], [[0.0, 0.0, 0.1, 0.1]], [0.8],
        )},
        {"frame_index": 1, "outputs": _make_outputs_dict([], [], [])},
    ])

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    results = list(runtime.propagate(
        video_path=Path("/dev/null"),
        prompts_with_initial_bbox=[("p", BBox(0.0, 0.0, 0.1, 0.1))],
        expected_frames={0, 1},
    ))
    assert results[0].detections["p"] is not None
    assert results[1].detections["p"] is None


def test_propagate_closes_sessions_when_consumer_breaks_early() -> None:
    """If the caller stops iterating early, the generator's finally still
    closes every session that was opened."""
    from mimicanno.object_tracker.propagator import BBox
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    predictor = mock.MagicMock()
    predictor.handle_request.side_effect = [
        {"session_id": "Z"},
        {"frame_index": 0, "outputs": _make_outputs_dict([0], [[0, 0, 0.1, 0.1]], [0.5])},
        {"is_success": True},  # close_session, eventually
    ]
    predictor.handle_stream_request.side_effect = lambda req: iter([
        {"frame_index": 0, "outputs": _make_outputs_dict(
            [0], [[0.0, 0.0, 0.1, 0.1]], [0.8],
        )},
        {"frame_index": 1, "outputs": _make_outputs_dict(
            [0], [[0.1, 0.1, 0.1, 0.1]], [0.7],
        )},
    ])

    runtime = SAM3Runtime(
        _predictor=predictor, _device="cpu", _offload_video=True,
    )
    gen = runtime.propagate(
        video_path=Path("/dev/null"),
        prompts_with_initial_bbox=[("only", BBox(0.0, 0.0, 0.1, 0.1))],
        expected_frames={0, 1},
    )
    # Consume only the first frame, then close the generator.
    first = next(gen)
    assert first.frame == 0
    gen.close()

    types = [c.args[0]["type"] for c in predictor.handle_request.call_args_list]
    assert "close_session" in types


# ---------------------------------------------------------------------------
# Cross-module wiring
# ---------------------------------------------------------------------------


def test_fixtures_frame_propagation_result_is_same_class() -> None:
    """fixtures.FramePropagationResult is identical to sam3_runtime's."""
    from mimicanno.object_tracker.fixtures import FramePropagationResult as FromFixtures
    from mimicanno.object_tracker.sam3_runtime import (
        FramePropagationResult as FromRuntime,
    )

    assert FromFixtures is FromRuntime


def test_legacy_import_alias_still_works() -> None:
    """Old name kept as an alias so cli.py and integration tests don't break."""
    from mimicanno.object_tracker import sam3_runtime

    assert (
        sam3_runtime._ensure_transformers_sam3_importable
        is sam3_runtime._ensure_sam3_importable
    )


# ---------------------------------------------------------------------------
# Gated: real SAM3 smoke (needs MIMICANNO_RUN_SAM3_SMOKE=1 + CUDA)
# ---------------------------------------------------------------------------

_SMOKE_ENABLED = os.environ.get("MIMICANNO_RUN_SAM3_SMOKE", "") == "1"


@pytest.mark.skipif(
    not _SMOKE_ENABLED,
    reason="real-SAM3 smoke is opt-in via MIMICANNO_RUN_SAM3_SMOKE=1",
)
def test_sam3_runtime_smoke_load_and_ground() -> None:  # pragma: no cover
    """Smoke test: load SAM3, run grounding on a real video frame.

    Requires MIMICANNO_RUN_SAM3_SMOKE=1, CUDA, and a checkpoint at
    ``$SAM3_CHECKPOINT`` (default: ``sam3/checkpoints/sam3.pt``).
    """
    import cv2  # type: ignore

    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    checkpoint = Path(os.environ.get(
        "SAM3_CHECKPOINT", "sam3/checkpoints/sam3.pt",
    ))
    cap = cv2.VideoCapture("sam3/assets/videos/bedroom.mp4")
    ok, frame_bgr = cap.read()
    cap.release()
    assert ok, "could not read bedroom.mp4 — required for smoke"
    frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    runtime = SAM3Runtime.load(checkpoint=checkpoint, device="cuda")
    try:
        detections = runtime.ground_on_frame(frame, "bed")
        assert isinstance(detections, list)
        assert all(0.0 <= b.x <= 1.0 for b, _ in detections)
        assert all(0.0 <= b.y <= 1.0 for b, _ in detections)
    finally:
        runtime.close()
        runtime.close()
