"""Phase 3 happy-path smoke (spec §11 #1).

End-to-end Phase 3 invocation through `mimicanno.cli.app` against the
synthetic Aloha episode, with `LocalGemmaVLMLabeler` /
`LocalGemmaTrackingPlanner` / `SAM3Runtime` substituted by the test
doubles in `mimicanno.object_tracker.fixtures`. No GPU.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from mimicanno.io import read_tracks_json
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    BBox,
    EntityPlan,
    FixtureSAM3Tracker,
    build_full_propagation,
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


def _phase3_cli_args(
    *, episode, runs_root: Path, sam3_ckpt: Path
) -> list[str]:
    return [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick the red block and place in white bin",
        "--robot", "aloha",
        "--target-phase", "3",
        "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
        "--offline",
        "--sam3-checkpoint", str(sam3_ckpt),
        "--runs-root", str(runs_root),
    ]


def test_phase3_happy_path_full_artifacts(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """Spec §11 #1: full Phase 3 run produces all 6 artifacts (incl. tracks.json),
    pipeline_status.object_state_available=True, segment_coverage=1.0."""
    runs_root = tmp_path / "runs"
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["white bin"],
        tool_prompts=[],
    )
    bbox = BBox(x=0.4, y=0.4, w=0.1, h=0.1)
    sam3 = FixtureSAM3Tracker(
        initial_detections={
            "red block": [(bbox, 0.95)],
            "white bin": [(bbox, 0.95)],
        },
        propagation_results=build_full_propagation(
            prompts=["red block", "white bin"], bbox=bbox, score=0.9,
        ),
    )

    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase3_cli_args(episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt),
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    for name in ("video.mp4", "signals.json", "boundaries.json",
                 "annotation.json", "tracks.json", "manifest.json"):
        assert (run_dir / name).exists(), f"missing artifact: {name}"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["pipeline_status"]["object_state_available"] is True
    assert manifest["pipeline_status"]["object_state_segment_coverage"] == 1.0
    assert manifest["pipeline_status"]["degraded_from_phase"] is None
    assert manifest["pipeline_status"]["degrade_reason"] is None

    assert manifest["model_versions"]["sam3"] == "facebook/sam3"
    sam3_ckpt_field = manifest["model_versions"]["sam3_checkpoint"]
    assert isinstance(sam3_ckpt_field, str) and sam3_ckpt_field.startswith("sha256:")

    artifact_roles = {(a["role"], a["url"]) for a in manifest["artifacts"]}
    assert ("tracks", "tracks.json") in artifact_roles

    annotation = json.loads((run_dir / "annotation.json").read_text())
    assert annotation["segments"], "expected at least one segment"
    for seg in annotation["segments"]:
        assert seg["label_source"] == "vlm_with_object_state"
        assert seg["object_state_unavailable"] is False
        assert seg["object_track_ids"], (
            f"segment {seg['segment_id']} has no object_track_ids"
        )

    fps = float(manifest["fps"])
    tracks_file = read_tracks_json(run_dir / "tracks.json")
    assert tracks_file.tracks, "tracks.json.tracks must be non-empty"
    # Cross-artifact integrity (spec §3.3) — the file must round-trip with
    # the manifest's (episode_id, fps) and its own n_frames.
    read_tracks_json(
        run_dir / "tracks.json",
        expected=(manifest["episode_id"], fps, tracks_file.n_frames),
    )
