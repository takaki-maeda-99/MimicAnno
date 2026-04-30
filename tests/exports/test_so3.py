"""SO(3) helper tests (Phase 5, Task 6)."""

from __future__ import annotations

import numpy as np

from mimicanno.exports.so3 import exp_so3, log_so3, quat_to_rotvec, rotvec_to_quat


def test_exp_so3_identity() -> None:
    R = exp_so3(np.array([0.0, 0.0, 0.0]))  # noqa: N806 — math convention
    np.testing.assert_allclose(R, np.eye(3), atol=1e-12)


def test_exp_so3_z_quarter() -> None:
    R = exp_so3(np.array([0.0, 0.0, np.pi / 2]))  # noqa: N806 — math convention
    expected = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    np.testing.assert_allclose(R, expected, atol=1e-12)


def test_log_so3_inverse_of_exp() -> None:
    rng = np.random.default_rng(42)
    for _ in range(50):
        rv = rng.normal(size=3) * 0.7  # avoid antipodal
        R = exp_so3(rv)  # noqa: N806 — math convention
        rv_back = log_so3(R)
        np.testing.assert_allclose(rv_back, rv, atol=1e-10)


def test_log_so3_identity_is_zero() -> None:
    rv = log_so3(np.eye(3))
    np.testing.assert_allclose(rv, np.zeros(3), atol=1e-12)


def test_quat_to_rotvec_xyzw_convention() -> None:
    # 90deg around z: quat = (0, 0, sin(pi/4), cos(pi/4))
    q = np.array([[0.0, 0.0, np.sin(np.pi / 4), np.cos(np.pi / 4)]])
    rv = quat_to_rotvec(q)
    np.testing.assert_allclose(rv, [[0, 0, np.pi / 2]], atol=1e-10)


def test_rotvec_to_quat_inverse() -> None:
    rng = np.random.default_rng(7)
    rv = rng.normal(size=(20, 3)) * 0.5
    q = rotvec_to_quat(rv)
    rv_back = quat_to_rotvec(q)
    np.testing.assert_allclose(rv_back, rv, atol=1e-10)
