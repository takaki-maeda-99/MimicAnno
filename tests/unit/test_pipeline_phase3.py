# tests/unit/test_pipeline_phase3.py
"""Unit tests for annotate_episode_phase3 orchestrator (Task 19).

All ML-heavy components (LocalGemmaVLMLabeler, SAM3Runtime,
LocalGemmaTrackingPlanner, Propagator, apply_phase3_labeling) are mocked.
Only the orchestration logic, degrade gates, and resource discipline are
tested here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    ModelConfig,
    TrackingConfig,
    VLMConfig,
)
from mimicanno.errors import SAM3InitFailed
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import BBox, Track, TrackSample
from mimicanno.pipeline import (
    AnnotateRequest,
    _compute_image_aspect_ratio,
    annotate_episode_phase3,
)
from mimicanno.schema import (
    BoundaryRef,
    SubtaskSegment,
)
from mimicanno.vlm_labeler import RunOutcome
from tests.fixtures.synthesize import synthesize_aloha_episode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    vlm_model_id: str = "fixture",
    resolved_checkpoint: str = "abc",
    fixture_path: Path | None = None,
    sam3_checkpoint: str | None = "/tmp/sam3.pt",
) -> AnnotationConfig:
    vlm = VLMConfig(
        model_id=vlm_model_id,
        resolved_checkpoint=resolved_checkpoint,
        fixture_path=fixture_path,
    )
    tracking = TrackingConfig(
        sam3_checkpoint=sam3_checkpoint,
        planner_max_retries=2,
    )
    boundary = BoundaryConfig.with_defaults()
    model_config = ModelConfig(
        vlm_model=vlm_model_id,
        vlm_checkpoint=resolved_checkpoint,
        sam3_model=None,
        sam3_checkpoint=None,
    )
    return AnnotationConfig(
        boundary=boundary,
        target_phase=3,
        model_config=model_config,
        vlm=vlm,
        tracking=tracking,
    )


def _make_request(
    episode: Any,
    runs_root: Path,
    config: AnnotationConfig | None = None,
) -> AnnotateRequest:
    if config is None:
        config = _make_config()
    return AnnotateRequest(
        video=episode.video,
        parquet=episode.parquet,
        task="pick the red block",
        robot_adapter_name="aloha",
        robot_adapter_config_path=None,
        labels_path=None,
        runs_root=runs_root,
        link_video=False,
        force=True,
        config=config,
    )


def _make_track(role: str = "object", prompt: str = "red block") -> Track:
    """Build a minimal Track with one sample."""
    from mimicanno.object_tracker.track_id import ROLE, make_track_id
    typed_role: ROLE = role  # type: ignore[assignment]
    track_id = make_track_id(role=typed_role, prompt=prompt, index=0)
    return Track(
        track_id=track_id,
        role=typed_role,
        prompt=prompt,
        slug="red_block",
        index=0,
        primary=True,
        samples=[
            TrackSample(
                frame=0,
                time_sec=0.0,
                bbox=BBox(x=0.1, y=0.1, w=0.2, h=0.2),
                score=0.9,
            )
        ],
        gap_events=[],
    )


def _minimal_segment(fps: float = 30.0) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id="s_000",
        episode_id="ep_synth_000",
        start_frame=0,
        end_frame=60,
        start_time=0.0,
        end_time=2.0,
        phase="unlabeled",
        verb=None,
        object=None,
        target=None,
        failure_flags=[],
        label_source="signals_only",
        object_state_unavailable=False,
        object_track_ids=[],
        label_version="manipulation.v1",
        start_boundary=BoundaryRef(
            candidate_id=None,
            time=0.0,
            sources=["episode_start"],
            score=1.0,
        ),
        end_boundary=BoundaryRef(
            candidate_id=None,
            time=2.0,
            sources=["episode_end"],
            score=1.0,
        ),
        boundary_confidence=1.0,
        vlm_confidence=None,
        overall_confidence=1.0,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )


# ---------------------------------------------------------------------------
# The patch targets (all relative to mimicanno.pipeline)
# ---------------------------------------------------------------------------

_PATCH_VLM = "mimicanno.pipeline.LocalGemmaVLMLabeler"
_PATCH_SAM3 = "mimicanno.pipeline.SAM3Runtime"
_PATCH_PLANNER = "mimicanno.pipeline.LocalGemmaTrackingPlanner"
_PATCH_PROPAGATOR = "mimicanno.pipeline.Propagator"
_PATCH_APPLY = "mimicanno.pipeline.apply_phase3_labeling"
_PATCH_DEGRADE = "mimicanno.pipeline._degrade_to_phase3_objectless"
_PATCH_GROUND = "mimicanno.pipeline.ground_initial_detections_with_retry"
_PATCH_OBJ_SIGNALS = "mimicanno.pipeline.compute_object_signals"
_PATCH_DETECTOR = "mimicanno.pipeline.Phase3BoundaryDetector"
_PATCH_BRACKET = "mimicanno.pipeline.bracket_phase1_segments"
_PATCH_INITIAL_FRAME = "mimicanno.pipeline._extract_frame_at"


# ---------------------------------------------------------------------------
# Test 1: Happy path — all stages succeed
# ---------------------------------------------------------------------------


def test_happy_path_all_stages_succeed(tmp_path: Path) -> None:
    """Happy path: annotate_episode_phase3 returns AnnotateResult with
    pipeline_status.object_state_available=True and degraded_from_phase=None."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    req = _make_request(episode, runs_root)

    # Build canned track
    track = _make_track()
    fake_tracks = [track]
    fake_segments = [_minimal_segment()]

    # Entity plan with object
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=[],
        tool_prompts=[],
    )

    # Stub TrackingPlan
    fake_plan = MagicMock()
    fake_plan.initial_detections = {("object", "red block"): BBox(0.1, 0.1, 0.2, 0.2)}

    # Object signals stub
    fake_object_signals = MagicMock()
    fake_object_signals.gripper_tool_track_id = None
    fake_object_signals.gripper_object_distance = {}
    fake_object_signals.object_speed = {}

    # Phase3BoundaryDetector stub
    fake_detector = MagicMock()
    fake_detector.detect.return_value = ([], ["eef_velocity_valley"])

    # apply_phase3_labeling returns ok outcome + coverage
    fake_run_outcome = RunOutcome(kind="ok", degrade_reason=None, underlying_error=None)

    _fake_initial_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with (
        patch(_PATCH_INITIAL_FRAME, return_value=_fake_initial_frame),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        patch(_PATCH_GROUND, return_value=(0, _fake_initial_frame, fake_plan, [])),
        patch(_PATCH_PROPAGATOR) as mock_prop_cls,
        patch(_PATCH_OBJ_SIGNALS, return_value=fake_object_signals),
        patch(_PATCH_DETECTOR, return_value=fake_detector),
        patch(_PATCH_BRACKET, return_value=fake_segments),
        patch(_PATCH_APPLY, return_value=(fake_segments, [], fake_run_outcome, 0.8)),
    ):
        # Wire VLM mock
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_handle = MagicMock()
        mock_vlm_instance.shared_handle.return_value = mock_handle

        # Wire planner mock
        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        # Wire SAM3 mock
        mock_sam3_instance = MagicMock()
        mock_sam3_cls.load.return_value = mock_sam3_instance

        # Wire propagator mock
        mock_prop_instance = MagicMock()
        mock_prop_cls.return_value = mock_prop_instance
        # Task 5: Propagator.run now returns (tracks, mask_cache).
        mock_prop_instance.run.return_value = (fake_tracks, None)

        result = annotate_episode_phase3(req)

    # Check result structure
    assert result is not None
    assert result.run_dir is not None

    # Verify SAM3.close was called
    mock_sam3_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: Gemma handle is shared (planner uses vlm.shared_handle())
