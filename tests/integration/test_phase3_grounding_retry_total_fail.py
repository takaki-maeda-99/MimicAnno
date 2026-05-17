"""E2E test — all 4 attempts fail; pipeline degrades (spec §8.2).

Frame 0, 60 (int(0.5*120)), 30 (int(0.25*120)), and 90 (int(0.75*120))
all yield zero tape detections. The retry helper exhausts all candidates and
Phase 3 degrades with degrade_reason="sam3_no_initial_detection".
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from mimicanno.object_tracker.propagator import BBox
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    EntityPlan,
    FixtureSAM3Tracker,
    patch_phase3,
)

runner = CliRunner()

# synthesize_aloha_episode default: n_frames=120, fps=30.
# retry_fractions default: [0.5, 0.25, 0.75]
# Attempt frames: [0, int(0.5*120)=60, int(0.25*120)=30, int(0.75*120)=90]
_N_FRAMES = 120
_RETRY_FRAMES = [0, 60, 30, 90]
_CLAW_BBOX = BBox(x=0.3, y=0.3, w=0.1, h=0.1)


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def test_retry_total_failure_degrades(
    episode, sam3_ckpt: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 4 grounding attempts fail; manifest records degrade with 4 attempts."""
    runs_root = tmp_path / "runs"

    entities = EntityPlan(
        object_prompts=["tape"],
        target_prompts=[],
        tool_prompts=["claw"],
    )

    # tape returns empty list at every retry frame; claw succeeds (to confirm
    # the planner side has some detections — it's the tape absence that triggers
    # degrade because tape is in object_prompts).
    sam3 = FixtureSAM3Tracker(
        initial_detections_by_frame={
            frame: {
                "tape": [],
                "claw": [(_CLAW_BBOX, 0.9)],
            }
            for frame in _RETRY_FRAMES
        },
    )

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

    # Pipeline degraded
    assert ps["degrade_reason"] == "sam3_no_initial_detection"
    assert ps["degraded_from_phase"] == 3
    assert ps.get("adopted_frame_index") is None

    # All 4 attempts recorded, none adopted
    attempts = ps["grounding_attempts"]
    assert len(attempts) == 4, f"Expected 4 attempts, got {len(attempts)}: {attempts}"
    assert [a["frame_index"] for a in attempts] == _RETRY_FRAMES
    assert all(a["adopted"] is False for a in attempts)
