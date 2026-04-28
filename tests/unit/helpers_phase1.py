"""Helpers for constructing Phase 1 SubtaskSegment fixtures + signal arrays
without invoking the full pipeline. Used by Phase 2 unit tests.
"""
from __future__ import annotations

import numpy as np

from mimicanno.config import ClipFeatureConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment

_DEFAULT_ALLOWED_LABELS = [
    "idle", "approach_object", "align_gripper", "grasp_object",
    "lift_object", "move_to_target", "align_to_target",
    "place_object", "release_object", "retreat",
]


class StubClipFeatureExtractor:
    """Test-only ClipFeatureExtractor that returns 4x4 zero-RGB keyframes
    instead of reading a real video. Computed scalars are real (uses the
    production compute_robot_state_summary)."""

    def __init__(self, fps: float, cfg: ClipFeatureConfig) -> None:
        self._fps = fps
        self._cfg = cfg

    def extract(
        self, *, segment, gripper, eef_velocity, keyframes_per_segment,
    ):
        from mimicanno.clip_features import (
            ClipFeatures,
            compute_keyframe_offsets,
            compute_robot_state_summary,
        )
        offsets = compute_keyframe_offsets(
            segment.start_frame, segment.end_frame, keyframes_per_segment,
        )
        offsets_sec = [(o - segment.start_frame) / self._fps for o in offsets]
        frames = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in offsets]
        summary = compute_robot_state_summary(
            start_frame=segment.start_frame, end_frame=segment.end_frame,
            fps=self._fps, gripper=gripper, eef_velocity=eef_velocity, cfg=self._cfg,
        )
        return ClipFeatures(
            keyframes=frames, keyframe_offsets_sec=offsets_sec,
            robot_state_summary=summary,
        )


def make_synthetic_phase1_run(
    n_segments: int = 4, fps: float = 30.0, frames_per_seg: int = 30,
    *, allowed_labels: list[str] | None = None,
    task_text: str = "pick the red block and place in white bin",
    robot_type: str = "aloha", label_version: str = "manipulation.v1",
):
    """Produce n_segments unlabeled SubtaskSegments + the signal arrays + a
    StubClipFeatureExtractor + episode_meta dict — everything needed to
    invoke `label_run(...)` without spinning up a real video / pipeline.

    Returns (segments, gripper, eef_velocity, extractor, episode_meta)."""
    total_frames = n_segments * frames_per_seg
    duration = total_frames / fps
    gripper = np.tile(np.linspace(0.0, 1.0, frames_per_seg), n_segments).astype(np.float64)
    eef_velocity = np.zeros((total_frames, 3), dtype=np.float64)
    extractor = StubClipFeatureExtractor(fps=fps, cfg=ClipFeatureConfig())
    episode_meta = {
        "task_text": task_text,
        "allowed_labels": allowed_labels or list(_DEFAULT_ALLOWED_LABELS),
        "label_version": label_version,
        "robot_type": robot_type,
        "fps": fps,
        "episode_duration_sec": duration,
    }
    segments: list[SubtaskSegment] = []
    for i in range(n_segments):
        start = i * frames_per_seg
        end = start + frames_per_seg - 1
        segments.append(SubtaskSegment(
            segment_id=f"s_{i:03d}",
            episode_id="ep_synth",
            start_frame=start, end_frame=end,
            start_time=start / fps, end_time=(end + 1) / fps,
            phase="unlabeled",
            verb=None, object=None, target=None, failure_flags=[],
            label_source="signals_only",
            object_state_unavailable=True, object_track_ids=[],
            label_version="manipulation.v1",
            start_boundary=BoundaryRef(candidate_id=None, time=start / fps,
                                       sources=["episode_start"], score=1.0),
            end_boundary=BoundaryRef(candidate_id=None, time=(end + 1) / fps,
                                     sources=["episode_end"], score=1.0),
            boundary_confidence=1.0,
            vlm_confidence=None, overall_confidence=1.0,
            evidence=None, reviewed=False, reviewer_id=None,
        ))
    return segments, gripper, eef_velocity, extractor, episode_meta
