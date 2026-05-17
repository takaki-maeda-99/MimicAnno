"""E2E test — retry succeeds at frame N/2 (spec §8.2).

Frame 0 yields zero object detections; the retry helper picks frame 60
(= int(0.5 * 120)) where the object IS detectable. Pipeline completes
phase 3 successfully and manifest records the retry.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from mimicanno.object_tracker.propagator import BBox
from mimicanno.object_tracker.fixtures import FixtureSAM3Tracker
from mimicanno.object_tracker.planner import EntityPlan
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    build_full_propagation,
    patch_phase3,
)

runner = CliRunner()

# synthesize_aloha_episode default: n_frames=120, fps=30.
# stride = max(1, round(30/3)) = 10 → propagation frames [0,10,...,110,119]
_N_FRAMES = 120
_RETRY_FRAME = 60  # int(0.5 * 120) — first retry fraction=0.5
_PROP_FRAMES: tuple[int, ...] = (
    0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 119,
)
_TAPE_BBOX = BBox(x=0.1, y=0.1, w=0.2, h=0.2)
_CLAW_BBOX = BBox(x=0.3, y=0.3, w=0.1, h=0.1)


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def test_retry_succeeds_at_midpoint(
    episode, sam3_ckpt: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry grounding at frame 60 succeeds; manifest records 2 attempts."""
    runs_root = tmp_path / "runs"

    # Frame 0: tape NOT detectable (empty list), claw is detectable.
    # Frame 60: tape IS detectable.
    # All other frame indices: fall back to empty (not called during grounding).
    entities = EntityPlan(
        object_prompts=["tape"],
        target_prompts=[],
        tool_prompts=["claw"],
    )
    sam3 = FixtureSAM3Tracker(
        initial_detections_by_frame={
            0: {
                "tape": [],
                "claw": [(_CLAW_BBOX, 0.9)],
            },
            _RETRY_FRAME: {
                "tape": [(_TAPE_BBOX, 0.9)],
                "claw": [(_CLAW_BBOX, 0.9)],
            },
        },
        propagation_results={
            f: {
                "tape": (_TAPE_BBOX, 0.9),
                "claw": (_CLAW_BBOX, 0.9),
            }
            for f in _PROP_FRAMES
        },
    )

    # Monkey-patch propagator._extract_frame_at so the retry helper can read
    # canned frames without real video I/O. Must be patched AFTER
    # mimicanno.pipeline has been imported (which wires the real impl in).
    import mimicanno.object_tracker.propagator as _propagator_mod
    _canned_frame = np.zeros((64, 64, 3), dtype=np.uint8)

    def _fake_extract_frame_at(
        video_path: object, n_frames: int, frame_index: int,
    ) -> np.ndarray:
        return _canned_frame

    monkeypatch.setattr(_propagator_mod, "_extract_frame_at", _fake_extract_frame_at)

    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(episode.video),
                "--parquet", str(episode.parquet),
                "--task", "pick up the tape",
                "--robot", "aloha",
                "--target-phase", "3",
                "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
                "--offline",
                "--sam3-checkpoint", str(sam3_ckpt),
                "--runs-root", str(runs_root),
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output + (result.stderr or "")

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    ps = manifest["pipeline_status"]

    # No degrade: phase 3 completed successfully
    assert ps.get("degrade_reason") is None
    assert ps.get("degraded_from_phase") is None
    assert ps["object_state_available"] is True

    # Retry was used: adopted frame = 60
    assert ps["adopted_frame_index"] == _RETRY_FRAME

    # Two grounding attempts recorded
    attempts = ps["grounding_attempts"]
    assert len(attempts) == 2, f"Expected 2 attempts, got {len(attempts)}: {attempts}"

    # First attempt: frame 0, not adopted
    assert attempts[0]["frame_index"] == 0
    assert attempts[0]["adopted"] is False

    # Second attempt: frame 60, adopted
    assert attempts[1]["frame_index"] == _RETRY_FRAME
    assert attempts[1]["adopted"] is True

    # Propagator was driven bidirectionally from the anchor frame
    assert sam3.last_anchor_frame_index == _RETRY_FRAME
    assert sam3.last_propagation_direction == "both"
