"""Re-running the same Phase 2 command short-circuits per parent §4.4 step 2."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def test_same_command_is_idempotent(synth_episode, tmp_path: Path) -> None:
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    runs = tmp_path / "runs"
    cmd = ["env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
           ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
           "--video", str(synth_episode.video), "--parquet", str(synth_episode.parquet),
           "--task", "x", "--robot", "aloha", "--target-phase", "2",
           "--vlm-model", f"fixture://{fixt}", "--runs-root", str(runs),
           "--offline"]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    dirs1 = sorted(d.name for d in runs.iterdir() if d.is_dir())
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    dirs2 = sorted(d.name for d in runs.iterdir() if d.is_dir())
    assert dirs1 == dirs2, "second invocation must reuse the existing run dir"
