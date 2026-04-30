"""Canonical IR: CanonicalEpisode + ee_delta_6d / gripper_delta math (spec §2).

Phase 5 Task 7 / Task 9:

- ``compute_ee_delta_6d`` (spec §2.2 closed-form).
- ``compute_gripper_delta`` (frame-to-frame diff, zero-padded last frame).
- ``CanonicalEpisode`` frozen dataclass (spec §2.1).
- ``build_canonical_episode`` integrator (spec §2.3).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import yaml  # type: ignore[import-untyped]

from mimicanno.__version__ import __version__ as _MIMICANNO_VERSION  # noqa: N812
from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter
from mimicanno.adapters.generic import GenericAdapter
from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter
from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.dataset_layout import resolve_episode_path
from mimicanno.exports.profile import ExportProfile
from mimicanno.exports.so3 import exp_so3, log_so3, quat_to_rotvec
from mimicanno.io_parquet import load_episode_parquet
from mimicanno.schema import (
    AnnotationResult,
    Manifest,
    PipelineStatus,
    SubtaskSegment,
)

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


# ---------------------------------------------------------------------------
# build_canonical_episode (spec §2.3)
# ---------------------------------------------------------------------------


def _select_adapter(profile: ExportProfile) -> RobotAdapter:
    """Resolve a RobotAdapter from ``profile.source.robot_adapter``.

    Mirrors ``mimicanno.pipeline._select_adapter`` but constructs
    ``GenericAdapter`` from ``profile.source.generic_adapter_config`` (an inline
    YAML mapping carried inside the profile) by writing a transient YAML file
    to a temp dir and reusing ``GenericAdapter.from_yaml``. This avoids
    duplicating the schema-version / column-validation logic.
    """
    name = profile.source.robot_adapter
    if name == "aloha":
        return AlohaAdapter()
    if name == "koch":
        return KochAdapter()
    if name == "so100":
        return SO100Adapter()
    if name == "generic":
        cfg = profile.source.generic_adapter_config
        if cfg is None:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_INVALID,
                "robot_adapter='generic' requires source.generic_adapter_config",
                {"profile_name": profile.name},
            )
        with tempfile.TemporaryDirectory() as td:
            tmp_yaml = Path(td) / "adapter.yaml"
            tmp_yaml.write_text(yaml.safe_dump(cfg))
            return GenericAdapter.from_yaml(tmp_yaml)
    raise MimicAnnoError(
        ErrorCode.EXPORT_PROFILE_INVALID,
        f"unknown robot_adapter {name!r}",
        {"robot_adapter": name},
    )


def _normalize_ee_pose(pose: np.ndarray | None) -> np.ndarray | None:
    """Coerce adapter ``eef_pose`` output to ``(T, 6)`` rotvec form.

    - ``(T, 6)``: pass through (already xyz+rotvec, GenericAdapter v0.2.0).
    - ``(T, 7)``: xyz+quat (xyzw); convert quat -> rotvec.
    - ``None``: return ``None``.
    """
    if pose is None:
        return None
    if pose.ndim != 2:
        raise MimicAnnoError(
            ErrorCode.EXPORT_EE_POSE_UNAVAILABLE,
            f"adapter.eef_pose returned ndim={pose.ndim}, expected 2",
            {"shape": list(pose.shape)},
        )
    if pose.shape[1] == 6:
        return np.asarray(pose, dtype=np.float64)
    if pose.shape[1] == 7:
        xyz = pose[:, :3]
        quat = pose[:, 3:7]
        rv = quat_to_rotvec(quat)
        return np.concatenate([xyz, rv], axis=1).astype(np.float64)
    raise MimicAnnoError(
        ErrorCode.EXPORT_EE_POSE_UNAVAILABLE,
        (
            f"adapter.eef_pose returned shape {pose.shape}; expected (T, 6) "
            f"(xyz+rotvec) or (T, 7) (xyz+quat)"
        ),
        {"shape": list(pose.shape)},
    )


def _resolve_raw_action(
    table: object,  # pa.Table; typed as object to keep imports light
    *,
    explicit_columns: list[str] | None,
) -> tuple[np.ndarray | None, tuple[str, ...] | None]:
    """Read raw_action columns from the parquet table.

    Returns ``(raw_action (T, A), tuple(columns))`` or ``(None, None)`` if no
    matching columns. ``explicit_columns=None`` triggers auto-detection
    (LeRobot v3 convention: all columns matching ``action.*``).
    """
    import pyarrow as pa  # local import; pyarrow is already a dep

    assert isinstance(table, pa.Table)
    if explicit_columns is None:
        cols = [c for c in table.column_names if c == "action" or c.startswith("action.")]
    else:
        cols = list(explicit_columns)
        missing = [c for c in cols if c not in table.column_names]
        if missing:
            raise MimicAnnoError(
                ErrorCode.EXPORT_RAW_ACTION_MISSING,
                f"raw_action_columns missing from parquet: {missing}",
                {"missing_columns": missing},
            )
    if not cols:
        return None, None

    pieces: list[np.ndarray] = []
    for col_name in cols:
        col_values = np.asarray(table.column(col_name).to_pylist())
        if col_values.ndim == 1:
            col_values = col_values.reshape(-1, 1)
        pieces.append(col_values.astype(np.float64))
    return np.concatenate(pieces, axis=1), tuple(cols)


def _apply_gates(
    *,
    annotation: AnnotationResult,
    manifest: Manifest,
    profile: ExportProfile,
) -> None:
    if profile.gates.require_reviewed and any(
        not s.reviewed for s in annotation.segments
    ):
        raise MimicAnnoError(
            ErrorCode.EXPORT_NOT_REVIEWED,
            "gate require_reviewed: at least one segment is not reviewed",
            {"episode_id": annotation.episode_id},
        )
    if (
        profile.gates.forbid_degraded_pipeline
        and manifest.pipeline_status.degraded_from_phase is not None
    ):
        raise MimicAnnoError(
            ErrorCode.EXPORT_PHASE_DOWNGRADE,
            (
                "gate forbid_degraded_pipeline: manifest reports "
                f"degraded_from_phase={manifest.pipeline_status.degraded_from_phase}"
            ),
            {"episode_id": annotation.episode_id},
        )
    if profile.gates.forbid_unlabeled_segments and any(
        s.phase == "unlabeled" for s in annotation.segments
    ):
        raise MimicAnnoError(
            ErrorCode.EXPORT_UNLABELED_PRESENT,
            "gate forbid_unlabeled_segments: at least one segment has phase='unlabeled'",
            {"episode_id": annotation.episode_id},
        )


def build_canonical_episode(
    *,
    dataset_root: Path,
    episode_index: int,
    annotation: AnnotationResult,
    manifest: Manifest,
    profile: ExportProfile,
) -> CanonicalEpisode:
    """Source dataset + mimicanno run -> CanonicalEpisode (spec §2.3)."""
    adapter = _select_adapter(profile)

    parquet_path, _row_filter = resolve_episode_path(
        dataset_root, episode_index=episode_index
    )
    loaded = load_episode_parquet(parquet_path)
    table = loaded.table
    num_frames = table.num_rows
    parquet_episode_id = parquet_path.stem  # mirrors pipeline's episode_id derivation

    if annotation.episode_id != parquet_episode_id:
        raise MimicAnnoError(
            ErrorCode.EXPORT_EPISODE_MISMATCH,
            (
                f"annotation.episode_id={annotation.episode_id!r} does not match "
                f"parquet episode_id={parquet_episode_id!r}"
            ),
            {
                "annotation_episode_id": annotation.episode_id,
                "parquet_episode_id": parquet_episode_id,
                "episode_index": episode_index,
            },
        )

    if not annotation.segments:
        raise MimicAnnoError(
            ErrorCode.EXPORT_FRAME_COUNT_MISMATCH,
            "annotation has no segments",
            {"episode_id": annotation.episode_id},
        )
    last_end = annotation.segments[-1].end_frame
    if last_end != num_frames - 1:
        raise MimicAnnoError(
            ErrorCode.EXPORT_FRAME_COUNT_MISMATCH,
            (
                f"annotation.segments[-1].end_frame={last_end} does not match "
                f"parquet num_frames-1={num_frames - 1}"
            ),
            {
                "last_end_frame": last_end,
                "num_frames": num_frames,
                "episode_id": annotation.episode_id,
            },
        )

    # Apply gates on metadata before computing canonical arrays (cheap).
    _apply_gates(annotation=annotation, manifest=manifest, profile=profile)

    # ee_pose_world (T, 6)
    pose_raw = adapter.eef_pose(table)
    pose = _normalize_ee_pose(pose_raw)
    if pose is None:
        raise MimicAnnoError(
            ErrorCode.EXPORT_EE_POSE_UNAVAILABLE,
            f"adapter {profile.source.robot_adapter!r} returned no eef_pose",
            {"adapter": profile.source.robot_adapter},
        )

    ee_delta = compute_ee_delta_6d(pose, basis=profile.canonical.delta_basis)

    # Gripper signal
    gripper = adapter.gripper_signal(table).astype(np.float64)
    gripper_d = compute_gripper_delta(gripper)

    # Optional raw_action pass-through
    raw_action: np.ndarray | None
    raw_action_columns: tuple[str, ...] | None
    if profile.source.pass_through_raw_action:
        raw_action, raw_action_columns = _resolve_raw_action(
            table, explicit_columns=profile.source.raw_action_columns
        )
        if raw_action is None:
            raise MimicAnnoError(
                ErrorCode.EXPORT_RAW_ACTION_MISSING,
                (
                    "profile demands pass_through_raw_action=true but no "
                    "action.* columns are present in the parquet"
                ),
                {"episode_id": annotation.episode_id},
            )
    else:
        raw_action = None
        raw_action_columns = None

    # Cast to float32 at the IR boundary (spec §2.1).
    pose32 = pose.astype(np.float32)
    ee_delta32 = ee_delta.astype(np.float32)
    gripper32 = gripper.astype(np.float32)
    gripper_d32 = gripper_d.astype(np.float32)
    raw_action32 = raw_action.astype(np.float32) if raw_action is not None else None

    # label_version: take from the first segment (constant per spec).
    label_version = annotation.segments[0].label_version

    return CanonicalEpisode(
        episode_index=episode_index,
        episode_id=parquet_episode_id,
        fps=manifest.fps,
        num_frames=num_frames,
        ee_pose_world=pose32,
        ee_delta_6d=ee_delta32,
        gripper_normalized=gripper32,
        gripper_delta=gripper_d32,
        raw_action=raw_action32,
        raw_action_columns=raw_action_columns,
        segments=tuple(annotation.segments),
        run_hash=manifest.run_hash,
        config_hash=manifest.config_hash,
        input_hash=manifest.input_hash,
        label_version=label_version,
        pipeline_phase=annotation.pipeline_phase,
        mimicanno_version=_MIMICANNO_VERSION,
        generated_at=manifest.generated_at,
        pipeline_status=manifest.pipeline_status,
    )
