"""Tests for pipeline.estimate_hand (MediaPipe backend).

Drives the MediaPipe HandLandmarker path with the gx010085 fixture frames and
their precomputed UniDAC depth NPZs. Run inside MimicAnno's uv venv::

    uv run pytest tests/hand_pipeline/test_pipeline_estimate.py -v
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from mimicanno.hand_pipeline.pipeline import HandEstimate, estimate_hand


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "gx010085"


def test_estimate_hand_with_depth():
    """With UniDAC depth, every HandEstimate has metric cam_t and an orthonormal R."""
    img = cv2.imread(str(FIXTURES / "depth_frame_120.jpg"))
    assert img is not None
    depth = np.load(FIXTURES / "depth_frame_000120.npz")["depth"].astype(np.float32)
    estimates = estimate_hand(img, depth)
    assert isinstance(estimates, list)
    for est in estimates:
        assert isinstance(est, HandEstimate)
        assert est.cam_t.shape == (3,)
        assert est.global_orient.shape == (3, 3)
        np.testing.assert_allclose(
            est.global_orient @ est.global_orient.T,
            np.eye(3), atol=1e-4,
        )
        assert np.isclose(np.linalg.det(est.global_orient), 1.0, atol=1e-3)
        assert est.wrist_depth_m is None or est.wrist_depth_m > 0


def test_estimate_hand_no_depth():
    """Without depth, cam_t falls back to zero; rotation still produced."""
    img = cv2.imread(str(FIXTURES / "depth_frame_120.jpg"))
    assert img is not None
    estimates = estimate_hand(img, depth=None)
    assert isinstance(estimates, list)
    for est in estimates:
        np.testing.assert_array_equal(est.cam_t, np.zeros(3, dtype=np.float32))
        assert est.wrist_depth_m is None
        assert est.global_orient.shape == (3, 3)


def test_estimate_hand_zero_image():
    """All-zero image: MediaPipe finds nothing, return [] (no crash)."""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    estimates = estimate_hand(img, depth=None)
    assert estimates == []


def test_estimate_hand_return_intermediate():
    """return_intermediate=True yields (estimates, raws) of matching length."""
    img = cv2.imread(str(FIXTURES / "depth_frame_120.jpg"))
    assert img is not None
    out = estimate_hand(img, depth=None, return_intermediate=True)
    assert isinstance(out, tuple) and len(out) == 2
    estimates, raws = out
    assert isinstance(estimates, list) and isinstance(raws, list)
    assert len(estimates) == len(raws)
