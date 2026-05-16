"""Phase 5 D — integration smoke for `mimicanno eval` CLI.

Spawns the CLI via subprocess and checks the JSON output shape both for a
populated runs root (real SO101 fixture) and an empty tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.server.conftest import _build_loadable_fixture


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.timeout(60)
def test_eval_cli_with_real_fixture(tmp_path: Path) -> None:
    """`mimicanno eval <runs_root> --format json` on the frozen fixture →
    JSON with at least one run."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _build_loadable_fixture(runs_root)

    proc = subprocess.run(
        ["uv", "run", "mimicanno", "eval", str(runs_root), "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"CLI failed: rc={proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    assert isinstance(parsed.get("runs"), list)
    assert len(parsed["runs"]) >= 1
    assert isinstance(parsed.get("aggregate"), dict)


@pytest.mark.timeout(60)
def test_eval_cli_empty_runs_root(tmp_path: Path) -> None:
    """`mimicanno eval <empty> --format json` → JSON with `runs: []` and no error."""
    empty_root = tmp_path / "empty_runs"
    empty_root.mkdir()

    proc = subprocess.run(
        ["uv", "run", "mimicanno", "eval", str(empty_root), "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"CLI failed: rc={proc.returncode}\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict)
    assert parsed.get("runs") == []
    assert isinstance(parsed.get("aggregate"), dict)
    # Aggregate of zero runs has zero totals.
    assert parsed["aggregate"]["total_edits"] == 0
    assert parsed["aggregate"]["total_segments"] == 0
