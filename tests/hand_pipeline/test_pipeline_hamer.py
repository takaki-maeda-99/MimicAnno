"""Tests for pipeline._run_hamer (Phase 2b).

Run inside the HaMeR venv: ``/misc/dl00/gayagaya/hamer/.hamer/bin/python``.
"""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import HamerRaw, _run_hamer


@pytest.fixture(scope="module")
def hands(two_hands_central_image):
    return _run_hamer(two_hands_central_image)


def test_run_hamer_detects_two_hands(hands):
    assert isinstance(hands, list)
    assert len(hands) == 2, f"expected 2 hands, got {len(hands)}"
    sides = sorted(h.is_right for h in hands)
    assert sides == [False, True], f"expected one left + one right, got {sides}"


def test_run_hamer_output_shapes(hands):
    for h in hands:
        assert isinstance(h, HamerRaw)
        assert h.betas.shape == (10,) and h.betas.dtype == np.float32
        assert h.global_orient.shape == (3, 3) and h.global_orient.dtype == np.float32
        assert h.hand_pose.shape == (15, 3, 3) and h.hand_pose.dtype == np.float32
        assert h.cam_t.shape == (3,) and h.cam_t.dtype == np.float32
        assert np.isfinite(h.cam_t).all()
        assert h.vertices.shape == (778, 3) and h.vertices.dtype == np.float32
        assert h.joints_3d.shape == (21, 3) and h.joints_3d.dtype == np.float32
        assert h.joints_2d.shape == (21, 2) and h.joints_2d.dtype == np.float32
        assert h.bbox.shape == (4,)

        # Rotation matrices should be orthonormal.
        I3 = np.eye(3, dtype=np.float32)
        np.testing.assert_allclose(h.global_orient @ h.global_orient.T, I3,
                                   atol=1e-4)
        for j in range(15):
            R = h.hand_pose[j]
            np.testing.assert_allclose(R @ R.T, I3, atol=1e-4,
                                       err_msg=f"joint {j} not orthonormal")


def test_run_hamer_no_hand():
    # A flat black image should yield zero detections.
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    out = _run_hamer(blank)
    assert out == [], f"expected [], got {out!r}"


def test_run_hamer_deterministic(two_hands_central_image, hands):
    out2 = _run_hamer(two_hands_central_image)
    assert len(out2) == len(hands)
    # The detector may shuffle ordering; match by bbox.
    key = lambda h: (h.is_right, round(float(h.bbox[0]), 1))
    a = sorted(hands, key=key)
    b = sorted(out2,  key=key)
    for ha, hb in zip(a, b):
        assert ha.is_right == hb.is_right
        np.testing.assert_allclose(ha.betas,    hb.betas,    atol=1e-5)
        np.testing.assert_allclose(ha.vertices, hb.vertices, atol=1e-5)
        np.testing.assert_allclose(ha.cam_t,    hb.cam_t,    atol=1e-5)
