# tests/integration/test_cli_zero_action.py
"""§11: empty/zero action column disables action_norm_change without aborting."""

import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.integration


def test_zero_action_disables_detector(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data")

    # Rewrite parquet with all-zero action column.
    table = pq.read_table(episode.parquet)
    n = table.num_rows
    df = table.to_pylist()
    new_table = pa.table(
        {
            "observation.state": pa.array([row["observation.state"] for row in df]),
            "action": pa.array([[0.0] * 14] * n),
            "timestamp": pa.array([row["timestamp"] for row in df]),
        }
    )
    pq.write_table(new_table, episode.parquet)

    runs_root = tmp_path / "runs"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mimicanno.cli",
            "annotate",
            "--video",
            str(episode.video),
            "--parquet",
            str(episode.parquet),
            "--task",
            "pick",
            "--robot",
            "aloha",
            "--runs-root",
            str(runs_root),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    final = next(
        p
        for p in runs_root.iterdir()
        if p.is_dir() and p.name.startswith(episode.episode_id + "__")
    )
    manifest = json.loads((final / "manifest.json").read_text())
    assert "action_norm_change" in manifest["pipeline_params"]["boundary"]["disabled_sources"]
