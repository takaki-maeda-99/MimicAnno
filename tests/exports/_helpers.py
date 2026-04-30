"""Shared synthetic builders for Phase 5 sink-writer tests (Tasks 11-16).

Avoids depending on the mini_so101 fixture (Task 24) by constructing a minimal
LeRobot v3 dataset + CanonicalEpisode + ExportProfile entirely in-memory /
under a pytest tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import yaml  # type: ignore[import-untyped]

from mimicanno.exports.canonical import CanonicalEpisode
from mimicanno.exports.profile import ExportProfile
from mimicanno.schema import (
    BoundaryRef,
    PipelineStatus,
    SubtaskSegment,
)


def make_segment(
    *,
    episode_id: str,
    start_frame: int,
    end_frame: int,
    phase: str,
    boundary_score: float = 0.9,
) -> SubtaskSegment:
    b = BoundaryRef(
        candidate_id=None, time=0.0, sources=["episode_start"], score=boundary_score
    )
    e = BoundaryRef(
        candidate_id=None, time=0.0, sources=["episode_end"], score=boundary_score
    )
    return SubtaskSegment(
        segment_id=f"{episode_id}_seg{start_frame}_{end_frame}",
        episode_id=episode_id,
        start_frame=start_frame,
        end_frame=end_frame,
        start_time=float(start_frame) / 30.0,
        end_time=float(end_frame) / 30.0,
        phase=phase,
        verb=None,
        object=None,
        target=None,
        failure_flags=[],
        label_source="signals_only",
        object_state_unavailable=True,
        object_track_ids=[],
        label_version="manipulation.v1",
        start_boundary=b,
        end_boundary=e,
        boundary_confidence=boundary_score,
        vlm_confidence=None,
        overall_confidence=0.0,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )


def make_canonical_episode(
    *,
    episode_index: int,
    num_frames: int = 3,
    segments: list[SubtaskSegment] | None = None,
    raw_action: bool = False,
) -> CanonicalEpisode:
    episode_id = f"episode_{episode_index:06d}"
    if segments is None:
        segments = [
            make_segment(
                episode_id=episode_id,
                start_frame=0,
                end_frame=num_frames - 1,
                phase="approach",
            )
        ]
    pose = np.zeros((num_frames, 6), dtype=np.float32)
    pose[:, 0] = np.arange(num_frames, dtype=np.float32) * 0.1
    delta = np.zeros((num_frames, 6), dtype=np.float32)
    delta[:-1, 0] = 0.1
    gripper = np.linspace(0.1, 0.9, num_frames, dtype=np.float32)
    gripper_d = np.zeros_like(gripper)
    gripper_d[:-1] = np.diff(gripper)
    raw = (
        np.arange(num_frames * 7, dtype=np.float32).reshape(num_frames, 7)
        if raw_action
        else None
    )
    raw_cols = ("action.joint_pos", "action.gripper_pos") if raw_action else None
    return CanonicalEpisode(
        episode_index=episode_index,
        episode_id=episode_id,
        fps=30.0,
        num_frames=num_frames,
        ee_pose_world=pose,
        ee_delta_6d=delta,
        gripper_normalized=gripper,
        gripper_delta=gripper_d,
        raw_action=raw,
        raw_action_columns=raw_cols,
        segments=tuple(segments),
        run_hash="sha256:" + "0" * 64,
        config_hash="sha256:" + "1" * 64,
        input_hash="sha256:" + "2" * 64,
        label_version="manipulation.v1",
        pipeline_phase=1,
        mimicanno_version="0.1.0",
        generated_at="2026-04-30T00:00:00Z",
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
    )


def write_source_dataset(
    root: Path,
    *,
    episodes: list[CanonicalEpisode],
    extra_episode_columns: dict[str, list[Any]] | None = None,
    bare_collision_columns: bool = False,
) -> None:
    """Build a 1-chunk LeRobot v3 dataset under ``root`` covering ``episodes``.

    - ``data/chunk-000/episode_NNNNNN.parquet`` per episode (bare 6-DoF state)
    - ``meta/info.json`` with v3 templates + `features` for the source columns
    - ``meta/episodes/chunk-000/file-000.parquet`` with one row per episode

    ``extra_episode_columns``: extra columns to add to the per-episode parquet
    (e.g. to test bare-prefix collision in Task 14).
    ``bare_collision_columns``: when True, adds bare ``subtask_names`` etc.
    list-columns to the per-episode parquet.
    """
    (root / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (root / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)

    for ep in episodes:
        path = (
            root
            / "data"
            / "chunk-000"
            / f"episode_{ep.episode_index:06d}.parquet"
        )
        n = ep.num_frames
        table = pa.table(
            {
                "timestamp": pa.array(
                    [float(i) / ep.fps for i in range(n)], type=pa.float64()
                ),
                "frame_index": pa.array(list(range(n)), type=pa.int64()),
                "episode_index": pa.array(
                    [ep.episode_index] * n, type=pa.int64()
                ),
                "observation.state.gripper_pos": pa.array(
                    [float(g * 100.0) for g in ep.gripper_normalized.tolist()],
                    type=pa.float32(),
                ),
                "observation.state.ee_pos": pa.array(
                    ep.ee_pose_world[:, :3].tolist(),
                    type=pa.list_(pa.float32(), 3),
                ),
                "observation.state.ee_rotvec": pa.array(
                    ep.ee_pose_world[:, 3:6].tolist(),
                    type=pa.list_(pa.float32(), 3),
                ),
                "observation.state": pa.array(
                    [[0.0] * 6 for _ in range(n)], type=pa.list_(pa.float32(), 6)
                ),
                "action.joint_pos": pa.array(
                    [[0.0] * 6 for _ in range(n)], type=pa.list_(pa.float32(), 6)
                ),
                "action.gripper_pos": pa.array(
                    [0.0] * n, type=pa.float32()
                ),
            }
        )
        pq.write_table(table, path)  # type: ignore[no-untyped-call]

    info = {
        "codebase_version": "v3.0",
        "total_episodes": len(episodes),
        "total_frames": sum(ep.num_frames for ep in episodes),
        "chunks_size": 1000,
        "fps": 30,
        "splits": {"train": f"0:{len(episodes)}"},
        "data_path": (
            "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet"
        ),
        "video_path": (
            "videos/{video_key}/chunk-{chunk_index:03d}/"
            "episode_{episode_index:06d}.mp4"
        ),
        "features": {
            "observation.state": {
                "dtype": "float32",
                "shape": [6],
                "names": None,
            },
            "action.joint_pos": {
                "dtype": "float32",
                "shape": [6],
                "names": None,
            },
        },
    }
    (root / "meta" / "info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )

    ep_cols: dict[str, Any] = {
        "episode_index": pa.array(
            [ep.episode_index for ep in episodes], type=pa.int64()
        ),
        "length": pa.array(
            [ep.num_frames for ep in episodes], type=pa.int64()
        ),
        "tasks": pa.array(
            [["pick the cube"] for _ in episodes], type=pa.list_(pa.string())
        ),
    }
    if extra_episode_columns is not None:
        for name, values in extra_episode_columns.items():
            ep_cols[name] = pa.array(values)
    if bare_collision_columns:
        ep_cols["subtask_names"] = pa.array(
            [["existing"] for _ in episodes], type=pa.list_(pa.string())
        )
        ep_cols["subtask_start_frames"] = pa.array(
            [[0] for _ in episodes], type=pa.list_(pa.int64())
        )
        ep_cols["subtask_end_frames"] = pa.array(
            [[ep.num_frames - 1] for ep in episodes], type=pa.list_(pa.int64())
        )
    pq.write_table(  # type: ignore[no-untyped-call]
        pa.table(ep_cols),
        root / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
    )


def make_profile(
    *,
    annotation_prefix: str | None = "mimicanno",
    extra_per_frame_columns: list[dict[str, Any]] | None = None,
    tmp_dir: Path | None = None,
) -> ExportProfile:
    if extra_per_frame_columns is None:
        extra_per_frame_columns = [
            {
                "name": "mimicanno.ee_delta_6d",
                "source": "ee_delta_6d",
                "dtype": "float32",
            },
            {
                "name": "mimicanno.gripper_normalized",
                "source": "gripper_normalized",
                "dtype": "float32",
            },
            {
                "name": "mimicanno.gripper_delta",
                "source": "gripper_delta",
                "dtype": "float32",
            },
        ]
    cfg = {
        "schema_version": "1",
        "name": "test",
        "description": "",
        "source": {
            "robot_adapter": "generic",
            "pass_through_raw_action": False,
            "generic_adapter_config": {
                "schema_version": "0.2.0",
                "name": "so101",
                "gripper_column": "observation.state.gripper_pos",
                "gripper_scale_min": 0.0,
                "gripper_scale_max": 100.0,
                "eef_xyz_column": "observation.state.ee_pos",
                "eef_rotvec_column": "observation.state.ee_rotvec",
                "eef_quat_column": None,
            },
        },
        "canonical": {
            "delta_basis": "body_frame_t",
            "rotation_repr": "rotvec",
            "gripper_source": "observation",
        },
        "sink": {
            "writer": "lerobot_v3",
            "params": {
                "annotation_prefix": annotation_prefix,
                "subtask_registry_path": "meta/subtasks.parquet",
                "extra_per_frame_columns": extra_per_frame_columns,
            },
        },
        "sidecar": {"enabled": True, "path": "meta/mimicanno_segments.parquet"},
        "gates": {
            "require_reviewed": False,
            "forbid_degraded_pipeline": False,
            "forbid_unlabeled_segments": False,
        },
    }
    base = tmp_dir if tmp_dir is not None else Path("/tmp")
    p = base / f"_test_profile_{id(cfg)}.yaml"
    p.write_text(yaml.safe_dump(cfg))
    try:
        return ExportProfile.from_yaml(p)
    finally:
        p.unlink(missing_ok=True)
