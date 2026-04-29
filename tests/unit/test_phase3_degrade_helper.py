# tests/unit/test_phase3_degrade_helper.py
"""Unit tests for _degrade_to_phase3_objectless + PipelineStatus.object_state_segment_coverage.

8 scenarios (spec §7.2 + plan Task 20 Step 20.1):
  1. Boundary weights are Phase 3 weights (not Phase 1/Phase 2).
  2. disabled_sources includes both Phase 3 object sources.
  3. tracks.json NOT written to the run directory.
  4. manifest.artifacts[] excludes kind="tracks".
  5. annotation.notes PII rule: exact canonical string; no forbidden substrings.
  6. underlying_log goes to stderr (NOT in notes).
  7. pipeline_status fields: object_state_available=False, coverage=0.0, etc.
  8. Phase 1/2 manifest omits object_state_segment_coverage in to_dict().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    BoundaryWeights,
    ModelConfig,
    TrackingConfig,
    VLMConfig,
)
from mimicanno.pipeline import AnnotateRequest, _degrade_to_phase3_objectless
from mimicanno.schema import PipelineStatus
from mimicanno.vlm_labeler import FixtureVLMLabeler
from tests.fixtures.synthesize import synthesize_aloha_episode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _make_config(*, has_eef: bool = True) -> AnnotationConfig:
    vlm = VLMConfig(
        model_id="fixture",
        resolved_checkpoint="abc",
        fixture_path=FIXT / "ok_first_try.json",
    )
    tracking = TrackingConfig(
        sam3_checkpoint="/tmp/sam3.pt",
    )
    boundary = BoundaryConfig(
        weights=BoundaryWeights.phase3_defaults(),
        thresholds={"gripper_delta": 0.30, "velocity_valley": 0.05},
        merge_window_sec=0.10,
        score_threshold=0.30,
        disabled_sources=[],
    )
    model_config = ModelConfig(
        vlm_model="fixture",
        vlm_checkpoint="abc",
        sam3_model=None,
        sam3_checkpoint=None,
    )
    return AnnotationConfig(
        boundary=boundary,
        target_phase=3,
        model_config=model_config,
        vlm=vlm,
        tracking=tracking,
    )


def _make_request(episode: Any, runs_root: Path, config: AnnotationConfig | None = None) -> AnnotateRequest:
    if config is None:
        config = _make_config()
    return AnnotateRequest(
        video=episode.video,
        parquet=episode.parquet,
        task="pick the red block",
        robot_adapter_name="aloha",
        robot_adapter_config_path=None,
        labels_path=None,
        runs_root=runs_root,
        link_video=False,
        force=True,
        config=config,
    )


def _call_degrade(
    episode: Any,
    runs_root: Path,
    *,
    degrade_reason: str = "sam3_init_failed",
    underlying_log: str | None = None,
    has_eef: bool = True,
    n_frames: int = 120,
    fps: float = 30.0,
) -> Any:
    """Helper: call _degrade_to_phase3_objectless with synthetic signals."""
    from mimicanno.adapters.aloha import AlohaAdapter
    from mimicanno.io_parquet import load_episode_parquet
    from mimicanno.io_video import probe_video
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.signals import gaussian_smooth_1d, smoothing_sigma_for_fps

    config = _make_config(has_eef=has_eef)
    req = _make_request(episode, runs_root, config)

    probe = probe_video(req.video)
    loaded = load_episode_parquet(req.parquet)
    labels_path = Path(default_labels_path("manipulation"))
    label_set = load_label_set(labels_path)
    adapter = AlohaAdapter()

    timestamps = np.asarray(loaded.table.column("timestamp").to_pylist(), dtype=np.float64)
    actual_n_frames = len(timestamps)

    gripper = adapter.gripper_signal(loaded.table)
    eef_vel = adapter.eef_velocity(loaded.table)
    sigma = smoothing_sigma_for_fps(fps)
    gripper_s = gaussian_smooth_1d(gripper, sigma=sigma)
    if eef_vel is not None and has_eef:
        vel_s: np.ndarray | None = gaussian_smooth_1d(eef_vel, sigma=sigma)
        accel_s: np.ndarray | None = gaussian_smooth_1d(
            np.abs(np.diff(eef_vel, prepend=eef_vel[0])) * fps, sigma=sigma
        )
    else:
        vel_s = None
        accel_s = None

    disabled_phase1: list[str] = []
    if vel_s is None:
        disabled_phase1.extend(["eef_velocity_valley", "eef_acceleration_peak"])

    from mimicanno.config import (
        InputBundle,
        compose_run_hash,
        compute_config_hash,
        compute_input_hash,
    )

    config_hash = compute_config_hash(config)
    inputs = InputBundle(
        video_sha256=probe.sha256,
        parquet_sha256=loaded.sha256,
        task_text=req.task,
        robot_adapter_name=req.robot_adapter_name,
        robot_adapter_config_sha256=None,
        labels_yaml_sha256=label_set.sha256,
    )
    input_hash = compute_input_hash(inputs)
    run_hash = compose_run_hash(config_hash, input_hash)

    # Use FixtureVLMLabeler as the vlm argument — _degrade_to_phase3_objectless
    # passes it through to apply_phase2_labeling via _labeler_factory override,
    # so no real GPU is needed.
    vlm = FixtureVLMLabeler(FIXT / "ok_first_try.json")

    result = _degrade_to_phase3_objectless(
        req, config, vlm,
        fps=fps,
        duration_sec=float(probe.duration_sec),
        n_frames=actual_n_frames,
        episode_id=req.parquet.stem,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        label_set=label_set,
        probe=probe,
        loaded=loaded,
        adapter=adapter,
        adapter_config_sha=None,
        timestamps=timestamps,
        gripper_s=gripper_s,
        vel_s=vel_s,
        accel_s=accel_s,
        action_s=None,
        has_eef=has_eef,
        disabled_sources_phase1=disabled_phase1,
        degrade_reason=degrade_reason,
        underlying_log=underlying_log,
    )
    return result


# ---------------------------------------------------------------------------
# Test 1: Boundary weights are Phase 3 weights
# ---------------------------------------------------------------------------


def test_boundary_weights_are_phase3(tmp_path: Path) -> None:
    """Boundary weights in pipeline_params must be Phase 3 values (spec §7.2)."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = _call_degrade(episode, tmp_path / "runs")

    run_dir = result.run_dir
    import json
    manifest = json.loads((run_dir / "manifest.json").read_text())
    weights = manifest["pipeline_params"]["boundary"]["weights"]

    expected = {
        "gripper": 0.45,
        "velocity": 0.15,
        "acceleration": 0.03,
        "action": 0.02,
        "gripper_object_distance_threshold_crossing": 0.25,
        "object_motion_start_stop": 0.10,
    }
    assert weights == expected, f"Got weights={weights}, expected {expected}"


