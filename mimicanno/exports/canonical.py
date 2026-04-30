"""Canonical IR: CanonicalEpisode + ee_delta_6d / gripper_delta math (spec §2).

Phase 5, Task 7 — provides:

- ``compute_ee_delta_6d`` (spec §2.2 closed-form).
- ``compute_gripper_delta`` (frame-to-frame diff, zero-padded last frame).
- ``CanonicalEpisode`` frozen dataclass skeleton (spec §2.1). The
  ``build_canonical_episode`` integrator lands in Task 9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from mimicanno.exports.so3 import exp_so3, log_so3
from mimicanno.schema import PipelineStatus, SubtaskSegment

DeltaBasis = Literal["body_frame_t", "world", "base"]


def compute_ee_delta_6d(
    pose_world: np.ndarray,
    *,
    basis: DeltaBasis,
) -> np.ndarray:
    """Closed-form ee_delta_6d per spec §2.2.

    Input ``pose_world`` is shape ``(T, 6)`` containing ``[x, y, z, rx, ry, rz]``
    where the rotation triple is an axis-angle rotvec in the world frame.
    Output is ``(T, 6)`` with the last frame padded with zeros. ``T == 1``
    returns all zeros.

    ``basis``:

    - ``body_frame_t``: ``Δp = R_t.T @ (p_{t+1} - p_t)``,
      ``ΔR = R_t.T @ R_{t+1}``, ``Δr = log_so3(ΔR)``.
    - ``world`` / ``base``: ``Δp = p_{t+1} - p_t``,
      ``ΔR = R_{t+1} @ R_t.T`` (left-invariant world delta),
      ``Δr = log_so3(ΔR)``.
    """
    t_count = pose_world.shape[0]
    out = np.zeros((t_count, 6), dtype=np.float64)
    if t_count <= 1:
        return out
    p = pose_world[:, :3]
    r = pose_world[:, 3:6]
    for t in range(t_count - 1):
        r_t = exp_so3(r[t])
        r_tp1 = exp_so3(r[t + 1])
        if basis == "body_frame_t":
            dp = r_t.T @ (p[t + 1] - p[t])
            d_rot = r_t.T @ r_tp1
        elif basis in ("world", "base"):
            dp = p[t + 1] - p[t]
            d_rot = r_tp1 @ r_t.T
        else:
            raise ValueError(f"unknown basis: {basis!r}")
        out[t, :3] = dp
        out[t, 3:6] = log_so3(d_rot)
    return out


def compute_gripper_delta(g: np.ndarray) -> np.ndarray:
    """Frame-to-frame gripper delta with zero-padded last frame."""
    if g.size == 0:
        return np.zeros_like(g)
    out = np.zeros_like(g)
    out[:-1] = np.diff(g)
    return out


@dataclass(frozen=True)
class CanonicalEpisode:
    """Intermediate representation between source dataset and sink writer.

    See spec §2.1 for the full field list. Arrays are stored as ``np.float32``
    by convention (the parquet sink writes float32); intermediate math may use
    float64 and cast at the boundary.
    """

    # Identity
    episode_index: int
    episode_id: str
    fps: float
    num_frames: int

    # Per-frame canonical (T-aligned)
    ee_pose_world: np.ndarray            # (T, 6)
    ee_delta_6d: np.ndarray              # (T, 6)
    gripper_normalized: np.ndarray       # (T,)
    gripper_delta: np.ndarray            # (T,)

    # Per-frame raw (optional pass-through)
    raw_action: np.ndarray | None
    raw_action_columns: tuple[str, ...] | None

    # Per-segment
    segments: tuple[SubtaskSegment, ...]

    # Provenance (read from manifest)
    run_hash: str
    config_hash: str
    input_hash: str
    label_version: str
    pipeline_phase: int
    mimicanno_version: str
    generated_at: str
    pipeline_status: PipelineStatus
