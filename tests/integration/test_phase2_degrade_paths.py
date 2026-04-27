"""Integration: run-level degrade paths produce a published run dir with
Phase 1 baseline + degrade flags (§4.3)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def _run_phase2(synth_episode, runs_root: Path, fixture_name: str):
    fixt = Path("tests/fixtures/vlm") / fixture_name
    return subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode.video),
        "--parquet", str(synth_episode.parquet),
        "--task", "x", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt.resolve()}",
        "--runs-root", str(runs_root),
        "--offline",
    ], capture_output=True, text=True)


def test_init_failure_publishes_phase1_baseline_with_degrade_flag(
    synth_episode, tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    p = _run_phase2(synth_episode, runs, "init_should_raise.json")
    assert p.returncode == 0, p.stderr  # degrade ≠ abort

    [run_dir] = [d for d in runs.iterdir() if d.is_dir()]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    assert manifest["generator"]["pipeline_phase"] == 2
    assert manifest["pipeline_status"]["degraded_from_phase"] == 2
    assert manifest["pipeline_status"]["degrade_reason"] == "vlm_init_failed"
    assert all(s["phase"] == "unlabeled" for s in annotation["segments"])
    assert all(s["label_source"] == "signals_only" for s in annotation["segments"])
    assert all(s["vlm_confidence"] is None for s in annotation["segments"])
    assert "vlm_init_failed" in annotation["notes"]
    assert "OSError" not in annotation["notes"]
    assert "RuntimeError" not in annotation["notes"]


def test_runtime_oom_threshold_triggers_degrade(
    synth_episode, tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    p = _run_phase2(synth_episode, runs, "runtime_oom.json")
    assert p.returncode == 0, p.stderr
    [run_dir] = [d for d in runs.iterdir() if d.is_dir()]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["pipeline_status"]["degrade_reason"] == "vlm_runtime_failed"
