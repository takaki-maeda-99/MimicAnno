"""Smoke test that pipeline.annotate_episode() composes the full chain.

Heavier end-to-end tests live alongside CLI tests under integration/.
"""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_annotate_synthetic_aloha_smoke(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    from mimicanno.pipeline import AnnotateRequest, annotate_episode
    from mimicanno.config import (
        AnnotationConfig, BoundaryConfig, ModelConfig,
    )

    inputs = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    req = AnnotateRequest(
        video=inputs.video,
        parquet=inputs.parquet,
        task="pick red block",
        robot_adapter_name="aloha",
        robot_adapter_config_path=None,
        labels_path=None,         # use bundled manipulation.yaml
        runs_root=tmp_path / "runs",
        link_video=False,
        force=False,
        config=AnnotationConfig(
            boundary=BoundaryConfig(
                weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
                thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
                merge_window_sec=0.10,
                score_threshold=0.30,
                disabled_sources=[],
            ),
            target_phase=1,
            model_config=ModelConfig(None, None, None, None),
        ),
    )
    result = annotate_episode(req)
    final = result.run_dir
    assert (final / "manifest.json").exists()
    assert (final / "annotation.json").exists()
    assert (final / "boundaries.json").exists()
    assert (final / "signals.json").exists()
    assert (final / "video.mp4").exists()
    manifest = json.loads((final / "manifest.json").read_text())
    assert manifest["episode_id"] == inputs.episode_id
    assert manifest["pipeline_status"]["object_state_available"] is False