# ---------------------------------------------------------------------------
# Test 2: disabled_sources includes both Phase 3 object sources
# ---------------------------------------------------------------------------


def test_disabled_sources_includes_phase3_object_sources(tmp_path: Path) -> None:
    """final_disabled_sources must always include both Phase 3 object sources on degrade."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = _call_degrade(episode, tmp_path / "runs")

    import json
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    disabled = manifest["pipeline_params"]["boundary"]["disabled_sources"]

    assert "gripper_object_distance_threshold_crossing" in disabled
    assert "object_motion_start_stop" in disabled


# ---------------------------------------------------------------------------
# Test 3: tracks.json NOT written
# ---------------------------------------------------------------------------


def test_tracks_json_not_written(tmp_path: Path) -> None:
    """tracks.json must NOT be written to the run directory on degrade (spec §3.4)."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = _call_degrade(episode, tmp_path / "runs")

    tracks_path = result.run_dir / "tracks.json"
    assert not tracks_path.exists(), (
        f"tracks.json should not exist on degrade path but found: {tracks_path}"
    )


# ---------------------------------------------------------------------------
# Test 4: manifest.artifacts[] excludes kind="tracks"
# ---------------------------------------------------------------------------


def test_manifest_artifacts_excludes_tracks(tmp_path: Path) -> None:
    """manifest.artifacts must NOT include role='tracks' on degrade (spec §3.4)."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = _call_degrade(episode, tmp_path / "runs")

    import json
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    roles = [a["role"] for a in manifest["artifacts"]]
    assert "tracks" not in roles, f"artifacts must not include 'tracks'; got roles={roles}"
    # The 4 expected roles are present
    for expected in ("video", "annotation", "boundaries", "signals"):
        assert expected in roles


# ---------------------------------------------------------------------------
# Test 5: annotation.notes PII rule
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = ["Traceback", "at 0x", "/path/to/", "repr(", "RuntimeError", "Exception"]


@pytest.mark.parametrize("forbidden", _FORBIDDEN_SUBSTRINGS)
def test_annotation_notes_excludes_pii(forbidden: str, tmp_path: Path) -> None:
    """notes must not contain PII/exception data (spec §7.2/§8 channel rule)."""
    episode = synthesize_aloha_episode(tmp_path / forbidden.replace("/", "_"))
    result = _call_degrade(
        episode,
        tmp_path / "runs" / forbidden.replace("/", "_"),
        underlying_log="RuntimeError: /path/to/file at 0xDEAD Traceback repr(e) Exception",
    )
    import json
    annotation = json.loads((result.run_dir / "annotation.json").read_text())
    notes = annotation.get("notes", "") or ""
    assert forbidden not in notes, (
        f"notes must not contain {forbidden!r}; got notes={notes!r}"
    )


def test_annotation_notes_exact_canonical_message(tmp_path: Path) -> None:
    """notes must be exactly the canonical degrade message."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = _call_degrade(
        episode, tmp_path / "runs", degrade_reason="sam3_init_failed"
    )
    import json
    annotation = json.loads((result.run_dir / "annotation.json").read_text())
    expected = "phase3: degraded to object-state-unavailable path (degrade_reason=sam3_init_failed)."
    assert annotation["notes"] == expected


