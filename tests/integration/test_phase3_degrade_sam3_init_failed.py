"""Whole-run degrade — sam3_init_failed (spec §7.2 / §8 PII rule).

When SAM3Runtime.load() raises SAM3InitFailed, the orchestrator degrades
and the underlying error message MUST NOT leak into `annotation.notes`.
The original error repr can still appear in stderr WARN lines (used by
operators to diagnose), but never in published artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from mimicanno.errors import SAM3InitFailed
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    EntityPlan,
    FixtureSAM3Tracker,
    patch_phase3,
)

runner = CliRunner()

# A deliberately leaky underlying error. None of these substrings may appear
# in `annotation.notes` (PII rule).
_PII_PAYLOAD = "CUDA OOM at /home/u/sam3.ckpt loading 8.2GB into device 0 with token sk_xxx"
_PII_FRAGMENTS = (
    "CUDA OOM",
    "/home/u/sam3.ckpt",
    "sk_xxx",
    "RuntimeError",
    "loading 8.2GB",
    "Traceback",
    "at 0x",
)


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def test_degrade_sam3_init_failed(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    runs_root = tmp_path / "runs"
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=[],
        tool_prompts=[],
    )
    sam3 = FixtureSAM3Tracker(
        raise_on_load=SAM3InitFailed(underlying=_PII_PAYLOAD),
    )

    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(episode.video),
                "--parquet", str(episode.parquet),
                "--task", "pick the red block",
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
    assert manifest["pipeline_status"]["degrade_reason"] == "sam3_init_failed"
    assert manifest["pipeline_status"]["object_state_segment_coverage"] == 0.0

    assert not (run_dir / "tracks.json").exists()
    assert not any(a["role"] == "tracks" for a in manifest["artifacts"])

    expected_note = (
        "phase3: degraded to object-state-unavailable path "
        "(degrade_reason=sam3_init_failed)."
    )
    assert annotation["notes"] == expected_note
    for fragment in _PII_FRAGMENTS:
        assert fragment not in (annotation["notes"] or ""), (
            f"PII fragment {fragment!r} leaked into annotation.notes"
        )

    disabled = manifest["pipeline_params"]["boundary"]["disabled_sources"]
    assert "gripper_object_distance_threshold_crossing" in disabled
    assert "object_motion_start_stop" in disabled

    for seg in annotation["segments"]:
        assert seg["label_source"] == "vlm_robot_state_only"
        assert seg["object_state_unavailable"] is True
        assert seg["object_track_ids"] == []

    # Optional PII-positive: the underlying repr SHOULD reach the WARN log so
    # operators can diagnose. CliRunner captures stderr.
    assert "WARN: phase3 degrade sam3_init_failed" in result.stderr
    assert "CUDA OOM" in result.stderr
