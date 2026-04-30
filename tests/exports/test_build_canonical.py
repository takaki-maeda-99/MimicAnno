"""build_canonical_episode integrator tests (Phase 5 Task 9, spec §2.3).

Synthetic 3-frame "so101" episode with rotvec ee pose, gripper signal in 0..100
units, and pass-through raw_action columns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.canonical import build_canonical_episode
from mimicanno.exports.profile import ExportProfile
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    BoundaryRef,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    SubtaskSegment,
    TaskInfo,
)


def _write_so101_parquet(p: Path) -> None:
    """3-frame SO101-shaped episode: xyz + rotvec + gripper raw + action.*."""
    p.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": pa.array([0.0, 1 / 30, 2 / 30]),
            "frame_index": pa.array([0, 1, 2]),
            "episode_index": pa.array([0, 0, 0]),
            "observation.state.gripper_pos": pa.array([10.0, 50.0, 90.0]),
            "observation.state.ee_pos": pa.array(
                [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]]
            ),
            "observation.state.ee_rotvec": pa.array(
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
            ),
            "observation.state": pa.array(
                [[0.0] * 6, [0.0] * 6, [0.0] * 6]
            ),  # placeholder for REQUIRED_COLUMNS
            "action.joint_pos": pa.array([[0.0] * 6, [0.1] * 6, [0.2] * 6]),
            "action.gripper_pos": pa.array([0.0, 0.5, 1.0]),
        }
    )
    pq.write_table(table, p)  # type: ignore[no-untyped-call]


def _write_info_json(dataset_root: Path, n_episodes: int = 1) -> None:
    meta = dataset_root / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v3.0",
                "total_episodes": n_episodes,
                "chunks_size": 1000,
                "data_path": (
                    "data/chunk-{chunk_index:03d}/"
                    "episode_{episode_index:06d}.parquet"
                ),
                "video_path": (
                    "videos/{video_key}/chunk-{chunk_index:03d}/"
                    "episode_{episode_index:06d}.mp4"
                ),
                "fps": 30,
                "splits": {"train": f"0:{n_episodes}"},
                "features": {},
            }
        )
    )


def _make_segment(
    *,
    episode_id: str,
    start_frame: int,
    end_frame: int,
    phase: str,
    boundary_score: float = 1.0,
) -> SubtaskSegment:
    b = BoundaryRef(
        candidate_id=None, time=0.0, sources=["episode_start"], score=boundary_score
    )
    e = BoundaryRef(
        candidate_id=None, time=0.0, sources=["episode_end"], score=boundary_score
    )
    return SubtaskSegment(
        segment_id=f"{episode_id}_seg{start_frame}",
        episode_id=episode_id,
        start_frame=start_frame,
        end_frame=end_frame,
        start_time=0.0,
        end_time=0.0,
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


def _make_manifest(*, episode_id: str, run_hash: str = "sha256:" + "0" * 64) -> Manifest:
    return Manifest(
        schema_version="1",
        episode_id=episode_id,
        task=TaskInfo(text="pick the cube", version=None),
        generated_at="2026-04-30T00:00:00Z",
        generator=GeneratorInfo(
            name="mimicanno", cli_version="0.1.0", pipeline_phase=1
        ),
        config_hash="sha256:" + "1" * 64,
        input_hash="sha256:" + "2" * 64,
        run_hash=run_hash,
        model_versions={"vlm": None, "sam3": None},
        pipeline_params={},
        inputs={
            "data_parquet": InputRef(
                path="data/chunk-000/episode_000000.parquet",
                sha256="sha256:" + "3" * 64,
            )
        },
        time_base="parquet_timestamp",
        fps=30.0,
        duration_sec=0.1,
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
        compat={"min_reader_version": 1},
        artifacts=[
            Artifact(
                role="annotation",
                url="annotation.json",
                content_type="application/json",
            )
        ],
    )


def _make_annotation(
    *,
    episode_id: str,
    segments: list[SubtaskSegment],
    run_hash: str = "sha256:" + "0" * 64,
) -> AnnotationResult:
    return AnnotationResult(
        schema_version="1",
        episode_id=episode_id,
        task=TaskInfo(text="pick the cube", version=None),
        generated_at="2026-04-30T00:00:00Z",
        generator=GeneratorInfo(
            name="mimicanno", cli_version="0.1.0", pipeline_phase=1
        ),
        config_hash="sha256:" + "1" * 64,
        input_hash="sha256:" + "2" * 64,
        run_hash=run_hash,
        model_versions={"vlm": None, "sam3": None},
        pipeline_phase=1,
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )


def _make_profile(
    *,
    pass_through_raw_action: bool = True,
    raw_action_columns: list[str] | None = None,
    forbid_unlabeled: bool = False,
) -> ExportProfile:
    """SO101-style profile with explicit raw_action_columns when given."""
    raw_src: dict[str, Any] = {
        "robot_adapter": "generic",
        "pass_through_raw_action": pass_through_raw_action,
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
    }
    if raw_action_columns is not None:
        raw_src["raw_action_columns"] = raw_action_columns

    cfg = {
        "schema_version": "1",
        "name": "test",
        "description": "",
        "source": raw_src,
        "canonical": {
            "delta_basis": "body_frame_t",
            "rotation_repr": "rotvec",
            "gripper_source": "observation",
        },
        "sink": {
            "writer": "lerobot_v3",
            "params": {
                "annotation_prefix": "mimicanno",
                "subtask_registry_path": "meta/subtasks.parquet",
                "extra_per_frame_columns": [],
            },
        },
        "sidecar": {"enabled": True, "path": "meta/mimicanno_segments.parquet"},
        "gates": {
            "require_reviewed": False,
            "forbid_degraded_pipeline": False,
            "forbid_unlabeled_segments": forbid_unlabeled,
        },
    }
    import yaml  # type: ignore[import-untyped]

    p = Path("/tmp") / f"test_profile_{id(cfg)}.yaml"
    p.write_text(yaml.safe_dump(cfg))
    try:
        return ExportProfile.from_yaml(p)
    finally:
        p.unlink(missing_ok=True)


def test_happy_path(tmp_path: Path) -> None:
    parquet_path = (
        tmp_path / "data" / "chunk-000" / "episode_000000.parquet"
    )
    _write_so101_parquet(parquet_path)
    _write_info_json(tmp_path)

    episode_id = "episode_000000"
    segs = [
        _make_segment(
            episode_id=episode_id,
            start_frame=0,
            end_frame=2,  # inclusive; num_frames - 1
            phase="approach",
        )
    ]
    annotation = _make_annotation(episode_id=episode_id, segments=segs)
    manifest = _make_manifest(episode_id=episode_id)
    profile = _make_profile(
        raw_action_columns=["action.joint_pos", "action.gripper_pos"]
    )

    canon = build_canonical_episode(
        dataset_root=tmp_path,
        episode_index=0,
        annotation=annotation,
        manifest=manifest,
        profile=profile,
    )
    assert canon.num_frames == 3
    assert canon.fps == 30.0
    assert canon.episode_index == 0
    assert canon.episode_id == episode_id
    assert canon.ee_pose_world.shape == (3, 6)
    assert canon.ee_delta_6d.shape == (3, 6)
    # Last frame zero-padded
    np.testing.assert_allclose(canon.ee_delta_6d[-1], 0.0, atol=1e-12)
    # Frame 0 -> Frame 1 body-frame Δp_x = 0.1
    np.testing.assert_allclose(canon.ee_delta_6d[0, 0], 0.1, atol=1e-10)
    # Gripper normalized: 10/100, 50/100, 90/100
    np.testing.assert_allclose(
        canon.gripper_normalized, [0.1, 0.5, 0.9], atol=1e-10
    )
    np.testing.assert_allclose(
        canon.gripper_delta, [0.4, 0.4, 0.0], atol=1e-10
    )
    # Provenance
    assert canon.run_hash == manifest.run_hash
    assert canon.config_hash == manifest.config_hash
    assert canon.input_hash == manifest.input_hash
    assert canon.pipeline_phase == 1
    # raw_action carried
    assert canon.raw_action is not None
    # 6 joints + 1 gripper = 7 columns
    assert canon.raw_action.shape == (3, 7)
    assert canon.raw_action_columns == (
        "action.joint_pos",
        "action.gripper_pos",
    )


def test_episode_index_mismatch_raises(tmp_path: Path) -> None:
    parquet_path = (
        tmp_path / "data" / "chunk-000" / "episode_000000.parquet"
    )
    _write_so101_parquet(parquet_path)
    _write_info_json(tmp_path)

    annotation = _make_annotation(
        episode_id="episode_000000",
        segments=[
            _make_segment(
                episode_id="episode_000000", start_frame=0, end_frame=2, phase="approach"
            )
        ],
    )
    manifest = _make_manifest(episode_id="episode_000000")
    profile = _make_profile(pass_through_raw_action=False)

    # Caller asks for episode_index=99 but annotation says episode_index=0
    # via a synthetic mismatch: build wrapping annotation with a different idx.
    # The cleanest way: patch annotation.episode_id to mismatch.
    bad_annotation = _make_annotation(
        episode_id="ep_9999",  # does not match parquet episode 0
        segments=annotation.segments,
    )
    with pytest.raises(MimicAnnoError) as ei:
        build_canonical_episode(
            dataset_root=tmp_path,
            episode_index=0,
            annotation=bad_annotation,
            manifest=manifest,
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_EPISODE_MISMATCH


def test_frame_count_mismatch_raises(tmp_path: Path) -> None:
    parquet_path = (
        tmp_path / "data" / "chunk-000" / "episode_000000.parquet"
    )
    _write_so101_parquet(parquet_path)
    _write_info_json(tmp_path)

    annotation = _make_annotation(
        episode_id="episode_000000",
        segments=[
            # End frame 5 but num_frames = 3 -> mismatch
            _make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=5,
                phase="approach",
            )
        ],
    )
    manifest = _make_manifest(episode_id="episode_000000")
    profile = _make_profile(pass_through_raw_action=False)
    with pytest.raises(MimicAnnoError) as ei:
        build_canonical_episode(
            dataset_root=tmp_path,
            episode_index=0,
            annotation=annotation,
            manifest=manifest,
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_FRAME_COUNT_MISMATCH


def test_raw_action_missing_raises(tmp_path: Path) -> None:
    """Profile demands pass_through but no action.* columns present."""
    parquet_path = (
        tmp_path / "data" / "chunk-000" / "episode_000000.parquet"
    )
    # Build an episode WITHOUT action.* columns.
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": pa.array([0.0, 1 / 30, 2 / 30]),
            "observation.state.gripper_pos": pa.array([10.0, 50.0, 90.0]),
            "observation.state.ee_pos": pa.array(
                [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]]
            ),
            "observation.state.ee_rotvec": pa.array(
                [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
            ),
            "observation.state": pa.array(
                [[0.0] * 6, [0.0] * 6, [0.0] * 6]
            ),
        }
    )
    pq.write_table(table, parquet_path)  # type: ignore[no-untyped-call]
    _write_info_json(tmp_path)

    annotation = _make_annotation(
        episode_id="episode_000000",
        segments=[
            _make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=2,
                phase="approach",
            )
        ],
    )
    manifest = _make_manifest(episode_id="episode_000000")
    # raw_action_columns=None -> auto-detect via action.*; none present -> error
    profile = _make_profile(pass_through_raw_action=True)
    with pytest.raises(MimicAnnoError) as ei:
        build_canonical_episode(
            dataset_root=tmp_path,
            episode_index=0,
            annotation=annotation,
            manifest=manifest,
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_RAW_ACTION_MISSING


def test_gate_unlabeled_present_raises(tmp_path: Path) -> None:
    parquet_path = (
        tmp_path / "data" / "chunk-000" / "episode_000000.parquet"
    )
    _write_so101_parquet(parquet_path)
    _write_info_json(tmp_path)

    annotation = _make_annotation(
        episode_id="episode_000000",
        segments=[
            _make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=2,
                phase="unlabeled",
            )
        ],
    )
    manifest = _make_manifest(episode_id="episode_000000")
    profile = _make_profile(
        pass_through_raw_action=False, forbid_unlabeled=True
    )
    with pytest.raises(MimicAnnoError) as ei:
        build_canonical_episode(
            dataset_root=tmp_path,
            episode_index=0,
            annotation=annotation,
            manifest=manifest,
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_UNLABELED_PRESENT
