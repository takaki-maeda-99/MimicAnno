"""Tests for _generate_signals() v3 format (--full-signals)."""
from __future__ import annotations

import json
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_hand_estimation import _generate_signals


# ---------------------------------------------------------------------------
# Minimal HandEstimate stub (avoids importing HaMeR deps in CI)

@dataclass
class _FakeHandEstimate:
    is_right: bool
    cam_t: np.ndarray
    global_orient: np.ndarray
    wrist_depth_m: Optional[float]
    pinch_distance_m: Optional[float]
    depth_interpolated: bool = False
    joints_2d: np.ndarray = field(default_factory=lambda: np.zeros((21, 2), dtype=np.float32))


def _identity_orient() -> np.ndarray:
    return np.eye(3, dtype=np.float32)


def _make_frame_results(
    n_frames: int,
    *,
    right_depth_ok: bool = True,
    include_left: bool = True,
    skip_both_at: int = -1,
) -> dict:
    results = {}
    for i in range(n_frames):
        if i == skip_both_at:
            results[i] = []
            continue
        cam_t = np.array([0.1 * i, -0.05, 0.6], dtype=np.float32)
        hands = [
            _FakeHandEstimate(
                is_right=True,
                cam_t=cam_t,
                global_orient=_identity_orient(),
                wrist_depth_m=0.6 if right_depth_ok else None,
                pinch_distance_m=0.03 + i * 0.001,
            ),
        ]
        if include_left:
            hands.append(
                _FakeHandEstimate(
                    is_right=False,
                    cam_t=cam_t * 0.9,
                    global_orient=_identity_orient(),
                    wrist_depth_m=0.55,
                    pinch_distance_m=0.04,
                )
            )
        results[i] = hands
    return results


# ---------------------------------------------------------------------------
# v3 tests

def test_v3_schema_version_and_joints_2d(tmp_path):
    results = _make_frame_results(3)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    assert data["schema_version"] == 3
    # Verify joints_2d is present and well-formed in the first non-null hand entry
    for k, v in data.items():
        if not k.startswith("frame_"):
            continue
        for side in ("right", "left"):
            h = v.get(side)
            if h is None:
                continue
            assert "joints_2d" in h
            j = h["joints_2d"]
            assert isinstance(j, list) and len(j) == 21
            for pt in j:
                assert isinstance(pt, list) and len(pt) == 2
                assert all(isinstance(x, (int, float)) for x in pt)
            return
    raise AssertionError("no non-null hand entry found")


def test_v2_cam_t_shape(tmp_path):
    results = _make_frame_results(3)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    entry = data["frame_000000"]["right"]
    assert entry is not None
    assert isinstance(entry["cam_t"], list)
    assert len(entry["cam_t"]) == 3
    assert all(isinstance(v, float) for v in entry["cam_t"])


def test_v2_euler_deg_keys(tmp_path):
    results = _make_frame_results(3)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    euler = data["frame_000000"]["right"]["euler_deg"]
    assert set(euler.keys()) == {"yaw", "pitch", "roll"}


def test_v2_depth_ok_true_and_false(tmp_path):
    results = _make_frame_results(3, right_depth_ok=False)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    entry = data["frame_000000"]["right"]
    assert entry["depth_ok"] is False
    # cam_t is still present even when depth_ok=False
    assert len(entry["cam_t"]) == 3


def test_v2_cam_t_present_regardless_of_depth_ok(tmp_path):
    results = _make_frame_results(5, right_depth_ok=False)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(5)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    for i in range(5):
        key = f"frame_{i:06d}"
        assert data[key]["right"]["cam_t"] is not None


def test_v2_both_undetected_frame_key_preserved(tmp_path):
    """Both-hands-undetected frames must still emit the frame key (not dropped)."""
    results = _make_frame_results(3, include_left=False, skip_both_at=1)
    # frame 1 has no hands at all
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    assert "frame_000001" in data
    assert data["frame_000001"]["right"] is None
    assert data["frame_000001"]["left"] is None


def test_v2_no_pinch_depth_ok_field(tmp_path):
    """v2 must NOT contain pinch_depth_ok (merged into depth_ok)."""
    results = _make_frame_results(2)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(2)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    entry = data["frame_000000"]["right"]
    assert "pinch_depth_ok" not in entry


def test_v2_uses_pinch_m_not_value(tmp_path):
    results = _make_frame_results(2)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(2)), results, out, sigma=0.0, full=True)
    data = json.loads(out.read_text())
    entry = data["frame_000000"]["right"]
    assert "pinch_m" in entry
    assert "value" not in entry


# ---------------------------------------------------------------------------
# v1 tests (full=False, default)

def test_v1_schema_version(tmp_path):
    results = _make_frame_results(3)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=False)
    data = json.loads(out.read_text())
    assert data["schema_version"] == 1


def test_v1_uses_value_not_pinch_m(tmp_path):
    results = _make_frame_results(2)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(2)), results, out, sigma=0.0, full=False)
    data = json.loads(out.read_text())
    entry = data["frame_000000"]["right"]
    assert "value" in entry
    assert "cam_t" not in entry
    assert "pinch_m" not in entry


def test_v1_both_undetected_drops_key(tmp_path):
    """v1 drops frames where neither hand detected (existing behaviour)."""
    results = _make_frame_results(3, include_left=False, skip_both_at=1)
    out = tmp_path / "signals.json"
    _generate_signals(list(range(3)), results, out, sigma=0.0, full=False)
    data = json.loads(out.read_text())
    assert "frame_000001" not in data


# ---------------------------------------------------------------------------
# --signals-only integration

def test_signals_only_cli(tmp_path):
    """run_signals_only reads existing pkls and writes v3 signals.json."""
    from scripts.run_hand_estimation import run_signals_only

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()

    results = _make_frame_results(4)
    for fi, hands in results.items():
        with open(frames_dir / f"frame_{fi:06d}.pkl", "wb") as f:
            pickle.dump(hands, f)

    # meta.json needed for validation (run_signals_only checks it exists)
    (tmp_path / "meta.json").write_text(json.dumps({
        "video_fps": 30.0, "video_width": 100, "video_height": 100,
    }))

    args = MagicMock()
    args.out = str(tmp_path)
    args.pinch_smooth_sigma = 0.0
    args.full_signals = True

    run_signals_only(args)

    data = json.loads((tmp_path / "signals.json").read_text())
    assert data["schema_version"] == 3
    assert "frame_000000" in data


def test_signals_only_empty_frames_exits(tmp_path):
    """--signals-only with no pkl files should sys.exit(1)."""
    from scripts.run_hand_estimation import run_signals_only

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    (tmp_path / "meta.json").write_text("{}")

    args = MagicMock()
    args.out = str(tmp_path)
    args.pinch_smooth_sigma = 0.0
    args.full_signals = True

    with pytest.raises(SystemExit):
        run_signals_only(args)
