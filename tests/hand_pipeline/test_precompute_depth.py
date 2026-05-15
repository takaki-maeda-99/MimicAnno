"""Tests for scripts/precompute_depth.py.

Run inside `conda activate unidac` (needs the unidac package + the checkpoints
under UniDAC/checkpoints/). The tests use GX010013.MP4 (hand-free fisheye) and
process only 2 frames so each test takes a few seconds on GPU.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest

from scripts.precompute_depth import precompute


def _args(input_path: Path, out_dir: Path, *, limit: int = 2,
          overwrite: bool = False, stride: int = 1) -> argparse.Namespace:
    return argparse.Namespace(
        input=str(input_path),
        out=str(out_dir),
        stride=stride,
        preset="A",
        device=None,
        overwrite=overwrite,
        limit=limit,
    )


@pytest.fixture(scope="module")
def precomputed_run(tmp_path_factory, test_video_with_hands):
    """Run --limit 2 once per module; subsequent tests reuse the output dir."""
    out = tmp_path_factory.mktemp("depth_out")
    meta = precompute(_args(test_video_with_hands, out, limit=2))
    return out, meta


def test_smoke_outputs_valid_npy(precomputed_run):
    out, meta = precomputed_run
    npy_files = sorted(out.glob("frame_*.npy"))
    assert len(npy_files) == 2, f"expected 2 frames, got {len(npy_files)}"
    assert meta["frames_processed"] == 2
    assert meta["failures"] == []

    fwd_sz = tuple(meta["fwd_sz"])  # e.g. (512, 704) for Preset A
    for p in npy_files:
        depth = np.load(p)
        assert depth.dtype == np.float32, f"{p.name}: dtype={depth.dtype}"
        assert depth.shape == fwd_sz, f"{p.name}: shape={depth.shape}"
        assert np.isfinite(depth).all(), f"{p.name}: contains non-finite values"
        # Plausible metric depth range; UniDAC outputs meters.
        assert depth.min() >= 0.0, f"{p.name}: min={depth.min()} (negative depth)"
        assert depth.max() < 1000.0, f"{p.name}: max={depth.max()} (implausibly far)"


def test_meta_json_has_required_fields(precomputed_run):
    out, meta_from_run = precomputed_run
    meta = json.loads((out / "meta.json").read_text())
    required = {
        "unidac_version", "preset", "fwd_sz", "cano_sz",
        "source", "source_type", "source_metadata",
        "stride", "ref_w_native", "cam_params_at_W", "preset_params",
        "frames_processed", "frames_skipped_existing",
        "total_elapsed_seconds", "fps_avg", "failures", "interrupted",
    }
    missing = required - set(meta)
    assert not missing, f"meta.json missing keys: {missing}"

    assert meta["preset"] == "A"
    assert meta["source_type"] == "video"
    assert meta["frames_processed"] == 2
    assert meta["fps_avg"] > 0.0
    assert meta["interrupted"] is False
    # Preset A's cam params should round-trip through meta.
    pp = meta["preset_params"]
    assert pp["fl_x_ref"] == 1820.0
    assert pp["fl_y_ref"] == 1275.0
    assert pp["camera_model"] == "OPENCV_FISHEYE"


def test_resume_skips_existing(precomputed_run, test_video_with_hands):
    out, _ = precomputed_run
    # Sanity: precomputed_run left 2 frames in `out`.
    assert len(list(out.glob("frame_*.npy"))) == 2
    # Re-run without --overwrite: should skip both frames.
    meta2 = precompute(_args(test_video_with_hands, out, limit=2))
    assert meta2["frames_processed"] == 0
    assert meta2["frames_skipped_existing"] == 2
    assert meta2["failures"] == []
