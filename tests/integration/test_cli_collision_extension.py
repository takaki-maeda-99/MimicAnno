# tests/integration/test_cli_collision_extension.py
"""§15.11: forcing a run_hash[:12] prefix collision triggers [:16] extension
without overwriting the existing run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_collision_triggers_16_hex_extension(tmp_path: Path):
    from mimicanno.config import (
        AnnotationConfig,
        BoundaryConfig,
        InputBundle,
        ModelConfig,
        compose_run_hash,
        compute_config_hash,
        compute_input_hash,
    )
    from mimicanno.io_parquet import load_episode_parquet
    from mimicanno.io_video import probe_video
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.rundir import canonical_name_for
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Compute the run_hash the CLI will derive.
    probe = probe_video(episode.video)
    parquet = load_episode_parquet(episode.parquet)
    labels = load_label_set(Path(default_labels_path("manipulation")))
    cfg = AnnotationConfig(
        boundary=BoundaryConfig(
            weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=0.10,
            score_threshold=0.30,
            disabled_sources=[],
        ),
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
    )
    inputs = InputBundle(
        video_sha256=probe.sha256,
        parquet_sha256=parquet.sha256,
        task_text="pick red block",
        robot_adapter_name="aloha",
        robot_adapter_config_sha256=None,
        labels_yaml_sha256=labels.sha256,
    )
    expected_run_hash = compose_run_hash(
        compute_config_hash(cfg),
        compute_input_hash(inputs),
    )
    name = canonical_name_for(episode.episode_id, run_hash=expected_run_hash)

    # Plant a colliding (but different-content) run dir.
    plant = runs_root / name
    plant.mkdir()
    (plant / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "run_hash": "sha256:" + "f" * 64,  # different from expected
            }
        )
    )

    # Now run the CLI; it should write to <episode>__<hash[:16]>/ instead.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mimicanno.cli",
            "annotate",
            "--video",
            str(episode.video),
            "--parquet",
            str(episode.parquet),
            "--task",
            "pick red block",
            "--robot",
            "aloha",
            "--runs-root",
            str(runs_root),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    # Both directories now exist; the planted one is untouched.
    expected_extended = runs_root / canonical_name_for(
        episode.episode_id,
        run_hash=expected_run_hash,
        length=16,
    )
    assert plant.exists()
    assert expected_extended.exists()
    assert json.loads((plant / "manifest.json").read_text())["run_hash"] == "sha256:" + "f" * 64
