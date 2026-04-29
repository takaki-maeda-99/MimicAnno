"""Spec §11: Same inputs run with --target-phase 1, 2, 3 produce 3 distinct
canonical_names, 3 distinct config_hash values, 3 distinct run dirs.
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


def _run_phase1(episode, runs_root: Path) -> str:
    result = runner.invoke(app, [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick", "--robot", "aloha",
        "--target-phase", "1",
        "--runs-root", str(runs_root),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr
    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    return run_dir.name


def _run_phase2(episode, runs_root: Path) -> str:
    result = runner.invoke(app, [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
        "--offline",
        "--runs-root", str(runs_root),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr
    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    return run_dir.name


def _run_phase3(episode, sam3_ckpt: Path, runs_root: Path) -> str:
    bbox = BBox(x=0.4, y=0.4, w=0.1, h=0.1)
    sam3 = FixtureSAM3Tracker(
        initial_detections={"red block": [(bbox, 0.95)]},
        propagation_results=build_full_propagation(prompts=["red block"], bbox=bbox, score=0.9),
    )
    entities = EntityPlan(object_prompts=["red block"], target_prompts=[], tool_prompts=[])
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(app, [
            "annotate",
            "--video", str(episode.video),
            "--parquet", str(episode.parquet),
            "--task", "pick", "--robot", "aloha",
            "--target-phase", "3",
            "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
            "--offline",
            "--sam3-checkpoint", str(sam3_ckpt),
            "--runs-root", str(runs_root),
        ], catch_exceptions=False)
        assert result.exit_code == 0, result.output + result.stderr
    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    return run_dir.name


def test_three_target_phases_produce_three_distinct_runs(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    runs1 = tmp_path / "runs_p1"
    runs2 = tmp_path / "runs_p2"
    runs3 = tmp_path / "runs_p3"

    name1 = _run_phase1(episode, runs1)
    name2 = _run_phase2(episode, runs2)
    name3 = _run_phase3(episode, sam3_ckpt, runs3)

    # 3 distinct canonical_names.
    assert len({name1, name2, name3}) == 3, (name1, name2, name3)

    # 3 distinct config_hash values (read from each run's manifest).
    h1 = json.loads((runs1 / name1 / "manifest.json").read_text())["config_hash"]
    h2 = json.loads((runs2 / name2 / "manifest.json").read_text())["config_hash"]
    h3 = json.loads((runs3 / name3 / "manifest.json").read_text())["config_hash"]
    assert len({h1, h2, h3}) == 3, (h1, h2, h3)

    # And 3 distinct run dirs (already implied by the names but explicit).
    assert (runs1 / name1).is_dir()
    assert (runs2 / name2).is_dir()
    assert (runs3 / name3).is_dir()
