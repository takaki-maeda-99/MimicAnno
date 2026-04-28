"""Phase 2 clip-feature extraction (spec §2.7, §3.1).

Pure functions over (segment indices, signal arrays, config) for
keyframe selection and 5-scalar robot-state summary, plus a
ClipFeatureExtractor class that composes them with frame I/O via
io_video.extract_frames_at_indices.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import numpy as np

from mimicanno.config import ClipFeatureConfig
from mimicanno.object_tracker.propagator import BBox, GapEvent, Track

if TYPE_CHECKING:
    from mimicanno.config import TrackingConfig
    from mimicanno.object_tracker.signals import ObjectSignals
    from mimicanno.schema import ObjectStateSummary, SubtaskSegment


class RobotStateSummary(TypedDict):
    duration_sec: float
    mean_eef_speed_mps: float | None
    gripper_open_fraction: float
    gripper_transitions: int
    dwell_fraction: float | None


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
    eef_velocity: np.ndarray | None,
    cfg: ClipFeatureConfig,
) -> RobotStateSummary:
    """5-scalar robot-state summary for one segment (spec §3.1)."""
    seg = slice(start_frame, end_frame + 1)
    g = gripper[seg]
    duration_sec = (end_frame - start_frame + 1) / fps if fps > 0 else 0.0

    open_mask = g >= cfg.gripper_open_threshold
    gripper_open_fraction = float(np.mean(open_mask)) if g.size > 0 else 0.0
    gripper_transitions = _count_crossings(g, cfg.gripper_open_threshold)

    mean_speed: float | None
    dwell_fraction: float | None
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
    object_state_summary: ObjectStateSummary | None = field(default=None)


def _is_in_gap(gap_events: list[GapEvent], t: int) -> bool:
    """Return True iff frame t falls inside any gap_event."""
    return any(gap.from_frame <= t <= gap.to_frame for gap in gap_events)


def _bbox_at_frame(track: Track, t: int) -> BBox | None:
    """Interpolate bbox (x, y, w, h) at frame t for the given track.

    Returns None if:
    - t is inside any gap_event of the track, OR
    - no sample exists with frame <= t, OR
    - no sample exists with frame >= t (no extrapolation).

    If a sample exists exactly at t, its bbox is returned directly.
    Otherwise, linearly interpolates between the bracketing samples.
    """
    if _is_in_gap(track.gap_events, t):
        return None

    samples = track.samples
    if not samples:
        return None

    # Find the largest-frame sample with frame <= t and smallest-frame with frame >= t
    s_lo = None
    s_hi = None
    for s in samples:
        if s.frame <= t and (s_lo is None or s.frame > s_lo.frame):
            s_lo = s
        if s.frame >= t and (s_hi is None or s.frame < s_hi.frame):
            s_hi = s

    if s_lo is None or s_hi is None:
        return None

    if s_lo.frame == t:
        return s_lo.bbox
    if s_hi.frame == t:
        return s_hi.bbox

    # Linear interpolation
    alpha = (t - s_lo.frame) / (s_hi.frame - s_lo.frame)
    x = (1 - alpha) * s_lo.bbox.x + alpha * s_hi.bbox.x
    y = (1 - alpha) * s_lo.bbox.y + alpha * s_hi.bbox.y
    w = (1 - alpha) * s_lo.bbox.w + alpha * s_hi.bbox.w
    h = (1 - alpha) * s_lo.bbox.h + alpha * s_hi.bbox.h
    return BBox(x=x, y=y, w=w, h=h)


def compute_object_state_summary(
    tracks: list[Track],
    *,
    segment_start_frame: int,
    segment_end_frame: int,
    object_signals: ObjectSignals,
    config: TrackingConfig,
    image_aspect_ratio: float | None = None,
) -> ObjectStateSummary | None:
    """Compute per-segment object/target/tool state summary (spec §5.2).

    Returns None when the primary object is not visible enough in the segment
    (triggers per-segment fallback in Task 13).

    Args:
        tracks: All Track objects for the episode.
        segment_start_frame: First frame of the segment (inclusive).
        segment_end_frame: Last frame of the segment (inclusive).
        object_signals: Pre-computed ObjectSignals from compute_object_signals.
        config: TrackingConfig with visibility_threshold and image_aspect_ratio_default.
        image_aspect_ratio: Override for aspect ratio; if None, reads from
            config.image_aspect_ratio_default. The orchestrator (Task 19) may
            pass an episode-derived aspect by setting this explicitly.
    """
    from mimicanno.schema import ObjectStateSummary

    aspect = image_aspect_ratio if image_aspect_ratio is not None else config.image_aspect_ratio_default
    segment_length = segment_end_frame - segment_start_frame + 1

    # Step 1: Visibility filter
    object_prompts: list[str] = []
    target_prompts: list[str] = []
    tool_prompts: list[str] = []
    visible_track_ids: list[str] = []

    for track in tracks:
        # Count non-gap frames within [segment_start_frame, segment_end_frame]
        gap_overlap = 0
        for gap in track.gap_events:
            overlap = max(0, min(gap.to_frame, segment_end_frame) - max(gap.from_frame, segment_start_frame) + 1)
            gap_overlap += overlap
        non_gap_count = segment_length - gap_overlap
        visible_ratio = non_gap_count / segment_length if segment_length > 0 else 0.0

        if visible_ratio >= config.visibility_threshold:
            visible_track_ids.append(track.track_id)
            if track.role == "object" and track.prompt not in object_prompts:
                object_prompts.append(track.prompt)
            elif track.role == "target" and track.prompt not in target_prompts:
                target_prompts.append(track.prompt)
            elif track.role == "tool" and track.prompt not in tool_prompts:
                tool_prompts.append(track.prompt)

    # Step 2 + 3: Primary tracks; no primary object (or not visible enough) → None
    primary_object_track: Track | None = None
    primary_target_track: Track | None = None

    for track in tracks:
        if track.role == "object" and track.primary:
            primary_object_track = track
        elif track.role == "target" and track.primary:
            primary_target_track = track

    if primary_object_track is None:
        return None
    if primary_object_track.prompt not in object_prompts:
        return None

    # Step 4: Gripper-object distances
    seg_slice = slice(segment_start_frame, segment_end_frame + 1)
    dist_at_start: float | None = None
    dist_at_end: float | None = None
    dist_min: float | None = None

    if object_signals.gripper_tool_track_id is not None:
        dist_arr = object_signals.gripper_object_distance.get(primary_object_track.track_id)
        if dist_arr is not None:
            seg_dist = dist_arr[seg_slice]
            valid = seg_dist[~np.isnan(seg_dist)]
            if len(valid) > 0:
                dist_at_start = float(valid[0])
                dist_at_end = float(valid[-1])
                dist_min = float(np.min(valid))

    # Step 5: Primary object motion
    speed_arr = object_signals.object_speed.get(primary_object_track.track_id)
    primary_max_speed: float | None = None
    if speed_arr is not None:
        seg_speed = speed_arr[seg_slice]
        if not np.all(np.isnan(seg_speed)):
            primary_max_speed = float(np.nanmax(seg_speed))

    center_arr = object_signals.object_center.get(primary_object_track.track_id)
    primary_displacement: float | None = None
    if center_arr is not None:
        total_disp = 0.0
        has_pair = False
        for t in range(segment_start_frame, segment_end_frame):
            c0 = center_arr[t]
            c1 = center_arr[t + 1]
            if not np.isnan(c0[0]) and not np.isnan(c1[0]):
                dx = c1[0] - c0[0]
                dy = c1[1] - c0[1]
                total_disp += math.sqrt(dx**2 + (dy / aspect) ** 2)
                has_pair = True
        if has_pair:
            primary_displacement = total_disp

    # Step 6: Object-at-target proxy
    at_target_at_end: bool | None = None
    if primary_target_track is not None:
        obj_bbox = _bbox_at_frame(primary_object_track, segment_end_frame)
        tgt_bbox = _bbox_at_frame(primary_target_track, segment_end_frame)
        if obj_bbox is not None and tgt_bbox is not None:
            at_target_at_end = obj_bbox.iou(tgt_bbox) > 0.05

    return ObjectStateSummary(
        object_prompts=object_prompts,
        target_prompts=target_prompts,
        tool_prompts=tool_prompts,
        visible_track_ids=visible_track_ids,
        gripper_object_distance_at_start=dist_at_start,
        gripper_object_distance_at_end=dist_at_end,
        gripper_object_distance_min=dist_min,
        primary_object_displacement=primary_displacement,
        primary_object_max_speed=primary_max_speed,
        primary_object_at_target_at_end=at_target_at_end,
    )


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
        self, segment: SubtaskSegment,
        gripper: np.ndarray, eef_velocity: np.ndarray | None,
        keyframes_per_segment: int,
    ) -> ClipFeatures:
        from mimicanno.io_video import (
            extract_frames_at_indices,  # lazy: avoids circular import at module init
        )

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
