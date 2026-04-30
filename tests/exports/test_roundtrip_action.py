"""RT-2: action round-trip test (Phase 5 Task 27, spec §10.2).

Synthesises a known ``CanonicalEpisode`` with non-trivial per-frame arrays
(``ee_pose_world`` following a clear trajectory, ``gripper_normalized``
sweeping 0 → 1, computed ``gripper_delta``), runs the sink writer to a
``tmp_path`` dataset, then reads back the per-episode data parquet and
reconstructs the arrays. Asserts ``np.allclose`` (atol=1e-6, rtol=1e-5).

Tests all 3 ``delta_basis`` modes (``body_frame_t``, ``world``, ``base``)
since the spec requires distinct deltas under non-zero rotations. The sink
itself is delta-basis-agnostic — it round-trips whatever array the
CanonicalEpisode carries — but the test explicitly recomputes ee_delta_6d
via ``compute_ee_delta_6d`` for each mode to confirm the basis branch
works through the full builder + sink path.

Note: ``ee_pose_world`` is not in the default ``extra_per_frame_columns``
(only ``ee_delta_6d`` / ``gripper_normalized`` / ``gripper_delta`` are), so
we do not assert pose round-trip — only the delta + gripper signals that
the profile actually writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow.parquet as pq

from mimicanno.exports.canonical import (
    CanonicalEpisode,
    compute_ee_delta_6d,
    compute_gripper_delta,
)
from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from mimicanno.schema import BoundaryRef, PipelineStatus, SubtaskSegment
from tests.exports._helpers import make_profile, write_source_dataset


def _build_pose_trajectory(num_frames: int) -> np.ndarray:
    """A trajectory with both translation and rotation — non-trivial enough that
    the three ``delta_basis`` modes produce distinct deltas."""
    rng = np.random.default_rng(seed=20260430)
    pose = np.zeros((num_frames, 6), dtype=np.float64)
    # Linear translation along x with some y/z modulation.
    t = np.linspace(0.0, 1.0, num_frames, dtype=np.float64)
    pose[:, 0] = t
    pose[:, 1] = 0.5 * np.sin(2 * np.pi * t)
    pose[:, 2] = 0.25 * np.cos(np.pi * t)
    # Rotation: monotonic rotvec around mostly z, with a small x/y component.
    pose[:, 3] = 0.1 * t
    pose[:, 4] = 0.05 * t * t
    pose[:, 5] = (np.pi / 2) * t  # 0 -> pi/2 yaw
    # Tiny noise to keep matrices well-conditioned without breaking determinism.
    pose += 1e-6 * rng.standard_normal(pose.shape)
    return pose


def _build_canonical_episode_with_basis(
    *,
    episode_index: int,
    num_frames: int,
    delta_basis: Literal["body_frame_t", "world", "base"],
) -> CanonicalEpisode:
    """Build a CanonicalEpisode with ee_delta_6d computed for ``delta_basis``.

    Gripper is a 0..1 linear sweep; gripper_delta is the canonical diff.
    """
    pose64 = _build_pose_trajectory(num_frames)
    delta64 = compute_ee_delta_6d(pose64, basis=delta_basis)
    gripper64 = np.linspace(0.0, 1.0, num_frames, dtype=np.float64)
    gripper_d64 = compute_gripper_delta(gripper64)

    episode_id = f"episode_{episode_index:06d}"
    seg = SubtaskSegment(
        segment_id=f"{episode_id}_seg00",
        episode_id=episode_id,
        start_frame=0,
        end_frame=num_frames - 1,
        start_time=0.0,
        end_time=(num_frames - 1) / 30.0,
        phase="approach",
        verb=None,
        object=None,
        target=None,
        failure_flags=[],
        label_source="signals_only",
        object_state_unavailable=True,
        object_track_ids=[],
        label_version="manipulation.v1",
        start_boundary=BoundaryRef(
            candidate_id=None, time=0.0, sources=["episode_start"], score=1.0
        ),
        end_boundary=BoundaryRef(
            candidate_id=None,
            time=(num_frames - 1) / 30.0,
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

    return CanonicalEpisode(
        episode_index=episode_index,
        episode_id=episode_id,
        fps=30.0,
        num_frames=num_frames,
        ee_pose_world=pose64.astype(np.float32),
        ee_delta_6d=delta64.astype(np.float32),
        gripper_normalized=gripper64.astype(np.float32),
        gripper_delta=gripper_d64.astype(np.float32),
        raw_action=None,
        raw_action_columns=None,
        segments=(seg,),
        run_hash="sha256:" + "0" * 64,
        config_hash="sha256:" + "1" * 64,
        input_hash="sha256:" + "2" * 64,
        label_version="manipulation.v1",
        pipeline_phase=4,
        mimicanno_version="0.1.0",
        generated_at="2026-04-30T00:00:00Z",
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
    )


def _read_data_parquet_arrays(
    out_dir: Path, episode_index: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read the per-frame parquet and return (ee_delta_6d, gripper_normalized,
    gripper_delta) arrays."""
    path = (
        out_dir
        / "data"
        / f"chunk-{episode_index // 1000:03d}"
        / f"episode_{episode_index:06d}.parquet"
    )
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    ee_delta = np.asarray(
        table.column("mimicanno.ee_delta_6d").to_pylist(), dtype=np.float64
    )
    gripper = np.asarray(
        table.column("mimicanno.gripper_normalized").to_pylist(),
        dtype=np.float64,
    )
    gripper_d = np.asarray(
        table.column("mimicanno.gripper_delta").to_pylist(), dtype=np.float64
    )
    return ee_delta, gripper, gripper_d


