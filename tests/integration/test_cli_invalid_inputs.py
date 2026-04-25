# tests/integration/test_cli_invalid_inputs.py
"""§11: aborts emit structured JSON on stderr with the right error_code."""
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.integration


def _last_json_line(text: str) -> dict:
    line = next(line for line in reversed(text.strip().splitlines()) if line.strip())
    return json.loads(line)


def test_missing_state_column_aborts_with_error_code(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")

    # Re-write parquet without observation.state (required).
    table = pq.read_table(episode.parquet)
    df = table.to_pylist()
    new_table = pa.table({
        "action": pa.array([row["action"] for row in df]),
        "timestamp": pa.array([row["timestamp"] for row in df]),
    })
    pq.write_table(new_table, episode.parquet)

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = _last_json_line(result.stderr)
    assert "error_code" in err
    assert "observation.state" in err.get("message", "")


def test_unknown_robot_adapter(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "nonexistent",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = _last_json_line(result.stderr)
    assert err["error_code"] == "adapter.unknown"
