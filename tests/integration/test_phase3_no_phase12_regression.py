"""Spec §11 #3: Phase 1 + Phase 2 invocations on the curated synth episode
produce manifest hashes byte-identical to pinned pre-Phase-3 baselines.

This is an end-to-end equivalent of `tests/unit/test_phase3_hash_gating.py`
— the unit version pins `compute_config_hash` against synthetic
`AnnotationConfig`s, while this test pins what an actual `mimicanno annotate`
invocation produces against `synthesize_aloha_episode` so that any plumbing-
level regression (CLI flag wiring, hash payload composition) is caught.
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

# Pinned hashes captured 2026-04-29 from `mimicanno annotate` against
# `synthesize_aloha_episode(out_dir=…/data)`. These must NEVER change without
# bumping the relevant schema_version.
PHASE1_CONFIG_HASH = "sha256:f6de5eb8209e1d4d902370c4fe63ebfb7cb32284d2f8528ec44f20c8e387b115"
PHASE1_RUN_HASH = "sha256:d44413ef6bc3fac464a1b9649af8e6e03fa8434e1befb32b7a2674114e3a675e"
PHASE1_INPUT_HASH = "sha256:b9f7cb2225e3bff95c312299fa896890221bcd018e1e07aa6b5308991c3b3e15"

# Phase 2 config_hash bumped 2026-05-06 with `VLMConfig.mask_overlay` introduction.
PHASE2_CONFIG_HASH = "sha256:9a2758d7e5b76c942705ce9dc1534d3be74fddc8127e442d05c266dbc8bb166c"
PHASE2_RUN_HASH = "sha256:875c05a5fde4ad63123f7cc3914ecd1b52ab25943efd4f4f525536c44fcbd7e0"
PHASE2_INPUT_HASH = "sha256:b9f7cb2225e3bff95c312299fa896890221bcd018e1e07aa6b5308991c3b3e15"


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


def _run_dir(runs_root: Path) -> Path:
    [d] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    return d


def test_phase1_invocation_produces_pinned_hashes(episode, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    result = runner.invoke(app, [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick", "--robot", "aloha",
        "--target-phase", "1",
        "--runs-root", str(runs),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr

    manifest = json.loads((_run_dir(runs) / "manifest.json").read_text())
    assert manifest["config_hash"] == PHASE1_CONFIG_HASH
    assert manifest["run_hash"] == PHASE1_RUN_HASH
    assert manifest["input_hash"] == PHASE1_INPUT_HASH
    assert manifest["generator"]["pipeline_phase"] == 1
    assert "tracking" not in manifest["pipeline_params"]
    assert "vlm" not in manifest["pipeline_params"]


def test_phase2_invocation_produces_pinned_hashes(episode, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    result = runner.invoke(app, [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
        "--offline",
        "--runs-root", str(runs),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr

    manifest = json.loads((_run_dir(runs) / "manifest.json").read_text())
    assert manifest["config_hash"] == PHASE2_CONFIG_HASH
    assert manifest["run_hash"] == PHASE2_RUN_HASH
    assert manifest["input_hash"] == PHASE2_INPUT_HASH
    assert manifest["generator"]["pipeline_phase"] == 2
    assert "tracking" not in manifest["pipeline_params"]
    assert "vlm" in manifest["pipeline_params"]
