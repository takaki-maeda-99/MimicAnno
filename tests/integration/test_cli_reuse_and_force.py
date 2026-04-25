# tests/integration/test_cli_reuse_and_force.py
"""§15.6: re-running the same config does not rewrite the run directory.
--force re-publishes byte-equivalent artifacts modulo generated_at."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        capture_output=True, text=True, timeout=60,
    )


def _common_args(episode, runs_root: Path) -> list[str]:
    return [
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
    ]


def test_second_run_with_same_config_is_no_op(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    r1 = _run_cli(*_common_args(episode, runs_root))
    assert r1.returncode == 0
    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    mtime_before = (final / "manifest.json").stat().st_mtime_ns
    time.sleep(0.05)

    r2 = _run_cli(*_common_args(episode, runs_root))
    assert r2.returncode == 0
    mtime_after = (final / "manifest.json").stat().st_mtime_ns
    assert mtime_after == mtime_before  # nothing rewritten


def test_force_replaces_run(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    _run_cli(*_common_args(episode, runs_root))
    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    before = json.loads((final / "manifest.json").read_text())

    time.sleep(0.05)
    r = _run_cli(*_common_args(episode, runs_root), "--force")
    assert r.returncode == 0
    after = json.loads((final / "manifest.json").read_text())

    # generated_at differs because --force writes fresh.
    assert before["generated_at"] != after["generated_at"]
    # Hashes are stable (same inputs + config).
    assert before["run_hash"] == after["run_hash"]
    assert before["config_hash"] == after["config_hash"]
    assert before["input_hash"] == after["input_hash"]
