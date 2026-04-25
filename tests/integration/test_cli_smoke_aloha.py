# tests/integration/test_cli_smoke_aloha.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_cli_runs_and_creates_run_dir(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    runs_root = tmp_path / "runs"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick red block",
         "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    run_dirs = [p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__")]
    assert len(run_dirs) == 1
    final = run_dirs[0]
    manifest = json.loads((final / "manifest.json").read_text())
    assert manifest["episode_id"] == episode.episode_id
    # No .writer.json should remain in the final dir.
    assert not (final / ".writer.json").exists()


def test_cli_emits_structured_error_on_missing_parquet(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    bogus = tmp_path / "does-not-exist.parquet"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(bogus),
         "--task", "pick",
         "--robot", "aloha",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = json.loads(result.stderr.strip().splitlines()[-1])
    assert "error_code" in err
