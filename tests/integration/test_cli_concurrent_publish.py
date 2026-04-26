# tests/integration/test_cli_concurrent_publish.py
"""§15.4 + §4.4 step 6: two concurrent CLIs targeting the same run_hash
must not lose entries or corrupt the run dir; only one writes, the
other reuses."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_two_concurrent_publishes_same_hash(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=300)
    runs_root = tmp_path / "runs"
    args = [
        "--video",
        str(episode.video),
        "--parquet",
        str(episode.parquet),
        "--task",
        "pick red block",
        "--robot",
        "aloha",
        "--runs-root",
        str(runs_root),
    ]
    p1 = _spawn(args)
    # Stagger by 50 ms so both processes are likely to be in the
    # heavy-compute (lock-free) region simultaneously.
    time.sleep(0.05)
    p2 = _spawn(args)
    rc1 = p1.wait(timeout=120)
    rc2 = p2.wait(timeout=120)
    assert rc1 == 0
    assert rc2 == 0

    # Exactly one final run dir.
    runs = [
        p
        for p in runs_root.iterdir()
        if p.is_dir() and p.name.startswith(episode.episode_id + "__")
    ]
    assert len(runs) == 1

    # Index has exactly one row.
    idx = json.loads((runs_root / "index.json").read_text())
    assert len(idx["runs"]) == 1
    # No leftover *.tmp.<pid>/ or *.bak.<pid>/.
    for child in runs_root.iterdir():
        assert ".tmp." not in child.name
        assert ".bak." not in child.name