def _round_trip_episode(
    tmp_path: Path,
    *,
    delta_basis: Literal["body_frame_t", "world", "base"],
    num_frames: int = 10,
) -> tuple[CanonicalEpisode, np.ndarray, np.ndarray, np.ndarray]:
    """Build the episode for ``delta_basis``, write it through the sink, and
    return the original episode + the three round-tripped arrays."""
    ep = _build_canonical_episode_with_basis(
        episode_index=0, num_frames=num_frames, delta_basis=delta_basis
    )
    src = tmp_path / "src"
    src.mkdir(parents=True)
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir(parents=True)
    profile = make_profile(tmp_dir=tmp_path)

    writer = LeRobotV3SinkWriter()
    writer.write_all(
        out_dir=out, episodes=[ep], profile=profile, source_dataset=src
    )

    ee_delta_rt, gripper_rt, gripper_d_rt = _read_data_parquet_arrays(out, 0)
    return ep, ee_delta_rt, gripper_rt, gripper_d_rt


def test_action_round_trip_body_frame_t(tmp_path: Path) -> None:
    ep, ee_delta_rt, gripper_rt, gripper_d_rt = _round_trip_episode(
        tmp_path, delta_basis="body_frame_t"
    )
    np.testing.assert_allclose(ee_delta_rt, ep.ee_delta_6d, atol=1e-6, rtol=1e-5)
    np.testing.assert_allclose(
        gripper_rt, ep.gripper_normalized, atol=1e-6, rtol=1e-5
    )
    np.testing.assert_allclose(
        gripper_d_rt, ep.gripper_delta, atol=1e-6, rtol=1e-5
    )


def test_action_round_trip_world(tmp_path: Path) -> None:
    ep, ee_delta_rt, gripper_rt, gripper_d_rt = _round_trip_episode(
        tmp_path, delta_basis="world"
    )
    np.testing.assert_allclose(ee_delta_rt, ep.ee_delta_6d, atol=1e-6, rtol=1e-5)
    np.testing.assert_allclose(
        gripper_rt, ep.gripper_normalized, atol=1e-6, rtol=1e-5
    )
    np.testing.assert_allclose(
        gripper_d_rt, ep.gripper_delta, atol=1e-6, rtol=1e-5
    )


def test_action_round_trip_base(tmp_path: Path) -> None:
    ep, ee_delta_rt, gripper_rt, gripper_d_rt = _round_trip_episode(
        tmp_path, delta_basis="base"
    )
    np.testing.assert_allclose(ee_delta_rt, ep.ee_delta_6d, atol=1e-6, rtol=1e-5)
    np.testing.assert_allclose(
        gripper_rt, ep.gripper_normalized, atol=1e-6, rtol=1e-5
    )
    np.testing.assert_allclose(
        gripper_d_rt, ep.gripper_delta, atol=1e-6, rtol=1e-5
    )


def test_world_and_body_frame_t_produce_distinct_deltas(tmp_path: Path) -> None:
    """Sanity check that the chosen pose trajectory exercises all three branches:
    body_frame_t and world produce different arrays once rotation is non-zero."""
    pose = _build_pose_trajectory(num_frames=10)
    body_delta = compute_ee_delta_6d(pose, basis="body_frame_t")
    world_delta = compute_ee_delta_6d(pose, basis="world")
    # Last row is zero-padded; compare 0..-2.
    diff = np.abs(body_delta[:-1] - world_delta[:-1]).max()
    assert diff > 1e-3, (
        f"body_frame_t and world deltas should differ for this trajectory; "
        f"max diff was {diff}"
    )


def test_world_and_base_produce_identical_deltas(tmp_path: Path) -> None:
    """Spec §2.2 invariant: world and base bases differ only by interpretation;
    the closed-form output is the same array."""
    _ep_body, body_delta_rt, _g_b, _gd_b = _round_trip_episode(
        tmp_path / "body", delta_basis="body_frame_t"
    )
    _ep_world, world_delta_rt, _g_w, _gd_w = _round_trip_episode(
        tmp_path / "world", delta_basis="world"
    )
    _ep_base, base_delta_rt, _g_ba, _gd_ba = _round_trip_episode(
        tmp_path / "base", delta_basis="base"
    )
    # world vs base must be identical.
    np.testing.assert_allclose(
        world_delta_rt, base_delta_rt, atol=1e-7, rtol=1e-7
    )
    # body_frame_t must differ from world (consistency with the previous test
    # but on the round-tripped float32 arrays).
    diff = np.abs(world_delta_rt[:-1] - body_delta_rt[:-1]).max()
    assert diff > 1e-3
