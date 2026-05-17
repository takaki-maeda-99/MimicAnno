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

    # The frozen fixture carries schema_version 0.2.0, so --legacy is needed
    # to bypass the strict schema check added in Phase 6.
    proc = subprocess.run(
        ["uv", "run", "mimicanno", "eval", "--legacy", str(runs_root), "--format", "json"],
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


@pytest.mark.timeout(60)
def test_p14_strict_mode_rejects_03_run(tmp_path: Path) -> None:
    """P14: default strict mode must reject a 0.3.0 run with exit 2
    and a schema_version_mismatch error envelope on stderr.
    """
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _build_loadable_fixture(runs_root)

    # Downgrade annotation.json to schema_version 0.3.0
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1
    ann_path = run_dirs[0] / "annotation.json"
    doc = json.loads(ann_path.read_text())
    doc["schema_version"] = "0.3.0"
    ann_path.write_text(json.dumps(doc))

    proc = subprocess.run(
        ["uv", "run", "mimicanno", "eval", str(runs_root), "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, (
        f"Expected exit 2 for schema mismatch, got {proc.returncode}\n"
        f"STDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
    assert '"error": "schema_version_mismatch"' in proc.stderr, (
        f"Expected schema_version_mismatch envelope in stderr, got:\n{proc.stderr}"
    )


@pytest.mark.timeout(60)
def test_p15_legacy_mode_accepts_03_run(tmp_path: Path) -> None:
    """P15: --legacy bypasses the schema check; output succeeds (exit 0)."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _build_loadable_fixture(runs_root)

    # Downgrade annotation.json to schema_version 0.3.0
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1
    ann_path = run_dirs[0] / "annotation.json"
    doc = json.loads(ann_path.read_text())
    doc["schema_version"] = "0.3.0"
    ann_path.write_text(json.dumps(doc))

    proc = subprocess.run(
        ["uv", "run", "mimicanno", "eval", "--legacy", str(runs_root), "--format", "json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"Expected exit 0 with --legacy, got {proc.returncode}\n"
        f"STDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
