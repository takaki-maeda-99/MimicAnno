"""Phase 2 clip-feature extraction (spec §2.7, §3.1).

Pure functions over (segment indices, signal arrays, config) for
keyframe selection and 5-scalar robot-state summary, plus a
ClipFeatureExtractor class that composes them with frame I/O via
io_video.extract_frames_at_indices.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TypedDict

import numpy as np

from mimicanno.config import ClipFeatureConfig


class RobotStateSummary(TypedDict):
    duration_sec: float
    mean_eef_speed_mps: Optional[float]
    gripper_open_fraction: float
    gripper_transitions: int
    dwell_fraction: Optional[float]


def compute_keyframe_offsets(start_frame: int, end_frame: int, k: int) -> list[int]:
    """Return K_effective frame indices in temporal order, evenly spaced
    between start_frame and end_frame inclusive (spec §2.7).

    K_effective = min(k, end_frame - start_frame + 1). The K_effective == 1
    branch returns [start_frame] explicitly because the formula is undefined
    (denominator 0) in that case.
    """
    if k < 1:
        raise ValueError(f"keyframes_per_segment must be >= 1, got {k}")
    span = end_frame - start_frame + 1
    if span < 1:
        raise ValueError(f"end_frame {end_frame} must be >= start_frame {start_frame}")
    k_eff = min(k, span)
    if k_eff == 1:
        return [start_frame]
    return [
        start_frame + round(i * (end_frame - start_frame) / (k_eff - 1))
        for i in range(k_eff)
    ]


def _count_crossings(values: np.ndarray, threshold: float) -> int:
    """Count threshold crossings (state flips). For values [0, 1, 0, 1, 0]
    with threshold 0.5, returns 4."""
    above = values >= threshold
    flips = np.diff(above.astype(np.int8))
    return int(np.sum(flips != 0))


def compute_robot_state_summary(
    *,
    start_frame: int,
    end_frame: int,
    fps: float,
    gripper: np.ndarray,
    eef_velocity: Optional[np.ndarray],
    cfg: ClipFeatureConfig,
) -> RobotStateSummary:
    """5-scalar robot-state summary for one segment (spec §3.1)."""
    seg = slice(start_frame, end_frame + 1)
    g = gripper[seg]
    duration_sec = (end_frame - start_frame + 1) / fps if fps > 0 else 0.0

    open_mask = g >= cfg.gripper_open_threshold
    gripper_open_fraction = float(np.mean(open_mask)) if g.size > 0 else 0.0
    gripper_transitions = _count_crossings(g, cfg.gripper_open_threshold)

    mean_speed: Optional[float]
    dwell_fraction: Optional[float]
    if eef_velocity is None:
        mean_speed = None
        dwell_fraction = None
    else:
        v = eef_velocity[seg]
        speed = np.linalg.norm(v, axis=-1) if v.ndim > 1 else np.abs(v)
        mean_speed = float(np.mean(speed)) if speed.size > 0 else 0.0
        dwell_mask = speed < cfg.dwell_speed_threshold_mps
        dwell_fraction = float(np.mean(dwell_mask)) if speed.size > 0 else 0.0

    return RobotStateSummary(
        duration_sec=duration_sec,
        mean_eef_speed_mps=mean_speed,
        gripper_open_fraction=gripper_open_fraction,
        gripper_transitions=gripper_transitions,
        dwell_fraction=dwell_fraction,
    )


@dataclass(slots=True)
class ClipFeatures:
    keyframes: list[np.ndarray]
    keyframe_offsets_sec: list[float]
    robot_state_summary: RobotStateSummary


class ClipFeatureExtractor:
    """Composes keyframe extraction + scalar summary for one segment.

    Stateless — each call to `.extract()` is independent. The caller
    (orchestrator §2.3) constructs one extractor per run."""

    def __init__(
        self, video_path: Path, fps: float,
        clip_features_config: ClipFeatureConfig, image_size_px: int,
    ) -> None:
        self._video_path = video_path
        self._fps = fps
        self._cfg = clip_features_config
        self._image_size_px = image_size_px

    def extract(
        self, segment: "SubtaskSegment",
        gripper: np.ndarray, eef_velocity: Optional[np.ndarray],
        keyframes_per_segment: int,
    ) -> ClipFeatures:
        from mimicanno.io_video import extract_frames_at_indices  # lazy: avoids circular import at module init

        offsets_frames = compute_keyframe_offsets(
            segment.start_frame, segment.end_frame, keyframes_per_segment,
        )
        frames = extract_frames_at_indices(
            self._video_path, offsets_frames, long_edge_px=self._image_size_px,
        )
        offsets_sec = [(f - segment.start_frame) / self._fps for f in offsets_frames]
        summary = compute_robot_state_summary(
            start_frame=segment.start_frame, end_frame=segment.end_frame,
            fps=self._fps, gripper=gripper, eef_velocity=eef_velocity,
            cfg=self._cfg,
        )
        return ClipFeatures(
            keyframes=frames,
            keyframe_offsets_sec=offsets_sec,
            robot_state_summary=summary,
        )
