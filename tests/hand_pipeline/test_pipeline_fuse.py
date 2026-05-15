"""Tests for pipeline._fuse (Phase 2d).

Run inside the unidac env: ``/home/gayagaya/anaconda3/envs/unidac/bin/python``.
HaMeR is NOT exercised here; we use the pre-saved hamer_raw_two_hands.pkl fixture.
"""
from __future__ import annotations

import io
import pickle
import warnings
from pathlib import Path

import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import HandEstimate, HamerRaw, _fuse


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
HAMER_PKL = FIXTURE_DIR / "hamer_raw_two_hands.pkl"
DEPTH_NPY = FIXTURE_DIR / "depth_GX010013" / "frame_000000.npy"
IMG_H, IMG_W = 1520, 2704


class _CompatUnpickler(pickle.Unpickler):
    """Load fixtures pickled under the old ``pipeline`` top-level module name."""

    def find_class(self, module, name):
        if module == "pipeline":
            module = "mimicanno.hand_pipeline.pipeline"
        return super().find_class(module, name)


@pytest.fixture(scope="module")
def hamer_raws() -> list[HamerRaw]:
    if not HAMER_PKL.exists():
        pytest.skip(f"fixture missing: {HAMER_PKL}")
    with open(HAMER_PKL, "rb") as f:
        return _CompatUnpickler(f).load()


@pytest.fixture(scope="module")
def depth_erp() -> np.ndarray:
    if not DEPTH_NPY.exists():
        pytest.skip(f"fixture missing: {DEPTH_NPY}")
    return np.load(DEPTH_NPY)


@pytest.fixture(scope="module")
def fused(hamer_raws, depth_erp) -> list[HandEstimate]:
    return _fuse(hamer_raws, depth_erp, (IMG_H, IMG_W))


# ---------------------------------------------------------------------------

def test_fuse_two_hands(fused):
    """Two HamerRaw inputs produce two HandEstimate outputs."""
    assert len(fused) == 2
    for h in fused:
        assert isinstance(h, HandEstimate)


def test_fuse_output_types_and_shapes(fused):
    """All array fields have correct dtypes and shapes."""
    for h in fused:
        assert h.betas.shape == (10,) and h.betas.dtype == np.float32
        assert h.global_orient.shape == (3, 3) and h.global_orient.dtype == np.float32
        assert h.hand_pose.shape == (15, 3, 3) and h.hand_pose.dtype == np.float32
        assert h.cam_t.shape == (3,) and h.cam_t.dtype == np.float32
        assert h.vertices.shape == (778, 3) and h.vertices.dtype == np.float32
        assert h.joints_3d.shape == (21, 3) and h.joints_3d.dtype == np.float32
        assert h.joints_2d.shape == (21, 2) and h.joints_2d.dtype == np.float32
        assert h.bbox.shape == (4,) and h.bbox.dtype == np.float32
        assert isinstance(h.scale_factor, float)


def test_fuse_scale_factor(fused):
    """Scale ≈ 0.04–0.08 (HaMeR z-overshoot is ~15–25×) and is shared across hands."""
    scales = [h.scale_factor for h in fused]
    for s in scales:
        assert 0.04 <= s <= 0.08, f"scale_factor={s:.5f} outside expected 0.04..0.08"
    # Shared across hands: same value returned in both HandEstimates.
    assert scales[0] == scales[1], "scale_factor must be identical for all hands in one call"


def test_fuse_cam_t_magnitude(fused, hamer_raws):
    """After scaling, cam_t.z must be plausible metric depth (0.3–1.5 m)."""
    for h in fused:
        z = float(h.cam_t[2])
        assert 0.3 <= z <= 1.5, f"cam_t.z={z:.4f} outside 0.3..1.5 m"
    # cam_t must be smaller than the raw HaMeR values by ~scale.
    for raw, h in zip(hamer_raws, fused):
        ratio = float(h.cam_t[2]) / float(raw.cam_t[2])
        assert abs(ratio - h.scale_factor) < 0.001, (
            f"cam_t.z ratio={ratio:.5f} != scale_factor={h.scale_factor:.5f}"
        )


def test_fuse_vertices_in_cam_frame(fused, hamer_raws):
    """Metric vertices = raw.vertices + new_cam_t; shape and pose unchanged."""
    for raw, h in zip(hamer_raws, fused):
        # Shape (betas) and rotations are copied verbatim.
        np.testing.assert_array_equal(h.betas, raw.betas)
        np.testing.assert_array_equal(h.global_orient, raw.global_orient)
        np.testing.assert_array_equal(h.hand_pose, raw.hand_pose)
        # Vertices in cam frame should be local_verts + new_cam_t.
        expected = raw.vertices + h.cam_t[None, :]
        np.testing.assert_allclose(h.vertices, expected, atol=1e-5)
        # Plausible metric range: hand within ~3 m of camera.
        assert np.all(np.abs(h.vertices) < 3.0), "vertices contain unreasonably large values"


def test_fuse_empty_input(depth_erp):
    """Empty hamer_raws list produces empty output without error."""
    result = _fuse([], depth_erp, (IMG_H, IMG_W))
    assert result == []


def test_fuse_all_nan_depth(hamer_raws):
    """All-NaN depth map: _fuse warns and returns empty list."""
    nan_depth = np.full((512, 704), np.nan, dtype=np.float32)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _fuse(hamer_raws, nan_depth, (IMG_H, IMG_W))
    assert result == [], "expected empty list when depth is all NaN"
    assert any("NaN" in str(w.message) for w in caught), (
        "expected a UserWarning mentioning NaN"
    )
