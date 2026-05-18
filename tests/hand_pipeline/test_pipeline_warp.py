"""Tests for pipeline._back_warp_depth (Phase 2c).

Run inside the unidac env: ``/home/gayagaya/anaconda3/envs/unidac/bin/python``.
The hand landmarker backend is not exercised here (that's a different env).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import _back_warp_depth, _sample_depth_at_pixels


DEPTH_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "depth_GX010013" / "frame_000000.npy"
IMG_H, IMG_W = 1520, 2704           # GX010013 native resolution

# From Phase 2b _run_hamer report: wrist 2D pixel locations on this same frame.
LEFT_WRIST_UV = (1029, 1331)        # left hand wrist (rounded)
RIGHT_WRIST_UV = (2172, 1416)       # right hand wrist (rounded)


@pytest.fixture(scope="module")
def depth_erp() -> np.ndarray:
    if not DEPTH_FIXTURE.exists():
        pytest.skip(f"depth fixture missing: {DEPTH_FIXTURE}")
    d = np.load(DEPTH_FIXTURE)
    assert d.shape == (512, 704), d.shape
    assert d.dtype == np.float32
    return d


@pytest.fixture(scope="module")
def warped(depth_erp) -> np.ndarray:
    return _back_warp_depth(depth_erp, (IMG_H, IMG_W))


def test_back_warp_shape_dtype(warped):
    assert warped.shape == (IMG_H, IMG_W)
    assert warped.dtype == np.float32


def test_back_warp_smoke(warped):
    valid = np.isfinite(warped)
    frac = valid.mean()
    assert frac > 0.5, f"too few valid pixels: {frac:.3f}"
    finite_vals = warped[valid]
    assert finite_vals.min() >= 0.0
    assert finite_vals.max() < 1000.0  # meters


def test_back_warp_hand_region(warped):
    """The wrist pixels should land on plausible table-top depth (~0.3-1.5m)."""
    results = {}
    for label, (u, v) in [("left", LEFT_WRIST_UV), ("right", RIGHT_WRIST_UV)]:
        # 5x5 median around the wrist to soften single-pixel noise.
        patch = warped[v - 2:v + 3, u - 2:u + 3]
        finite = patch[np.isfinite(patch)]
        assert finite.size > 0, f"{label} wrist patch has no finite depth"
        results[label] = float(np.median(finite))
    for label, d in results.items():
        assert 0.2 <= d <= 2.0, f"{label} wrist depth {d:.3f}m outside 0.2..2.0"


def test_back_warp_deterministic(depth_erp, warped):
    again = _back_warp_depth(depth_erp, (IMG_H, IMG_W))
    # NaN-aware comparison.
    a_finite = np.isfinite(warped)
    b_finite = np.isfinite(again)
    assert np.array_equal(a_finite, b_finite), "NaN masks differ"
    np.testing.assert_allclose(warped[a_finite], again[b_finite], atol=1e-6)


# --- forward point-sampling helper -----------------------------------------

WRIST_PIXELS = np.array([list(LEFT_WRIST_UV), list(RIGHT_WRIST_UV)],
                        dtype=np.float64)


def test_sample_depth_smoke(depth_erp):
    out = _sample_depth_at_pixels(depth_erp, WRIST_PIXELS, (IMG_H, IMG_W))
    assert out.shape == (2,)
    assert out.dtype == np.float32
    for d in out:
        assert np.isfinite(d), f"unexpected NaN at wrist: {out}"
        assert 0.3 < d < 1.5, f"wrist depth {d:.3f} outside 0.3..1.5"


def test_sample_depth_matches_back_warp(depth_erp, warped):
    out = _sample_depth_at_pixels(depth_erp, WRIST_PIXELS, (IMG_H, IMG_W))
    for i, (u, v) in enumerate(WRIST_PIXELS):
        patch = warped[int(v) - 2:int(v) + 3, int(u) - 2:int(u) + 3]
        finite = patch[np.isfinite(patch)]
        ref = float(np.median(finite))
        assert abs(float(out[i]) - ref) < 0.05, (
            f"wrist {i}: forward {out[i]:.3f} vs back-warp {ref:.3f}")


def test_sample_depth_invalid_pixels(depth_erp):
    # Top-left and bottom-right corners are well outside the 150° patch.
    corners = np.array([[0, 0], [IMG_W - 1, IMG_H - 1]], dtype=np.float64)
    out = _sample_depth_at_pixels(depth_erp, corners, (IMG_H, IMG_W))
    assert out.shape == (2,)
    assert np.isnan(out).all(), f"expected NaN at corners, got {out}"


def test_sample_depth_performance(depth_erp):
    import time
    rng = np.random.default_rng(0)
    pixels = rng.uniform(
        low=[IMG_W * 0.3, IMG_H * 0.3],
        high=[IMG_W * 0.7, IMG_H * 0.7],
        size=(778, 2),
    )
    # Warm-up: cv2 may compile on first call.
    _sample_depth_at_pixels(depth_erp, pixels[:1], (IMG_H, IMG_W))
    t0 = time.perf_counter()
    out = _sample_depth_at_pixels(depth_erp, pixels, (IMG_H, IMG_W))
    dt = time.perf_counter() - t0
    assert out.shape == (778,)
    assert dt < 0.1, f"778-pixel sample took {dt*1000:.1f}ms (>100ms)"
