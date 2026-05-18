"""Unit tests for scripts/diagnose_handedness_flip.py.

Exercises the pairing + flip-counting logic on synthetic pkl data so we
catch logic regressions without needing a real run_hand_estimation run.
"""
from __future__ import annotations

import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from diagnose_handedness_flip import diagnose  # type: ignore


@dataclass
class _StubHand:
    """Minimal HandEstimate-shaped stub for diagnose() (only reads bbox + is_right)."""
    is_right: bool
    bbox: np.ndarray  # (4,) xyxy


def _bbox_at(cx: float, cy: float, w: float = 20.0, h: float = 20.0) -> np.ndarray:
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dtype=np.float32)


def _write_run(tmp_path: Path, frames: list[list[_StubHand]]) -> Path:
    """Build a fake run_dir under tmp_path with the supplied per-frame hand lists."""
    run_dir = tmp_path / "fake_run"
    frames_dir = run_dir / "frames"
    frames_dir.mkdir(parents=True)
    for idx, hands in enumerate(frames):
        pkl_path = frames_dir / f"frame_{idx:06d}.pkl"
        with pkl_path.open("wb") as fp:
            pickle.dump(hands, fp)
    return run_dir


def test_diagnose_zero_flips_when_handedness_stable(tmp_path):
    """Hand at (100,100) right, then (105,100) right → 1 pair, 0 flips."""
    frames = [
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
        [_StubHand(is_right=True, bbox=_bbox_at(105, 100))],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 1
    assert result["n_flips"] == 0


def test_diagnose_counts_flip_when_handedness_changes(tmp_path):
    """Same physical hand position, is_right changes → 1 pair, 1 flip."""
    frames = [
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
        [_StubHand(is_right=False, bbox=_bbox_at(108, 102))],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 1
    assert result["n_flips"] == 1


def test_diagnose_excludes_count_mismatch_transitions(tmp_path):
    """1-hand → 2-hand and back: no pairs counted (spatial correspondence undefined)."""
    frames = [
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
        [
            _StubHand(is_right=True, bbox=_bbox_at(100, 100)),
            _StubHand(is_right=False, bbox=_bbox_at(300, 100)),
        ],
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 0
    assert result["n_flips"] == 0
    assert result["n_count_mismatch"] == 2


def test_diagnose_drops_distant_pairs(tmp_path):
    """Hand jumped > threshold: not the same physical hand, not counted."""
    frames = [
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
        [_StubHand(is_right=False, bbox=_bbox_at(500, 500))],  # 565 px away
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 0
    assert result["n_flips"] == 0
    assert result["n_dist_dropped"] == 1


def test_diagnose_two_hand_greedy_match_picks_nearest(tmp_path):
    """Two hands: greedy match should pair (left↔left, right↔right) by proximity,
    even when ordering in the list differs."""
    frames = [
        [
            _StubHand(is_right=False, bbox=_bbox_at(100, 100)),  # left at L
            _StubHand(is_right=True, bbox=_bbox_at(400, 100)),   # right at R
        ],
        # Order reversed in list, but L and R stayed put → 2 stable pairs, 0 flips.
        [
            _StubHand(is_right=True, bbox=_bbox_at(405, 105)),   # at R, labelled right (correct)
            _StubHand(is_right=False, bbox=_bbox_at(95, 102)),    # at L, labelled left (correct)
        ],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 2
    assert result["n_flips"] == 0


def test_diagnose_two_hand_label_swap_counted_as_two_flips(tmp_path):
    """Two hands stay put but labels swap → 2 flips."""
    frames = [
        [
            _StubHand(is_right=False, bbox=_bbox_at(100, 100)),
            _StubHand(is_right=True, bbox=_bbox_at(400, 100)),
        ],
        [
            _StubHand(is_right=True, bbox=_bbox_at(105, 100)),    # was left, now right (flip)
            _StubHand(is_right=False, bbox=_bbox_at(395, 100)),   # was right, now left (flip)
        ],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 2
    assert result["n_flips"] == 2


def test_diagnose_empty_frames_skipped(tmp_path):
    """No-detection frames don't form pairs and don't crash."""
    frames = [
        [],
        [_StubHand(is_right=True, bbox=_bbox_at(100, 100))],
        [],
        [_StubHand(is_right=True, bbox=_bbox_at(110, 110))],
    ]
    run_dir = _write_run(tmp_path, frames)
    result = diagnose(run_dir, distance_threshold=50.0)
    assert result["n_pairs"] == 0
    assert result["n_flips"] == 0


def test_diagnose_raises_when_run_dir_invalid(tmp_path):
    with pytest.raises(FileNotFoundError):
        diagnose(tmp_path / "does_not_exist", distance_threshold=50.0)