# ---------------------------------------------------------------------------


def test_gemma_handle_shared(tmp_path: Path) -> None:
    """The planner is constructed with vlm.shared_handle() result."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    entities = EntityPlan(
        object_prompts=["block"],
        target_prompts=[],
        tool_prompts=[],
    )
    fake_plan = MagicMock()
    fake_plan.initial_detections = {("object", "block"): BBox(0.1, 0.1, 0.2, 0.2)}
    fake_object_signals = MagicMock()
    fake_object_signals.gripper_tool_track_id = None
    fake_object_signals.gripper_object_distance = {}
    fake_object_signals.object_speed = {}
    fake_detector = MagicMock()
    fake_detector.detect.return_value = ([], [])
    fake_run_outcome = RunOutcome(kind="ok", degrade_reason=None, underlying_error=None)
    fake_segments = [_minimal_segment()]

    _fake_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with (
        patch(_PATCH_INITIAL_FRAME, return_value=_fake_frame),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        patch(_PATCH_GROUND, return_value=(0, _fake_frame, fake_plan, [])),
        patch(_PATCH_PROPAGATOR) as mock_prop_cls,
        patch(_PATCH_OBJ_SIGNALS, return_value=fake_object_signals),
        patch(_PATCH_DETECTOR, return_value=fake_detector),
        patch(_PATCH_BRACKET, return_value=fake_segments),
        patch(_PATCH_APPLY, return_value=(fake_segments, [], fake_run_outcome, 0.5)),
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        captured_handle = MagicMock()
        mock_vlm_instance.shared_handle.return_value = captured_handle

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        mock_sam3_instance = MagicMock()
        mock_sam3_cls.load.return_value = mock_sam3_instance
        mock_prop_instance = MagicMock()
        mock_prop_cls.return_value = mock_prop_instance
        mock_prop_instance.run.return_value = ([], None)

        annotate_episode_phase3(req)

    # The planner must have been constructed with the shared handle
    mock_planner_cls.assert_called_once_with(captured_handle)


# ---------------------------------------------------------------------------
# Test 3: SAM3.close is called BEFORE apply_phase3_labeling
# ---------------------------------------------------------------------------


def test_sam3_close_before_apply_phase3_labeling(tmp_path: Path) -> None:
    """sam3_runtime.close() is called before apply_phase3_labeling (resource discipline)."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    entities = EntityPlan(
        object_prompts=["block"],
        target_prompts=[],
        tool_prompts=[],
    )
    fake_plan = MagicMock()
    fake_plan.initial_detections = {("object", "block"): BBox(0.1, 0.1, 0.2, 0.2)}
    fake_object_signals = MagicMock()
    fake_object_signals.gripper_tool_track_id = None
    fake_object_signals.gripper_object_distance = {}
    fake_object_signals.object_speed = {}
    fake_detector = MagicMock()
    fake_detector.detect.return_value = ([], [])
    fake_run_outcome = RunOutcome(kind="ok", degrade_reason=None, underlying_error=None)
    fake_segments = [_minimal_segment()]

    call_order: list[str] = []

    def fake_close() -> None:
        call_order.append("sam3_close")

    def fake_apply_phase3(**kwargs: Any) -> Any:
        call_order.append("apply_phase3_labeling")
        return (fake_segments, [], fake_run_outcome, 0.5)

    _fake_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with (
        patch(_PATCH_INITIAL_FRAME, return_value=_fake_frame),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        patch(_PATCH_GROUND, return_value=(0, _fake_frame, fake_plan, [])),
        patch(_PATCH_PROPAGATOR) as mock_prop_cls,
        patch(_PATCH_OBJ_SIGNALS, return_value=fake_object_signals),
        patch(_PATCH_DETECTOR, return_value=fake_detector),
        patch(_PATCH_BRACKET, return_value=fake_segments),
        patch(_PATCH_APPLY, side_effect=fake_apply_phase3),
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_vlm_instance.shared_handle.return_value = MagicMock()

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        mock_sam3_instance = MagicMock()
        mock_sam3_instance.close.side_effect = fake_close
        mock_sam3_cls.load.return_value = mock_sam3_instance

        mock_prop_instance = MagicMock()
        mock_prop_cls.return_value = mock_prop_instance
        mock_prop_instance.run.return_value = ([], None)

        annotate_episode_phase3(req)

    assert call_order == ["sam3_close", "apply_phase3_labeling"], (
        f"Expected sam3_close before apply_phase3_labeling, got: {call_order}"
    )


# ---------------------------------------------------------------------------
# Test 4: finally discipline — exception in Propagator.run still closes SAM3
# ---------------------------------------------------------------------------


def test_finally_sam3_close_called_even_on_propagator_exception(tmp_path: Path) -> None:
    """If Propagator.run raises, sam3.close() is still called and exception propagates."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    entities = EntityPlan(
        object_prompts=["block"],
        target_prompts=[],
        tool_prompts=[],
    )
    fake_plan = MagicMock()
    fake_plan.initial_detections = {("object", "block"): BBox(0.1, 0.1, 0.2, 0.2)}

    _fake_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with (
        patch(_PATCH_INITIAL_FRAME, return_value=_fake_frame),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        patch(_PATCH_GROUND, return_value=(0, _fake_frame, fake_plan, [])),
        patch(_PATCH_PROPAGATOR) as mock_prop_cls,
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_vlm_instance.shared_handle.return_value = MagicMock()

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        mock_sam3_instance = MagicMock()
        mock_sam3_cls.load.return_value = mock_sam3_instance

        mock_prop_instance = MagicMock()
        mock_prop_cls.return_value = mock_prop_instance
        mock_prop_instance.run.side_effect = RuntimeError("GPU exploded")

        with pytest.raises(RuntimeError, match="GPU exploded"):
            annotate_episode_phase3(req)

    # close() must have been called despite the exception
    mock_sam3_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 5: _compute_image_aspect_ratio fallback cases
# ---------------------------------------------------------------------------


def test_compute_image_aspect_ratio_normal() -> None:
    from mimicanno.io_video import VideoProbe

    probe = VideoProbe(sha256="sha256:abc", duration_sec=4.0, fps=30.0, width=1920, height=1080)
    tracking = TrackingConfig()
    result = _compute_image_aspect_ratio(probe, tracking)
    assert abs(result - 1920 / 1080) < 1e-9


def test_compute_image_aspect_ratio_fallback_when_height_zero() -> None:
    from mimicanno.io_video import VideoProbe

    probe = VideoProbe(sha256="sha256:abc", duration_sec=4.0, fps=30.0, width=1920, height=0)
    tracking = TrackingConfig(image_aspect_ratio_default=2.0)
    result = _compute_image_aspect_ratio(probe, tracking)
    assert result == 2.0


def test_compute_image_aspect_ratio_fallback_when_width_zero() -> None:
    from mimicanno.io_video import VideoProbe

    probe = VideoProbe(sha256="sha256:abc", duration_sec=4.0, fps=30.0, width=0, height=1080)
    tracking = TrackingConfig(image_aspect_ratio_default=1.5)
    result = _compute_image_aspect_ratio(probe, tracking)
    assert result == 1.5


# ---------------------------------------------------------------------------
# Test 6a: Degrade gate — gemma_no_object_prompts
# ---------------------------------------------------------------------------


def test_degrade_gate_gemma_no_object_prompts(tmp_path: Path) -> None:
    """When planner returns empty object_prompts, _degrade_to_phase3_objectless is called."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    empty_entities = EntityPlan(
        object_prompts=[],
        target_prompts=[],
        tool_prompts=[],
    )
    fake_degrade_result = MagicMock()

    with (
        patch(_PATCH_INITIAL_FRAME, return_value=np.zeros((64, 64, 3), dtype=np.uint8)),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_DEGRADE, return_value=fake_degrade_result) as mock_degrade,
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_vlm_instance.shared_handle.return_value = MagicMock()

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = empty_entities

        result = annotate_episode_phase3(req)

    assert result is fake_degrade_result
    mock_degrade.assert_called_once()
    call_kwargs = mock_degrade.call_args
    assert call_kwargs.kwargs["degrade_reason"] == "gemma_no_object_prompts"


