"""Subprocess-level tests for ``mimicanno export`` CLI (Phase 5 Task 25).

The mini fixture (``tests/exports/fixtures/mini_so101`` + ``mini_runs``) is
re-used as a fast end-to-end input. Each test invokes
``python -m mimicanno export ...`` via :func:`subprocess.run` and asserts
exit code + stdout/stderr JSON shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "exports" / "fixtures"
DATASET = FIXTURES_DIR / "mini_so101"
RUNS_ROOT = FIXTURES_DIR / "mini_runs"


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Inherit virtualenv python; PYTHONPATH=src layout means the worktree root
    # already has mimicanno/ importable.
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "mimicanno", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
    )


def _base_args(out: Path) -> list[str]:
    return [
        "export",
        "--dataset", str(DATASET),
        "--runs-root", str(RUNS_ROOT),
        "--target-phase", "4",
        "--profile", "so101_sarm",
        "--out", str(out),
    ]


def test_happy_path(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    res = _run(_base_args(out))
    assert res.returncode == 0, f"stderr={res.stderr}\nstdout={res.stdout}"
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["out"] == str(out)
    assert payload["episode_count"] == 3
    assert payload["reused"] is False
    assert payload["manifest_path"] == str(out / ".mimicanno-export.json")
    assert (out / ".mimicanno-export.json").is_file()
    assert (out / "meta" / "subtasks.parquet").is_file()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    res = _run([*_base_args(out), "--dry-run"])
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload["dry_run"] is True
    assert payload["profile"]["name"] == "so101_sarm"
    assert len(payload["episodes"]) == 3
    assert not out.exists()


def test_in_place_without_confirm(tmp_path: Path) -> None:
    res = _run(
        [
            "export",
            "--dataset", str(DATASET),
            "--runs-root", str(RUNS_ROOT),
            "--target-phase", "4",
            "--profile", "so101_sarm",
            "--in-place",
        ]
    )
    assert res.returncode == 2, f"stdout={res.stdout}\nstderr={res.stderr}"
    err = json.loads(res.stderr.strip().splitlines()[-1])
    assert err["error_code"] == "EXPORT_INPLACE_NO_CONFIRM"


def test_two_output_modes_rejected(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    res = _run(
        [
            *_base_args(out),
            "--symlink-data",
            "--copy-data",
        ]
    )
    assert res.returncode != 0
    # Output mode mutex error reported via structured JSON or typer message.
    assert (
        "mutually exclusive" in res.stderr.lower()
        or "EXPORT_INPLACE_NO_CONFIRM" not in res.stderr  # not the wrong error
    )


def test_force_replaces_existing(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    # First run.
    res = _run(_base_args(out))
    assert res.returncode == 0, res.stderr

    # Second run without --force: idempotency short-circuit (reused=True).
    res2 = _run(_base_args(out))
    assert res2.returncode == 0, res2.stderr
    payload2 = json.loads(res2.stdout.strip().splitlines()[-1])
    assert payload2["reused"] is True

    # Drop a sentinel inside OUT then re-run with --force; sentinel must vanish.
    sentinel = out / ".sentinel"
    sentinel.write_text("hi")
    # Use a different profile path to force a re-export. We don't have a way
    # to mutate a built-in profile, so instead we just use --force which forces
    # the re-export path even when manifests match.
    res3 = _run([*_base_args(out), "--force"])
    assert res3.returncode == 0, res3.stderr
    assert not sentinel.exists()


def test_require_reviewed_rejects_unreviewed(tmp_path: Path) -> None:
    """Mini fixture has reviewed=False; --require-reviewed must trip."""
    out = tmp_path / "OUT"
    res = _run([*_base_args(out), "--require-reviewed"])
    assert res.returncode == 2, f"stdout={res.stdout}\nstderr={res.stderr}"
    err = json.loads(res.stderr.strip().splitlines()[-1])
    assert err["error_code"] == "EXPORT_NOT_REVIEWED"


def test_unknown_profile_emits_structured_error(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    res = _run(
        [
            "export",
            "--dataset", str(DATASET),
            "--runs-root", str(RUNS_ROOT),
            "--target-phase", "4",
            "--profile", "definitely-not-a-real-profile",
            "--out", str(out),
        ]
    )
    assert res.returncode == 2, res.stderr
    err = json.loads(res.stderr.strip().splitlines()[-1])
    assert err["error_code"] == "EXPORT_PROFILE_NOT_FOUND"


def test_in_place_with_confirm_creates_backup(tmp_path: Path) -> None:
    """--in-place + --yes-i-mean-it actually runs (backup is created)."""
    # Copy the dataset into tmp so we don't mutate the fixture in place.
    import shutil
    dataset_copy = tmp_path / "ds"
    shutil.copytree(DATASET, dataset_copy, symlinks=True)

    res = _run(
        [
            "export",
            "--dataset", str(dataset_copy),
            "--runs-root", str(RUNS_ROOT),
            "--target-phase", "4",
            "--profile", "so101_sarm",
            "--in-place",
            "--yes-i-mean-it",
        ]
    )
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    backups = list(dataset_copy.glob(".mimicanno-backup-*"))
    assert len(backups) == 1
    assert (dataset_copy / ".mimicanno-export.json").is_file()


@pytest.mark.parametrize("opt", ["--allow-degraded", "--allow-unlabeled", "--skip-missing"])
def test_gate_flags_accepted(tmp_path: Path, opt: str) -> None:
    """Smoke-check that each gate flag parses and runs against the mini fixture."""
    out = tmp_path / f"OUT_{opt.lstrip('-')}"
    res = _run([*_base_args(out), opt])
    assert res.returncode == 0, f"{opt}: stderr={res.stderr}"
