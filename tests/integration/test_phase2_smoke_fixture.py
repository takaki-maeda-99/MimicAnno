"""End-to-end Phase 2 smoke against FixtureVLMLabeler. Exit criterion #12."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def test_phase2_smoke_with_fixture(synth_episode, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    p = subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode.video),
        "--parquet", str(synth_episode.parquet),
        "--task", "pick the red block and place in white bin",
        "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt}",
        "--runs-root", str(runs),
        "--offline",
    ], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr

    [run_dir] = [d for d in runs.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    assert manifest["generator"]["pipeline_phase"] == 2
    assert manifest["model_versions"]["vlm"].startswith("fixture:")
    assert manifest["pipeline_status"]["degraded_from_phase"] is None
    assert manifest["pipeline_params"]["vlm"]["keyframes_per_segment"] == 4

    for seg in annotation["segments"]:
        assert seg["phase"] in (
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat", "unknown",
        )
        assert seg["label_source"] == "vlm_robot_state_only"
        assert 0.0 <= seg["vlm_confidence"] <= 1.0
    assert annotation["notes"] is not None
    assert "/" in annotation["notes"]


def test_phase2_smoke_logs_vlm_attempt_events(synth_episode, tmp_path: Path) -> None:
    """Exit criterion #12 — rejection retries observable in logs."""
    fixt = Path("tests/fixtures/vlm/retry_then_ok.json").resolve()
    p = subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode.video),
        "--parquet", str(synth_episode.parquet),
        "--task", "x", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt}",
        "--runs-root", str(tmp_path / "runs"),
        "--offline",
    ], capture_output=True, text=True)
    assert p.returncode == 0
    events = [json.loads(line) for line in p.stderr.strip().splitlines()
              if line.startswith("{") and '"event"' in line]
    rejected = [e for e in events
                if e.get("event") == "vlm_attempt" and e.get("status") == "rejected"]
    assert any(e.get("reject_reason") == "json_parse_error" for e in rejected)
    assert any(e.get("reject_reason") == "invalid_label" for e in rejected)
