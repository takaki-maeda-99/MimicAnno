"""ee_delta_6d / gripper_delta math tests (Phase 5, Task 7, spec §2.2)."""

from __future__ import annotations

import numpy as np

from mimicanno.exports.canonical import compute_ee_delta_6d, compute_gripper_delta


def test_pure_translation_body_frame_zero_rotation() -> None:
    # All rotations identity. body_frame_t Δp_body = world Δp because R_t = I.
    pose = np.array(
        [[0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0]],
        dtype=np.float64,
    )
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    np.testing.assert_allclose(d[0], [1, 0, 0, 0, 0, 0], atol=1e-12)
    np.testing.assert_allclose(d[1], [1, 0, 0, 0, 0, 0], atol=1e-12)
    np.testing.assert_allclose(d[2], 0, atol=1e-12)  # last frame padded


def test_pure_z_rotation_body_frame() -> None:
    # Rotate by pi/4 around z each frame, no translation.
    pose = np.array(
        [
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, np.pi / 4],
            [0, 0, 0, 0, 0, np.pi / 2],
        ],
        dtype=np.float64,
    )
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    # body-frame rotvec delta: log(R_t.T @ R_{t+1}) = pi/4 around z each step
    np.testing.assert_allclose(d[0, 3:], [0, 0, np.pi / 4], atol=1e-10)
    np.testing.assert_allclose(d[1, 3:], [0, 0, np.pi / 4], atol=1e-10)


def test_translation_in_world_seen_from_rotated_body() -> None:
    # Frame 0: identity. Frame 1: rotated 90 deg around z, translated +x in world.
    # Body-frame Δp at t=0 should be R_0.T @ (p1 - p0) = [1,0,0] (since R_0 = I).
    pose = np.array(
        [
            [0, 0, 0, 0, 0, 0],
            [1, 0, 0, 0, 0, np.pi / 2],
        ],
        dtype=np.float64,
    )
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    np.testing.assert_allclose(d[0, :3], [1, 0, 0], atol=1e-10)
    np.testing.assert_allclose(d[0, 3:], [0, 0, np.pi / 2], atol=1e-10)


def test_world_basis_uses_left_invariant() -> None:
    pose = np.array(
        [[0, 0, 0, 0, 0, 0], [1, 2, 3, 0, 0, np.pi / 4]], dtype=np.float64
    )
    d = compute_ee_delta_6d(pose, basis="world")
    # plain world delta
    np.testing.assert_allclose(d[0, :3], [1, 2, 3], atol=1e-12)
    # log(R1 @ R0.T) = R1 (since R0 = I)
    np.testing.assert_allclose(d[0, 3:], [0, 0, np.pi / 4], atol=1e-10)


def test_base_basis_equals_world_basis() -> None:
    pose = np.array(
        [[0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, np.pi / 4]], dtype=np.float64
    )
    np.testing.assert_allclose(
        compute_ee_delta_6d(pose, basis="world"),
        compute_ee_delta_6d(pose, basis="base"),
    )


def test_t_equals_one_returns_zero_delta() -> None:
    pose = np.array([[0.5, 0.5, 0.5, 0.1, 0.2, 0.3]], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    assert d.shape == (1, 6)
    np.testing.assert_allclose(d, 0, atol=1e-12)


def test_gripper_delta_basic() -> None:
    g = np.array([0.1, 0.3, 0.7, 0.7, 0.2])
    d = compute_gripper_delta(g)
    np.testing.assert_allclose(
        d, [0.2, 0.4, 0.0, -0.5, 0.0], atol=1e-12,
    )


def test_gripper_delta_empty() -> None:
    d = compute_gripper_delta(np.array([], dtype=np.float64))
    assert d.shape == (0,)
