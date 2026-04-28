"""CLI Tier 1 abort paths (spec §4.2)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def _run(tmp_path, *args: str) -> subprocess.CompletedProcess:
    video = tmp_path / "v.mp4"
    parquet = tmp_path / "p.parquet"
    video.write_bytes(b"")
    parquet.write_bytes(b"")
    return subprocess.run(
        [
            sys.executable, "-m", "mimicanno.cli", "annotate",
            "--video", str(video),
            "--parquet", str(parquet),
            "--task", "x",
            "--robot", "aloha",
            *args,
        ],
        capture_output=True,
        text=True,
    )


def test_target_phase_2_without_vlm_model_aborts(tmp_path) -> None:
    p = _run(tmp_path, "--target-phase", "2")
    assert p.returncode != 0
    err_lines = [line for line in p.stderr.strip().splitlines() if line.startswith("{")]
    obj = json.loads(err_lines[-1])
    assert obj["error_code"] == "vlm_model_required"


def test_offline_without_explicit_sha_aborts(tmp_path) -> None:
    p = _run(tmp_path, "--target-phase", "2", "--vlm-model", "google/gemma-x", "--offline")
    assert p.returncode != 0
    err_lines = [line for line in p.stderr.strip().splitlines() if line.startswith("{")]
    obj = json.loads(err_lines[-1])
    assert obj["error_code"] == "vlm_model_not_found"
