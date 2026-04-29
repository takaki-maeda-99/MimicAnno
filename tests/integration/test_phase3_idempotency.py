"""Spec §11 #6: Running Phase 3 twice with identical inputs + config produces
identical canonical_name / config_hash / run_hash, and structurally identical
artifact contents.
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

# Fields whose values vary run-to-run by design (timestamps in particular).
# They are scrubbed before comparing the parsed JSON dicts.
_VOLATILE_FIELDS = ("generated_at",)


def _scrub(d: object) -> object:
    if isinstance(d, dict):
        return {k: _scrub(v) for k, v in d.items() if k not in _VOLATILE_FIELDS}
    if isinstance(d, list):
        return [_scrub(x) for x in d]
    return d


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def _make_sam3() -> FixtureSAM3Tracker:
    bbox = BBox(x=0.4, y=0.4, w=0.1, h=0.1)
    return FixtureSAM3Tracker(
        initial_detections={"red block": [(bbox, 0.95)]},
        propagation_results=build_full_propagation(prompts=["red block"], bbox=bbox, score=0.9),
    )


def _invoke(episode, sam3_ckpt: Path, runs_root: Path) -> int:
    entities = EntityPlan(object_prompts=["red block"], target_prompts=[], tool_prompts=[])
    with patch_phase3(entities=entities, sam3_tracker=_make_sam3()):
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
    return result.exit_code


def _read_run(runs_root: Path) -> dict:
    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    return {
        "name": run_dir.name,
        "manifest": json.loads((run_dir / "manifest.json").read_text()),
        "annotation": json.loads((run_dir / "annotation.json").read_text()),
        "boundaries": json.loads((run_dir / "boundaries.json").read_text()),
        "tracks": json.loads((run_dir / "tracks.json").read_text()),
        "signals": json.loads((run_dir / "signals.json").read_text()),
    }


def test_phase3_idempotency_byte_equal_hashes_and_structural_artifacts(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    runs_a = tmp_path / "runs_a"
    runs_b = tmp_path / "runs_b"

    assert _invoke(episode, sam3_ckpt, runs_a) == 0
    assert _invoke(episode, sam3_ckpt, runs_b) == 0

    a = _read_run(runs_a)
    b = _read_run(runs_b)

    # canonical_name + config_hash + run_hash MUST be byte-identical.
    assert a["name"] == b["name"]
    assert a["manifest"]["config_hash"] == b["manifest"]["config_hash"]
    assert a["manifest"]["run_hash"] == b["manifest"]["run_hash"]

    # Structural equality (with timestamps scrubbed) on the rest.
    for key in ("boundaries", "annotation", "tracks", "signals"):
        assert _scrub(a[key]) == _scrub(b[key]), f"artifact diverged: {key}"
    # And on manifest with timestamps + input absolute paths scrubbed.
    a_m = _scrub(a["manifest"])
    b_m = _scrub(b["manifest"])
    # Input paths embed tmp dirs that differ between runs; check the sha
    # only (the sha is the integrity-relevant part of manifest.inputs).
    for inp in (a_m["inputs"], b_m["inputs"]):
        for ref in inp.values():
            ref.pop("path", None)
    assert a_m == b_m
