"""Phase 4 finer-segmentation: end-to-end ZC detector integration test.

spec: docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md §6.3

Uses a synthetic episode whose gripper signal is a 2-cycle trapezoid with slow
ramps — the existing ``detect_gripper_transition`` (|Δgripper| threshold) fails
to fire on these because per-frame deltas stay below 0.30, but the new
zero-crossing detector should produce 4 boundaries (one per crossing).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.integration


def _slow_trapezoid_gripper(n_frames: int) -> np.ndarray:
    """Two slow open/close cycles; per-frame |Δ| stays below 0.10."""
    g = np.zeros(n_frames, dtype=np.float64)
    # First cycle: ramp up over frames [10, 40), hold [40, 60), ramp down [60, 90).
    g[10:40] = np.linspace(0.0, 0.6, 30, endpoint=False)
    g[40:60] = 0.6
    g[60:90] = np.linspace(0.6, 0.0, 30, endpoint=False)
    # Second cycle: ramp up [110, 140), hold [140, 160), ramp down [160, 190).
    g[110:140] = np.linspace(0.0, 0.6, 30, endpoint=False)
    g[140:160] = 0.6
    g[160:190] = np.linspace(0.6, 0.0, 30, endpoint=False)
    return g


def _run_cli(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _candidates_count(run_dir: Path) -> int:
    payload = json.loads((run_dir / "boundaries.json").read_text())
    return len(payload["candidates"])


def test_zero_crossing_enabled_creates_extra_boundaries(tmp_path: Path) -> None:
    from tests.fixtures.synthesize import synthesize_aloha_episode

    n_frames, fps = 200, 30.0
    gripper = _slow_trapezoid_gripper(n_frames)
    episode = synthesize_aloha_episode(
        tmp_path / "data",
        n_frames=n_frames,
        fps=fps,
        gripper=gripper,
    )

    # --- Baseline run: default config (ZC disabled). ----------------------
    runs_base = tmp_path / "runs_base"
    res = _run_cli(
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_base),
    )
    assert res.returncode == 0, res.stderr
    base_dir = next(p for p in runs_base.iterdir() if p.is_dir())
    base_candidates = _candidates_count(base_dir)

    # --- ZC-enabled run --------------------------------------------------
    cfg_yaml = tmp_path / "zc.yaml"
    cfg_yaml.write_text(
        "zero_crossing:\n"
        "  enabled: true\n"
        "  ref: midpoint\n"
        "  hysteresis: 0.10\n"
        "  span_eps: 0.05\n"
        "  weight: 0.5\n"
        "score_threshold: 0.10\n"
    )
    runs_zc = tmp_path / "runs_zc"
    res = _run_cli(
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_zc),
        "--boundary-config", str(cfg_yaml),
    )
    assert res.returncode == 0, res.stderr
    zc_dir = next(p for p in runs_zc.iterdir() if p.is_dir())
    zc_candidates = _candidates_count(zc_dir)

    # ZC should produce ≥ 4 boundaries (2 cycles × 2 crossings).
    assert zc_candidates >= 4, (
        f"expected ≥4 boundaries with ZC enabled, got {zc_candidates}; "
        f"base was {base_candidates}"
    )
    assert zc_candidates > base_candidates, (
        f"ZC run ({zc_candidates}) should produce more boundaries than baseline "
        f"({base_candidates})"
    )

    # Manifest records the zero_crossing block when enabled.
    manifest = json.loads((zc_dir / "manifest.json").read_text())
    bcfg = manifest["pipeline_params"]["boundary"]
    assert bcfg["zero_crossing"]["enabled"] is True
    assert bcfg["zero_crossing"]["hysteresis"] == 0.10

    # Default-run manifest should NOT include the key (Option A hash compat).
    base_manifest = json.loads((base_dir / "manifest.json").read_text())
    assert "zero_crossing" not in base_manifest["pipeline_params"]["boundary"]
