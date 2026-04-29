"""Per-segment fallback (spec §6, §11 #5).

Per-segment fallback is NOT a whole-run degrade: when the primary object
isn't visible enough in a segment, only that segment falls back to the
Phase 2 robot-state-only prompt. `pipeline_status.object_state_available`
stays True; `object_state_segment_coverage` drops below 1.0.
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
    BBox,
    EntityPlan,
    FixtureSAM3Tracker,
    patch_phase3,
)

runner = CliRunner()


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def test_per_segment_fallback_preserves_run(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """First segment loses the primary object → that segment falls back to
    `vlm_robot_state_only`; other segments keep `vlm_with_object_state`."""
    runs_root = tmp_path / "runs"
    bbox = BBox(x=0.4, y=0.4, w=0.1, h=0.1)
    bin_bbox = BBox(x=0.7, y=0.7, w=0.1, h=0.1)

    # Synth episode @30fps, 120 frames, stride=10 → propagation frames:
    # 0,10,20,30,40,50,60,70,80,90,100,110,119. Make "red block" missing for
    # frames 0..40 so the segment containing those frames sees the primary
    # object as not-visible-enough; from frame 50 onward it's reacquired.
    propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] = {}
    for f in (0, 10, 20, 30, 40):
        propagation_results[f] = {"red block": None, "white bin": (bin_bbox, 0.9)}
    for f in (50, 60, 70, 80, 90, 100, 110, 119):
        propagation_results[f] = {
            "red block": (bbox, 0.9),
            "white bin": (bin_bbox, 0.9),
        }

    sam3 = FixtureSAM3Tracker(
        initial_detections={
            "red block": [(bbox, 0.95)],
            "white bin": [(bin_bbox, 0.95)],
        },
        propagation_results=propagation_results,
    )
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["white bin"],
        tool_prompts=[],
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
                # Lower score_threshold so the synthesized episode emits multiple
                # segments — gripper transitions in the synth are too gentle for
                # the default 0.30 cutoff (we just need ≥ 2 segments to demonstrate
                # partial coverage).
                "--score-threshold", "0.10",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    # tracks.json IS written even when one segment falls back.
    assert (run_dir / "tracks.json").exists()

    # Spec §6: per-segment fallback is NOT a degrade.
    assert manifest["pipeline_status"]["object_state_available"] is True
    assert manifest["pipeline_status"]["degraded_from_phase"] is None
    coverage = manifest["pipeline_status"]["object_state_segment_coverage"]
    assert 0.0 < coverage < 1.0, f"expected partial coverage; got {coverage}"

    segments = annotation["segments"]
    fallback = [s for s in segments if s["label_source"] == "vlm_robot_state_only"]
    phase3_seg = [s for s in segments if s["label_source"] == "vlm_with_object_state"]
    assert fallback, "expected at least one fallback segment"
    assert phase3_seg, "expected at least one Phase 3 segment"

    for seg in fallback:
        assert seg["object_state_unavailable"] is True
        assert seg["object_track_ids"] == []

    for seg in phase3_seg:
        assert seg["object_state_unavailable"] is False
        assert seg["object_track_ids"]
