"""Integration tests for the ``--boundary-config`` CLI flag.

Covers two paths:
  1. A YAML override actually reaches ``BoundaryConfig`` and is recorded in the
     resulting ``manifest.json``'s ``pipeline_params.boundary``.
  2. CLI per-flag overrides (``--score-threshold``, ``--merge-window-sec``)
     win over the YAML, so a user can tweak one knob without editing the file.
  3. A malformed YAML produces a structured error JSON on stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_cli(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_boundary_config_yaml_drives_thresholds(tmp_path: Path) -> None:
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    runs_root = tmp_path / "runs"

    cfg_yaml = tmp_path / "boundary.yaml"
    cfg_yaml.write_text(
        "thresholds:\n"
        "  gripper_delta: 0.15\n"
        "  velocity_valley: 0.05\n"
        "merge_window_sec: 0.20\n"
        "score_threshold: 0.20\n"
    )

    result = _run_cli(
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
        "--boundary-config", str(cfg_yaml),
    )
    assert result.returncode == 0, result.stderr

    run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    boundary = manifest["pipeline_params"]["boundary"]
    assert boundary["thresholds"]["gripper_delta"] == 0.15
    assert boundary["merge_window_sec"] == 0.20
    assert boundary["score_threshold"] == 0.20


def test_cli_flag_overrides_yaml_value(tmp_path: Path) -> None:
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    runs_root = tmp_path / "runs"

    cfg_yaml = tmp_path / "boundary.yaml"
    cfg_yaml.write_text("score_threshold: 0.40\nmerge_window_sec: 0.30\n")

    result = _run_cli(
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
        "--boundary-config", str(cfg_yaml),
        "--score-threshold", "0.18",  # CLI flag must beat YAML's 0.40
    )
    assert result.returncode == 0, result.stderr

    run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    boundary = manifest["pipeline_params"]["boundary"]
    assert boundary["score_threshold"] == 0.18  # from CLI
    assert boundary["merge_window_sec"] == 0.30  # from YAML (no CLI override)


def test_invalid_boundary_config_emits_structured_error(tmp_path: Path) -> None:
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data")
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("thresholds:\n  not_a_real_threshold: 0.1\n")

    result = _run_cli(
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick",
        "--robot", "aloha",
        "--runs-root", str(tmp_path / "runs"),
        "--boundary-config", str(bad_yaml),
    )
    assert result.returncode == 2, result.stderr
    err = json.loads(result.stderr.strip().splitlines()[-1])
    assert err["error_code"] == "boundary_config.unknown_threshold_key"
