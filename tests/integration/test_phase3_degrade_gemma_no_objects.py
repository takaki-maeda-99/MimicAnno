"""Whole-run degrade — gemma_no_object_prompts (spec §7.2).

When the planner returns zero object prompts, Phase 3 degrades to the
object-state-unavailable path. tracks.json is NOT written, every segment
is `vlm_robot_state_only`, and `annotation.notes` is the canonical
no-PII message.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    EntityPlan,
    patch_phase3,
)

runner = CliRunner()

_FORBIDDEN_NOTES_SUBSTRINGS = ("Traceback", "at 0x", "RuntimeError", "/home/", "/tmp/")


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def test_degrade_gemma_no_object_prompts(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    entities = EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])

    with patch_phase3(entities=entities):
        result = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(episode.video),
                "--parquet", str(episode.parquet),
                "--task", "pick anything",
                "--robot", "aloha",
                "--target-phase", "3",
                "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
                "--offline",
                "--sam3-checkpoint", str(sam3_ckpt),
                "--runs-root", str(runs_root),
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    assert manifest["pipeline_status"]["object_state_available"] is False
    assert manifest["pipeline_status"]["degraded_from_phase"] == 3
    assert manifest["pipeline_status"]["degrade_reason"] == "gemma_no_object_prompts"
    assert manifest["pipeline_status"]["object_state_segment_coverage"] == 0.0

    assert not (run_dir / "tracks.json").exists()
    assert not any(a["role"] == "tracks" for a in manifest["artifacts"])

    expected_note = (
        "phase3: degraded to object-state-unavailable path "
        "(degrade_reason=gemma_no_object_prompts)."
    )
    assert annotation["notes"] == expected_note
    for forbidden in _FORBIDDEN_NOTES_SUBSTRINGS:
        assert forbidden not in annotation["notes"]

    # The two Phase 3 object-derived sources are forcibly disabled on degrade
    # (spec §7.2) — independent of the active boundary weights.
    disabled = manifest["pipeline_params"]["boundary"]["disabled_sources"]
    assert "gripper_object_distance_threshold_crossing" in disabled
    assert "object_motion_start_stop" in disabled

    for seg in annotation["segments"]:
        assert seg["label_source"] == "vlm_robot_state_only"
        assert seg["object_state_unavailable"] is True
        assert seg["object_track_ids"] == []