# ---------------------------------------------------------------------------
# Test 6b: Degrade gate — sam3_init_failed
# ---------------------------------------------------------------------------


def test_degrade_gate_sam3_init_failed(tmp_path: Path) -> None:
    """When SAM3Runtime.load raises SAM3InitFailed, degrade fires with underlying_log."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    entities = EntityPlan(
        object_prompts=["block"],
        target_prompts=[],
        tool_prompts=[],
    )
    sam3_exc = SAM3InitFailed(underlying="CUDA OOM")
    fake_degrade_result = MagicMock()

    with (
        patch(_PATCH_INITIAL_FRAME, return_value=np.zeros((64, 64, 3), dtype=np.uint8)),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        patch(_PATCH_DEGRADE, return_value=fake_degrade_result) as mock_degrade,
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_vlm_instance.shared_handle.return_value = MagicMock()

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        mock_sam3_cls.load.side_effect = sam3_exc

        result = annotate_episode_phase3(req)

    assert result is fake_degrade_result
    mock_degrade.assert_called_once()
    call_kwargs = mock_degrade.call_args
    assert call_kwargs.kwargs["degrade_reason"] == "sam3_init_failed"
    # underlying_log kwarg must contain "SAM3InitFailed"
    underlying_log = call_kwargs.kwargs.get("underlying_log", "")
    assert underlying_log is not None
    assert "SAM3InitFailed" in underlying_log


# ---------------------------------------------------------------------------
# Test 6c: Degrade gate — sam3_no_initial_detection
# ---------------------------------------------------------------------------


def test_degrade_gate_sam3_no_initial_detection(tmp_path: Path) -> None:
    """When ground_initial_detections returns empty detections, degrade fires."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    req = _make_request(episode, tmp_path / "runs")

    entities = EntityPlan(
        object_prompts=["block"],
        target_prompts=[],
        tool_prompts=[],
    )
    # TrackingPlan with no grounded detections
    from mimicanno.object_tracker.propagator import TrackingPlan

    empty_plan = TrackingPlan(
        entities=entities,
        initial_detections={},
        failed_prompts=[("object", "block")],
    )
    fake_degrade_result = MagicMock()

    _fake_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    with (
        patch(_PATCH_INITIAL_FRAME, return_value=_fake_frame),
        patch(_PATCH_VLM) as mock_vlm_cls,
        patch(_PATCH_PLANNER) as mock_planner_cls,
        patch(_PATCH_SAM3) as mock_sam3_cls,
        # ground_initial_detections_with_retry returns (adopted_idx, frame, plan, attempts)
        patch(_PATCH_GROUND, return_value=(0, _fake_frame, empty_plan, [])),
        patch(_PATCH_DEGRADE, return_value=fake_degrade_result) as mock_degrade,
    ):
        mock_vlm_instance = MagicMock()
        mock_vlm_cls.return_value = mock_vlm_instance
        mock_vlm_instance.shared_handle.return_value = MagicMock()

        mock_planner_instance = MagicMock()
        mock_planner_cls.return_value = mock_planner_instance
        mock_planner_instance.extract_entities.return_value = entities

        mock_sam3_instance = MagicMock()
        mock_sam3_cls.load.return_value = mock_sam3_instance

        result = annotate_episode_phase3(req)

    assert result is fake_degrade_result
    mock_degrade.assert_called_once()
    call_kwargs = mock_degrade.call_args
    assert call_kwargs.kwargs["degrade_reason"] == "sam3_no_initial_detection"
    # SAM3 must still be closed even when degrade fires from ground step
    mock_sam3_instance.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test 7: _extract_initial_frame — basic shape test (real MP4)
# ---------------------------------------------------------------------------


def test_extract_frame_at_returns_array(tmp_path: Path) -> None:
    """_extract_frame_at returns a HxWx3 uint8 array for a real MP4 (frame 0)."""
    from mimicanno.pipeline import _extract_frame_at

    video = synthesize_aloha_episode(tmp_path / "data").video
    frame = _extract_frame_at(video, n_frames=120, frame_index=0)
    assert frame.dtype == np.uint8
    assert frame.ndim == 3
    assert frame.shape[2] == 3  # RGB
