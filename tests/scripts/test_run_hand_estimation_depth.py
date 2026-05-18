"""Unit tests for the depth-input validation and depth-coverage gate added
to ``scripts/run_hand_estimation.py``.

These tests do NOT spin up MediaPipe or read real video; they exercise the
two small helpers added to catch the "silent depth miss" failure mode
where ``--depth`` is mis-specified and every per-frame depth lookup falls
back to passthrough.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; add to sys.path so the test can import directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_hand_estimation import _check_depth_coverage, _validate_depth_dir  # type: ignore


# ---------------------------------------------------------------------------
# _validate_depth_dir
# ---------------------------------------------------------------------------


def test_validate_depth_dir_nonexistent_path_raises(tmp_path):
    bogus = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError) as exc:
        _validate_depth_dir(bogus)
    assert "does not exist" in str(exc.value)
    assert str(bogus) in str(exc.value)


def test_validate_depth_dir_detects_trailing_frames(tmp_path):
    """The common mistake: --depth data/depth/X/frames instead of data/depth/X.

    The validator must:
    - Raise FileNotFoundError (not silently degrade).
    - Show Got/Expected with the parent path as the suggested fix.
    - State the auto-detect rule for traceability.
    """
    phase_a_root = tmp_path / "depth" / "GX010085"
    frames = phase_a_root / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_000000.npy").touch()

    with pytest.raises(FileNotFoundError) as exc:
        _validate_depth_dir(frames)  # user passed the inner /frames subdir
    msg = str(exc.value)
    assert "appears to include 'frames'" in msg
    # Got / Expected pair
    assert f"Got:      {frames}" in msg
    assert f"Expected: {phase_a_root}" in msg
    # Auto-detect rule documented
    assert "depth_dir.name == 'frames'" in msg


def test_validate_depth_dir_missing_frames_subdir(tmp_path):
    """Symmetric case to the trailing-frames one: user gave the right kind
    of path but ``frames/`` was never created (e.g. Phase A never ran)."""
    phase_a_root = tmp_path / "depth" / "GX010085"
    phase_a_root.mkdir(parents=True)
    # No frames/ subdir created.

    with pytest.raises(FileNotFoundError) as exc:
        _validate_depth_dir(phase_a_root)
    msg = str(exc.value)
    assert "missing 'frames/' subdirectory" in msg
    assert f"Got:      {phase_a_root}" in msg
    assert f"Expected: {phase_a_root / 'frames'}" in msg


def test_validate_depth_dir_accepts_valid_root(tmp_path):
    phase_a_root = tmp_path / "depth" / "GX010085"
    frames = phase_a_root / "frames"
    frames.mkdir(parents=True)
    (frames / "frame_000000.npy").touch()

    # Must not raise.
    _validate_depth_dir(phase_a_root)


# ---------------------------------------------------------------------------
# _check_depth_coverage
# ---------------------------------------------------------------------------


def test_check_depth_coverage_passes_at_or_below_threshold():
    # 30% miss exactly equals the default threshold → pass.
    _check_depth_coverage(n_depth_miss=30, n_detections=100, threshold=0.30)
    # 10% miss is well below → pass.
    _check_depth_coverage(n_depth_miss=10, n_detections=100, threshold=0.30)
    # Zero detections → no-op (avoid div-by-zero).
    _check_depth_coverage(n_depth_miss=0, n_detections=0, threshold=0.30)


def test_check_depth_coverage_raises_above_threshold():
    """The catastrophic case the gate is designed to catch: every detection
    came back with wrist_depth_m=None (the silent-fallback symptom)."""
    with pytest.raises(RuntimeError) as exc:
        _check_depth_coverage(
            n_depth_miss=245, n_detections=245, threshold=0.30
        )
    msg = str(exc.value)
    # Coverage in the message lets the operator see the rate without re-running.
    assert "100.0%" in msg
    assert "245/245" in msg
    # Threshold value echoed.
    assert "30.0%" in msg
    # Diagnostic hint references the validation step and the override flag.
    assert "--depth-miss-threshold" in msg
