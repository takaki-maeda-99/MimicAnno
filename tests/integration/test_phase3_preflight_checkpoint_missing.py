"""Spec §11 #3: when --sam3-checkpoint points to a missing path, preflight
fails (exit 2, structured `sam3_checkpoint_not_found`) BEFORE any run dir
is published.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import FIXTURE_VLM_OK_FIRST_TRY

runner = CliRunner()


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


def _last_json_line(stderr: str) -> dict:
    for line in reversed(stderr.strip().splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON in stderr:\n{stderr}")


def test_preflight_sam3_checkpoint_missing_aborts_before_publish(
    episode, tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    bogus = tmp_path / "definitely_missing_sam3.ckpt"
    assert not bogus.exists()

    # Stub the import check so this test isolates the missing-path failure
    # (without requiring the sam3 backend to be installed in CI).
    from unittest import mock
    with mock.patch(
        "mimicanno.object_tracker.sam3_runtime._ensure_transformers_sam3_importable",
        return_value=None,
    ):
        result = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(episode.video),
                "--parquet", str(episode.parquet),
                "--task", "pick",
                "--robot", "aloha",
                "--target-phase", "3",
                "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
                "--offline",
                "--sam3-checkpoint", str(bogus),
                "--runs-root", str(runs_root),
            ],
            catch_exceptions=False,
        )

    assert result.exit_code != 0
    err = _last_json_line(result.stderr)
    assert err["error_code"] == "sam3_checkpoint_not_found"
    # No run dir should have been published before preflight fired.
    assert not runs_root.exists() or not any(runs_root.iterdir())