# ---------------------------------------------------------------------------
# Test 6: underlying_log goes to stderr, NOT notes
# ---------------------------------------------------------------------------


def test_underlying_log_goes_to_stderr_not_notes(tmp_path: Path, capsys: Any) -> None:
    """underlying_log must appear on stderr WARN line; notes must not contain it."""
    episode = synthesize_aloha_episode(tmp_path / "data")
    secret = "SAM3InitFailed('CUDA OOM')"
    result = _call_degrade(
        episode, tmp_path / "runs",
        degrade_reason="sam3_init_failed",
        underlying_log=secret,
    )
    captured = capsys.readouterr()
    # underlying_log must appear on stderr
    assert secret in captured.err, (
        f"underlying_log should be in stderr; got stderr={captured.err!r}"
    )

    import json
    annotation = json.loads((result.run_dir / "annotation.json").read_text())
    notes = annotation.get("notes", "") or ""
    assert secret not in notes, (
        f"underlying_log must NOT be in notes; got notes={notes!r}"
    )


# ---------------------------------------------------------------------------
# Test 7: pipeline_status fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("degrade_reason", [
    "gemma_no_object_prompts",
    "sam3_no_initial_detection",
    "sam3_init_failed",
])
def test_pipeline_status_fields(degrade_reason: str, tmp_path: Path) -> None:
    """pipeline_status must have correct fields on degrade (spec §7.2)."""
    episode = synthesize_aloha_episode(tmp_path / degrade_reason)
    result = _call_degrade(
        episode,
        tmp_path / "runs" / degrade_reason,
        degrade_reason=degrade_reason,
    )
    import json
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    ps = manifest["pipeline_status"]

    assert ps["object_state_available"] is False
    assert ps["object_state_segment_coverage"] == 0.0
    assert ps["degraded_from_phase"] == 3
    assert ps["degrade_reason"] == degrade_reason


# ---------------------------------------------------------------------------
# Test 8: Phase 1/2 manifests omit object_state_segment_coverage
# ---------------------------------------------------------------------------


def test_phase12_pipeline_status_omits_coverage() -> None:
    """PipelineStatus with object_state_segment_coverage=None must omit the key in to_dict()."""
    ps = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=None,
        degrade_reason=None,
        object_state_segment_coverage=None,
    )
    d = ps.to_dict()
    assert "object_state_segment_coverage" not in d, (
        f"Phase 1/2 manifest must omit object_state_segment_coverage; got keys={list(d)}"
    )


def test_phase3_pipeline_status_includes_coverage() -> None:
    """PipelineStatus with object_state_segment_coverage set must include the key in to_dict()."""
    ps = PipelineStatus(
        object_state_available=True,
        degraded_from_phase=None,
        degrade_reason=None,
        object_state_segment_coverage=0.75,
    )
    d = ps.to_dict()
    assert "object_state_segment_coverage" in d
    assert d["object_state_segment_coverage"] == 0.75


def test_phase3_degrade_pipeline_status_coverage_is_zero() -> None:
    """PipelineStatus on degrade path must have object_state_segment_coverage=0.0."""
    ps = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=3,
        degrade_reason="sam3_init_failed",
        object_state_segment_coverage=0.0,
    )
    d = ps.to_dict()
    assert d["object_state_segment_coverage"] == 0.0
