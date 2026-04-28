"""compute_object_signals — image-width-normalized distance/speed (spec §2.5).

Pure numpy. No external dependencies beyond numpy and the propagator dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mimicanno.object_tracker.propagator import GapEvent, Track, TrackSample
from mimicanno.object_tracker.track_id import ROLE


@dataclass(slots=True)
class ObjectSignals:
    """Frame-aligned (length = n_frames) derived signals.

    Frames inside any source track's gap_events are NaN.
    All distances and speeds are in **image-width-normalized** units.
    """

    gripper_object_distance: dict[str, np.ndarray]
    """object_track_id -> per-frame distance.
    NaN where either gripper or object bbox is missing at that frame.
    Dict is empty if no gripper tool track exists."""

    object_speed: dict[str, np.ndarray]
    """object_track_id -> per-frame speed (image-width-normalized / sec).
    NaN where bbox is missing at that frame."""

    object_center: dict[str, np.ndarray]
    """track_id -> per-frame bbox-center, shape [n_frames, 2] in normalized
    image coords. NaN where bbox is missing at that frame. Populated for
    EVERY track (object, target, tool), not just objects."""

    primary_object_track_id: str | None
    primary_target_track_id: str | None
    gripper_tool_track_id: str | None


def _interpolate_centers(
    samples: list[TrackSample], n_frames: int, gap_events: list[GapEvent]
) -> np.ndarray:
    """Per-track linear interpolation in non-gap regions.

    Returns shape (n_frames, 2) with NaN outside interp domain or inside gaps.
    """
    out = np.full((n_frames, 2), np.nan, dtype=np.float64)
    if not samples:
        return out

    sample_frames = np.array([s.frame for s in samples], dtype=np.float64)
    sample_centers = np.array([s.bbox.center for s in samples], dtype=np.float64)  # (N, 2)

    # Build gap mask
    gap_mask = np.zeros(n_frames, dtype=bool)
    for ge in gap_events:
        gap_mask[ge.from_frame : ge.to_frame + 1] = True

    # Interp domain: [first_sample, last_sample] excluding gaps
    first = int(sample_frames[0])
    last = int(sample_frames[-1])
    interp_domain = np.zeros(n_frames, dtype=bool)
    interp_domain[first : last + 1] = True
    interp_domain &= ~gap_mask

    frames_to_interp = np.where(interp_domain)[0]
    if frames_to_interp.size > 0:
        out[frames_to_interp, 0] = np.interp(
            frames_to_interp, sample_frames, sample_centers[:, 0]
        )
        out[frames_to_interp, 1] = np.interp(
            frames_to_interp, sample_frames, sample_centers[:, 1]
        )
    return out


def _find_primary(tracks: list[Track], role: ROLE) -> str | None:
    matches = [t.track_id for t in tracks if t.role == role and t.primary]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"multiple primary tracks for role={role!r}: {matches}")
    return matches[0]


def _compute_speed(
    centers: np.ndarray, fps: float, n_frames: int, image_aspect_ratio: float
) -> np.ndarray:
    """Central-difference speed; boundary frames use one-sided difference.

    centers: shape (n_frames, 2), NaN where missing.
    Returns shape (n_frames,).
    """
    if n_frames == 0:
        return np.empty(0, dtype=np.float64)
    if n_frames == 1:
        return np.array([np.nan], dtype=np.float64)

    prev_centers = np.roll(centers, 1, axis=0)   # prev_centers[t] = centers[t-1]
    next_centers = np.roll(centers, -1, axis=0)  # next_centers[t] = centers[t+1]

    # Central difference (fps/2 factor)
    dx = (next_centers[:, 0] - prev_centers[:, 0]) * (fps / 2.0)
    dy = (next_centers[:, 1] - prev_centers[:, 1]) * (fps / 2.0)

    # Override boundary frames (roll wraps, so t=0 uses centers[-1] as prev, and
    # t=-1 uses centers[0] as next — both invalid)
    dx[0] = (centers[1, 0] - centers[0, 0]) * fps
    dy[0] = (centers[1, 1] - centers[0, 1]) * fps
    dx[-1] = (centers[-1, 0] - centers[-2, 0]) * fps
    dy[-1] = (centers[-1, 1] - centers[-2, 1]) * fps

    # One-sided diffs for use in adjacent-to-gap corrections
    forward_dx = (next_centers[:, 0] - centers[:, 0]) * fps
    forward_dy = (next_centers[:, 1] - centers[:, 1]) * fps
    backward_dx = (centers[:, 0] - prev_centers[:, 0]) * fps
    backward_dy = (centers[:, 1] - prev_centers[:, 1]) * fps

    prev_nan = np.isnan(prev_centers[:, 0])
    next_nan = np.isnan(next_centers[:, 0])

    # Where prev is NaN but next is not: use forward diff
    mask_fwd = prev_nan & ~next_nan
    dx = np.where(mask_fwd, forward_dx, dx)
    dy = np.where(mask_fwd, forward_dy, dy)

    # Where next is NaN but prev is not: use backward diff
    mask_bwd = next_nan & ~prev_nan
    dx = np.where(mask_bwd, backward_dx, dx)
    dy = np.where(mask_bwd, backward_dy, dy)

    # Where current center is NaN: force NaN
    current_nan = np.isnan(centers[:, 0])
    dx[current_nan] = np.nan
    dy[current_nan] = np.nan

    result: np.ndarray = np.sqrt(dx**2 + (dy / image_aspect_ratio) ** 2)
    return result


def compute_object_signals(
    tracks: list[Track],
    *,
    fps: float,
    n_frames: int,
    image_aspect_ratio: float,
) -> ObjectSignals:
    """Compute per-frame signals for all tracks (spec §2.5)."""

    # Step 1: interpolate centers for every track
    all_centers: dict[str, np.ndarray] = {}
    for track in tracks:
        all_centers[track.track_id] = _interpolate_centers(
            track.samples, n_frames, track.gap_events
        )

    # Step 2: identify gripper (primary tool) track
    gripper_tool_track_id = _find_primary(tracks, "tool")
    gripper_centers = (
        all_centers[gripper_tool_track_id] if gripper_tool_track_id is not None else None
    )

    # Step 3: per-object distance + speed
    gripper_object_distance: dict[str, np.ndarray] = {}
    object_speed: dict[str, np.ndarray] = {}

    for track in tracks:
        if track.role == "object":
            obj_centers = all_centers[track.track_id]

            # Distance (only if gripper exists)
            if gripper_centers is not None:
                dx = obj_centers[:, 0] - gripper_centers[:, 0]
                dy = obj_centers[:, 1] - gripper_centers[:, 1]
                gripper_object_distance[track.track_id] = np.sqrt(
                    dx**2 + (dy / image_aspect_ratio) ** 2
                )

            # Speed
            object_speed[track.track_id] = _compute_speed(
                obj_centers, fps, n_frames, image_aspect_ratio
            )

    return ObjectSignals(
        gripper_object_distance=gripper_object_distance,
        object_speed=object_speed,
        object_center=all_centers,
        primary_object_track_id=_find_primary(tracks, "object"),
        primary_target_track_id=_find_primary(tracks, "target"),
        gripper_tool_track_id=gripper_tool_track_id,
    )
