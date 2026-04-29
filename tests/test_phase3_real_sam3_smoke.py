"""Layer 3 manual smoke (spec §10.3 / §11 #10).

Real Gemma + real SAM3 against a real LeRobot episode (lerobot/svla_so100_pickplace
ep0 by default — same dataset used in `docs/phase1-real-data-verification.md`).

NOT part of the CI gate — set both env vars to enable.

```bash
export MIMICANNO_RUN_SAM3_SMOKE=1
export MIMICANNO_SAM3_CHECKPOINT=/path/to/sam3.ckpt
# optional: override the episode used (defaults to lerobot/svla_so100_pickplace ep0)
export MIMICANNO_REAL_VIDEO=/path/to/episode_000.mp4
export MIMICANNO_REAL_PARQUET=/path/to/episode_000.parquet
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/test_phase3_real_sam3_smoke.py -v -s
```
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_SAM3_SMOKE") != "1"
    or not os.environ.get("MIMICANNO_SAM3_CHECKPOINT"),
    reason=(
        "Set MIMICANNO_RUN_SAM3_SMOKE=1 and MIMICANNO_SAM3_CHECKPOINT to run; "
        "this is a Layer 3 manual smoke that requires a GPU + sam3 weights."
    ),
)

runner = CliRunner()


def _resolve_real_episode() -> tuple[Path, Path]:
    """Pick the real episode to run against. Defaults to a known-good
    extraction location; override via MIMICANNO_REAL_{VIDEO,PARQUET}."""
    video_env = os.environ.get("MIMICANNO_REAL_VIDEO")
    parquet_env = os.environ.get("MIMICANNO_REAL_PARQUET")
    if video_env and parquet_env:
        return Path(video_env), Path(parquet_env)
    pytest.skip(
        "Set MIMICANNO_REAL_VIDEO and MIMICANNO_REAL_PARQUET to point at an "
        "extracted lerobot episode (use tools/extract_lerobot_episode.py)."
    )


def test_phase3_real_sam3_on_lerobot_ep0(tmp_path: Path) -> None:
    """Spec §11 #10: end-to-end Phase 3 against a real episode produces a
    tracks.json with at least one substantive track and
    pipeline_status.object_state_available=True."""
    video, parquet = _resolve_real_episode()
    sam3_ckpt = Path(os.environ["MIMICANNO_SAM3_CHECKPOINT"])
    vlm_model = os.environ.get("MIMICANNO_VLM_MODEL", "google/gemma-4-E2B-it")

    runs_root = tmp_path / "runs"
    result = runner.invoke(app, [
        "annotate",
        "--video", str(video),
        "--parquet", str(parquet),
        "--task", "Pick up the cube and place it in the box.",
        "--robot", "so100",
        "--target-phase", "3",
        "--vlm-model", vlm_model,
        "--sam3-checkpoint", str(sam3_ckpt),
        "--runs-root", str(runs_root),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    tracks = json.loads((run_dir / "tracks.json").read_text())

    assert manifest["pipeline_status"]["object_state_available"] is True
    coverage = manifest["pipeline_status"]["object_state_segment_coverage"]
    assert coverage is not None and coverage >= 0.5, (
        f"object_state_segment_coverage={coverage} below 0.5 threshold"
    )

    long_object_tracks = [
        t for t in tracks["tracks"]
        if t["role"] == "object" and len(t["samples"]) >= 10
    ]
    assert long_object_tracks, (
        "expected ≥1 object track with ≥10 samples in tracks.json"
    )
