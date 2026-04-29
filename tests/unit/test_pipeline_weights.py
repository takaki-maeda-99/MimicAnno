# tests/unit/test_pipeline_weights.py
"""Regression test: BoundaryConfig short-key weights must reach integrated_candidates.

Real-data smoke test on lerobot/svla_so100_pickplace caught that
BoundaryConfig.weights short keys ("gripper", "velocity", ...) were not
translated to the long detector source names ("gripper_transition", ...) before
being passed to integrated_candidates().  The result was every event scored 0.0
and every candidate was silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_annotate_episode_short_weight_keys_yield_candidates(tmp_path: Path):
    """Pipeline must emit >= 1 boundary candidate when a clear gripper transition
    is present and short-key BoundaryConfig weights are used (the spec §4.3 form).
    """
    from mimicanno.config import (
        AnnotationConfig,
        BoundaryConfig,
        BoundaryWeights,
        ModelConfig,
    )
    from mimicanno.pipeline import AnnotateRequest, annotate_episode
    from tests.fixtures.synthesize import synthesize_aloha_episode

    # synthesize_aloha_episode plants a hard gripper close at frame 50 and open
    # at frame 90, giving |delta| = 1.0 — well above even the default 0.30
    # threshold.  With the short-key bug the score lookup returns 0.0 and the
    # candidate is dropped; with the fix it scores 0.5 (gripper weight) and
    # passes the 0.10 score_threshold used here.
    inputs = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    req = AnnotateRequest(
        video=inputs.video,
        parquet=inputs.parquet,
        task="pick red block",
        robot_adapter_name="aloha",
        robot_adapter_config_path=None,
        labels_path=None,
        runs_root=tmp_path / "runs",
        link_video=False,
        force=False,
        config=AnnotationConfig(
            boundary=BoundaryConfig(
                # Short-key form per spec §4.3 — this is what the CLI passes.
                weights=BoundaryWeights(),
                thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
                merge_window_sec=0.10,
                score_threshold=0.10,
                disabled_sources=[],
            ),
            target_phase=1,
            model_config=ModelConfig(None, None, None, None),
        ),
    )
    result = annotate_episode(req)

    import json

    boundaries = json.loads((result.run_dir / "boundaries.json").read_text())
    candidates = boundaries["candidates"]
    assert len(candidates) >= 1, (
        "Expected at least 1 boundary candidate from a clear gripper transition, "
        "but got 0. This likely means the short-key→source-name translation in "
        "pipeline.py is missing or broken."
    )


def test_annotate_episode_unknown_weight_key_raises(tmp_path: Path):
    """An unrecognised key in boundary YAML weights must raise MimicAnnoError.

    BoundaryWeights is now a typed dataclass; unknown keys are caught at the
    user-facing entry point (load_boundary_config_yaml) before construction.
    """
    from mimicanno.config import load_boundary_config_yaml
    from mimicanno.errors import MimicAnnoError

    cfg_yaml = tmp_path / "boundary.yaml"
    cfg_yaml.write_text("weights:\n  gripper: 0.5\n  TYPO_KEY: 0.25\n")

    with pytest.raises(MimicAnnoError) as exc_info:
        load_boundary_config_yaml(cfg_yaml)
    assert exc_info.value.code == "boundary_config.unknown_weight_key"
    assert "TYPO_KEY" in exc_info.value.message
