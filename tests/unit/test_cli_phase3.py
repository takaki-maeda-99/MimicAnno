# tests/unit/test_cli_phase3.py
"""CLI Tier-1 abort guards + Phase 3 dispatch (spec §8)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app

runner = CliRunner()

_SAM3_IMPORT_CHECK = (
    "mimicanno.object_tracker.sam3_runtime._ensure_transformers_sam3_importable"
)


def _base_args(episode, runs_root: Path) -> list[str]:
    """Shared positional args for all Phase-3 invocations."""
    return [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
    ]


@pytest.fixture()
def episode(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture()
def vlm_model_arg() -> str:
    """A fixture VLM model arg that resolves without network access."""
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    return f"fixture://{fixt}"


@pytest.fixture()
def sam3_ckpt(tmp_path: Path) -> Path:
    """A dummy but existing SAM3 checkpoint file."""
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def _parse_stderr_json(stderr: str) -> dict:
    """Extract the last JSON line from stderr."""
    for line in reversed(stderr.strip().splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise AssertionError(f"No JSON line found in stderr:\n{stderr}")


# ---------------------------------------------------------------------------
# Scenario 1: --target-phase 3 without --sam3-checkpoint
# ---------------------------------------------------------------------------

def test_target_phase_3_without_sam3_checkpoint_aborts(
    episode, vlm_model_arg: str, tmp_path: Path
) -> None:
    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        "--vlm-model", vlm_model_arg,
        "--offline",
        # NO --sam3-checkpoint
    ]
    with mock.patch(_SAM3_IMPORT_CHECK, return_value=None):
        result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 2
    err = _parse_stderr_json(result.stderr)
    assert err["error_code"] == "missing_dependency"
    assert err["context"]["field"] == "--sam3-checkpoint"


# ---------------------------------------------------------------------------
# Scenario 2: --target-phase 3 without --vlm-model
# ---------------------------------------------------------------------------

def test_target_phase_3_without_vlm_model_aborts(
    episode, tmp_path: Path
) -> None:
    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        # NO --vlm-model, NO --sam3-checkpoint
    ]
    result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 2
    err = _parse_stderr_json(result.stderr)
    assert err["error_code"] == "vlm_model_required"


# ---------------------------------------------------------------------------
# Scenario 3: --target-phase 3 with nonexistent --sam3-checkpoint path
# ---------------------------------------------------------------------------

def test_target_phase_3_with_missing_sam3_checkpoint_path_aborts(
    episode, vlm_model_arg: str, tmp_path: Path
) -> None:
    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        "--vlm-model", vlm_model_arg,
        "--offline",
        "--sam3-checkpoint", "/tmp/nonexistent_mimicanno_test_ckpt.pt",
    ]
    with mock.patch(_SAM3_IMPORT_CHECK, return_value=None):
        result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 2
    err = _parse_stderr_json(result.stderr)
    assert err["error_code"] == "sam3_checkpoint_not_found"


# ---------------------------------------------------------------------------
# Scenario 4: --target-phase 3 dispatches to annotate_episode_phase3
# ---------------------------------------------------------------------------

def test_target_phase_3_dispatches_to_phase3_orchestrator(
    episode, vlm_model_arg: str, sam3_ckpt: Path, tmp_path: Path
) -> None:
    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        "--vlm-model", vlm_model_arg,
        "--offline",
        "--sam3-checkpoint", str(sam3_ckpt),
    ]
    with (
        mock.patch(_SAM3_IMPORT_CHECK, return_value=None),
        mock.patch("mimicanno.cli.annotate_episode_phase3") as mock_p3,
        mock.patch("mimicanno.cli.annotate_episode") as mock_p1,
    ):
        result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 0, result.output + result.stderr
    mock_p3.assert_called_once()
    mock_p1.assert_not_called()

    req = mock_p3.call_args[0][0]
    assert req.config.target_phase == 3


# ---------------------------------------------------------------------------
# Scenario 5: --track-stride-frames resolved into TrackingConfig
# ---------------------------------------------------------------------------

def test_track_stride_frames_flag_resolved_into_tracking_config(
    episode, vlm_model_arg: str, sam3_ckpt: Path, tmp_path: Path
) -> None:
    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        "--vlm-model", vlm_model_arg,
        "--offline",
        "--sam3-checkpoint", str(sam3_ckpt),
        "--track-stride-frames", "4",
    ]
    with (
        mock.patch(_SAM3_IMPORT_CHECK, return_value=None),
        mock.patch("mimicanno.cli.annotate_episode_phase3") as mock_p3,
    ):
        result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 0, result.output + result.stderr
    mock_p3.assert_called_once()
    req = mock_p3.call_args[0][0]
    assert req.config.tracking is not None
    assert req.config.tracking.track_stride_frames == 4


# ---------------------------------------------------------------------------
# Scenario 6: sam3 extras not importable → sam3_extras_missing
# ---------------------------------------------------------------------------

def test_target_phase_3_with_sam3_extras_missing(
    episode, vlm_model_arg: str, tmp_path: Path
) -> None:
    from mimicanno.errors import SAM3ExtrasMissing

    args = [
        *_base_args(episode, tmp_path / "runs"),
        "--target-phase", "3",
        "--vlm-model", vlm_model_arg,
        "--offline",
        "--sam3-checkpoint", "/does/not/matter.pt",
    ]
    with mock.patch(_SAM3_IMPORT_CHECK, side_effect=SAM3ExtrasMissing()):
        result = runner.invoke(app, args, catch_exceptions=False)

    assert result.exit_code == 2
    err = _parse_stderr_json(result.stderr)
    assert err["error_code"] == "sam3_extras_missing"
