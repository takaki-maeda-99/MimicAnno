# tests/integration/test_cli_crash_recovery.py
"""§15.10: a stale .tmp directory left by a dead PID is scavenged on next run;
a still-live writer's .tmp is NOT scavenged."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mimicanno.scavenger import (
    WriterMetadata, current_pid_start_time, write_writer_metadata,
)

pytestmark = pytest.mark.integration


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def test_scavenger_removes_dead_pid_tmp(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Plant a stale .tmp dir for a never-existed PID with old claimed_at.
    stale = runs_root / f"{episode.episode_id}__deadbeefdead.tmp.999999"
    stale.mkdir()
    write_writer_metadata(stale, WriterMetadata(
        pid=999999,
        pid_start_time="linux-jiffies-0",
        canonical_name=f"{episode.episode_id}__deadbeefdead",
        kind="tmp",
        claimed_at="1970-01-01T00:00:00.000Z",
    ))

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not stale.exists()


def test_scavenger_does_not_touch_live_writer(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Plant a "live" .tmp owned by THIS pytest process.
    pid = os.getpid()
    live = runs_root / f"{episode.episode_id}__livebeefbeef.tmp.{pid}"
    live.mkdir()
    write_writer_metadata(live, WriterMetadata(
        pid=pid,
        pid_start_time=current_pid_start_time(pid),
        canonical_name=f"{episode.episode_id}__livebeefbeef",
        kind="tmp",
        claimed_at=_now_iso(),
    ))

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert live.exists()
