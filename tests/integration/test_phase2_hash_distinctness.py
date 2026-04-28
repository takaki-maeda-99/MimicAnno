"""Different VLMConfig fields produce distinct run_hash (§1.3)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def _run(**kwargs) -> subprocess.CompletedProcess:
    args = ["env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
            ".venv/bin/python", "-m", "mimicanno.cli", "annotate"]
    for k, v in kwargs.items():
        args.append(f"--{k.replace('_', '-')}")
        args.append(str(v))
    args.append("--offline")
    return subprocess.run(args, capture_output=True, text=True)


def test_different_keyframes_produce_distinct_run_hashes(
    synth_episode, tmp_path: Path,
) -> None:
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    runs = tmp_path / "runs"
    common = dict(
        video=synth_episode.video, parquet=synth_episode.parquet,
        task="x", robot="aloha", target_phase=2,
        vlm_model=f"fixture://{fixt}", runs_root=runs,
    )
    p1 = _run(**common, vlm_keyframes=4)
    p2 = _run(**common, vlm_keyframes=6)
    assert p1.returncode == 0, p1.stderr
    assert p2.returncode == 0, p2.stderr
    dirs = sorted(d.name for d in runs.iterdir() if d.is_dir())
    assert len(dirs) == 2, f"expected 2 distinct runs, got {dirs}"
