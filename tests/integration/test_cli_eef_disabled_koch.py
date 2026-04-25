# tests/integration/test_cli_eef_disabled_koch.py
"""§15.7: Koch (joint-only) → EEF detectors auto-disabled, gripper still fires."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_koch_episode_auto_disables_eef(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_koch_episode
    episode = synthesize_koch_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "koch",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    manifest = json.loads((final / "manifest.json").read_text())
    disabled = manifest["pipeline_params"]["boundary"]["disabled_sources"]
    assert "eef_velocity_valley" in disabled
    assert "eef_acceleration_peak" in disabled
    # gripper detector still active.
    boundaries = json.loads((final / "boundaries.json").read_text())
    if boundaries["candidates"]:
        sources_seen = {src for c in boundaries["candidates"] for src in c["sources"]}
        assert "gripper_transition" in sources_seen
