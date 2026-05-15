"""Tests for pipeline.estimate_hand (Phase 2e).

Run inside the hamer venv with UniDAC on PYTHONPATH:
    PYTHONPATH=/misc/dl00/gayagaya/MimicAnno:/misc/dl00/gayagaya/MimicAnno/UniDAC \
        /misc/dl00/gayagaya/MimicAnno/hamer/.hamer/bin/python -m pytest \
        tests/hand_pipeline/test_pipeline_estimate.py -v

HaMeR and UniDAC are both exercised in the same process here.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import HandEstimate, HamerRaw, estimate_hand


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
IMG_PATH = FIXTURE_DIR / "two_hands_central.jpg"
DEPTH_NPY = FIXTURE_DIR / "depth_GX010013" / "frame_000000.npy"
IMG_H, IMG_W = 1520, 2704


@pytest.fixture(scope="module")
def frame() -> np.ndarray:
    if not IMG_PATH.exists():
        pytest.skip(f"fixture missing: {IMG_PATH}")
    img = cv2.imread(str(IMG_PATH))
    assert img is not None
    return img


@pytest.fixture(scope="module")
def depth_erp() -> np.ndarray:
    if not DEPTH_NPY.exists():
        pytest.skip(f"fixture missing: {DEPTH_NPY}")
    return np.load(DEPTH_NPY)


# ---------------------------------------------------------------------------

def test_estimate_hand_two_hands(frame, depth_erp):
    """Fixture frame with both hands → 2 HandEstimate, one per side, metric depth."""
    result = estimate_hand(frame, depth_erp)
    assert isinstance(result, list)
    assert len(result) == 2
    sides = {h.is_right for h in result}
    assert sides == {True, False}, f"expected both hands, got is_right={sides}"
    for h in result:
        assert isinstance(h, HandEstimate)
        if h.wrist_depth_m is not None:
            assert 0.1 <= h.wrist_depth_m <= 3.0, f"wrist_depth_m={h.wrist_depth_m:.4f}"
            z = float(h.cam_t[2])
            assert 0.1 <= z <= 3.0, f"cam_t.z={z:.4f} outside expected range"


def test_estimate_hand_no_hand(depth_erp):
    """Blank image → no hands detected → empty list."""
    blank = np.zeros((IMG_H, IMG_W, 3), dtype=np.uint8)
    result = estimate_hand(blank, depth_erp)
    assert result == []


def test_estimate_hand_refine_off(frame, depth_erp):
    """refine=False → pseudo-metric cam_t.z (≈8-9 m), wrist_depth_m is None."""
    result = estimate_hand(frame, depth_erp, refine=False)
    assert len(result) == 2
    for h in result:
        assert h.scale_factor is None
        assert h.n_valid_samples == 0
        assert h.wrist_depth_m is None
        z = float(h.cam_t[2])
        assert 7.0 <= z <= 12.0, f"pseudo-metric cam_t.z={z:.4f} outside 7..12 m"


def test_estimate_hand_refine_on_vs_off(frame, depth_erp):
    """refine=True gives metric cam_t.z; refine=False gives HaMeR pseudo-metric."""
    refined = estimate_hand(frame, depth_erp, refine=True)
    unrefined = estimate_hand(frame, depth_erp, refine=False)
    assert len(refined) == len(unrefined) == 2
    for h_r in refined:
        if h_r.wrist_depth_m is not None:
            # metric depth should be much smaller than HaMeR pseudo-metric (~8-9m)
            assert h_r.cam_t[2] < 3.0, f"refined cam_t.z={h_r.cam_t[2]:.4f} unexpectedly large"
    for h_u in unrefined:
        assert h_u.wrist_depth_m is None
        assert h_u.cam_t[2] > 3.0, f"unrefined cam_t.z={h_u.cam_t[2]:.4f} unexpectedly small"


def test_estimate_hand_intermediate(frame, depth_erp):
    """return_intermediate=True → (list[HandEstimate], list[HamerRaw]) tuple."""
    out = estimate_hand(frame, depth_erp, return_intermediate=True)
    assert isinstance(out, tuple) and len(out) == 2
    estimates, raws = out
    assert isinstance(estimates, list) and isinstance(raws, list)
    assert len(estimates) == len(raws)
    for h in estimates:
        assert isinstance(h, HandEstimate)
    for r in raws:
        assert isinstance(r, HamerRaw)


def test_estimate_hand_deterministic(frame, depth_erp):
    """Same input twice → identical output (atol=1e-5)."""
    a = estimate_hand(frame, depth_erp)
    b = estimate_hand(frame, depth_erp)
    assert len(a) == len(b)
    for ha, hb in zip(a, b):
        np.testing.assert_allclose(ha.cam_t, hb.cam_t, atol=1e-5)
        np.testing.assert_allclose(ha.vertices, hb.vertices, atol=1e-5)
        np.testing.assert_allclose(ha.joints_3d, hb.joints_3d, atol=1e-5)
        assert ha.scale_factor is None and hb.scale_factor is None
        assert ha.wrist_depth_m == hb.wrist_depth_m
