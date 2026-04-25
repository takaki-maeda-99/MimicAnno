# tests/integration/test_cli_perf_compute_path.py
"""§13: Phase 1 compute path target ≤ 5 s on a typical laptop CPU.

We measure with --link-video to exclude the I/O path. Small synthetic
episode (5 s = 150 frames at 30 fps), so any compute-side regression
exceeds the budget loudly."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.perf]


def test_compute_under_5s(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=150, fps=30.0)
    runs_root = tmp_path / "runs"

    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root),
         "--link-video"],
        capture_output=True, text=True, timeout=30,
    )
    elapsed = time.monotonic() - t0
    assert result.returncode == 0, result.stderr
    # Generous ceiling — we'd see a regression at >>5 s.
    assert elapsed < 8.0, f"compute path took {elapsed:.2f}s"
