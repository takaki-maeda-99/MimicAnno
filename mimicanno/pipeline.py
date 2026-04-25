# mimicanno/pipeline.py
"""End-to-end Phase 1 pipeline orchestrator."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from mimicanno import __version__
from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter
from mimicanno.adapters.generic import GenericAdapter
from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter
from mimicanno.boundaries import (
    detect_action_norm_change,
    detect_eef_acceleration_peak,
    detect_eef_velocity_valley,
    detect_gripper_transition,
    integrated_candidates,
)
from mimicanno.bracketing import bracket_phase1_segments
from mimicanno.config import (
    RUN_HASH_FALLBACK_PREFIX_LEN,
    AnnotationConfig,
    InputBundle,
    compose_run_hash,
    compute_config_hash,
    compute_input_hash,
)
from mimicanno.errors import MimicAnnoError
from mimicanno.io_parquet import (
    ParquetLoadError,
    load_episode_parquet,
    resolve_fps,
)
from mimicanno.io_video import materialize_video, probe_video
from mimicanno.labelset import default_labels_path, load_label_set
from mimicanno.publish import PublishOutcome, PublishRequest, publish
from mimicanno.rundir import canonical_name_for, is_collision
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    TaskInfo,
)
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS, COMPAT_BLOCK
from mimicanno.signals import (
    SignalChannel,
    downsample_for_viewer,
    gaussian_smooth_1d,
    smoothing_sigma_for_fps,
)
from mimicanno.writers import (
    write_annotation_json,
    write_boundaries_json,
    write_manifest_json,
    write_signals_json,
)


@dataclass(slots=True)
class AnnotateRequest:
    video: Path
    parquet: Path
    task: str
    robot_adapter_name: str
    robot_adapter_config_path: Path | None
    labels_path: Path | None
    runs_root: Path
    link_video: bool
    force: bool
    config: AnnotationConfig


@dataclass(slots=True)
class AnnotateResult:
    run_dir: Path
    outcome: PublishOutcome


def _select_adapter(name: str, config_path: Path | None) -> RobotAdapter:
    if name == "aloha":
        return AlohaAdapter()
    if name == "koch":
        return KochAdapter()
    if name == "so100":
        return SO100Adapter()
    if name == "generic":
        if config_path is None:
            raise MimicAnnoError(
                "adapter.generic_requires_config",
                "GenericAdapter requires --robot-config <yaml>",
                {},
            )
        return GenericAdapter.from_yaml(config_path)
    raise MimicAnnoError(
        "adapter.unknown",
        f"unknown robot adapter {name!r}; expected aloha|koch|so100|generic",
        {"adapter_name": name},
    )


def annotate_episode(req: AnnotateRequest) -> AnnotateResult:
    # 1) Resolve label set.
    labels_path = req.labels_path or Path(default_labels_path("manipulation"))
    label_set = load_label_set(labels_path)

    # 2) Adapter selection + adapter-config sha for input_hash.
    adapter = _select_adapter(req.robot_adapter_name, req.robot_adapter_config_path)
    adapter_config_sha: str | None = None
    if req.robot_adapter_config_path is not None:
        from mimicanno.hashing import sha256_file
        adapter_config_sha = "sha256:" + sha256_file(req.robot_adapter_config_path)

    # 3) Probe video and load parquet.
    probe = probe_video(req.video)
    try:
        loaded = load_episode_parquet(req.parquet)
    except ParquetLoadError as e:
        raise MimicAnnoError("parquet.load_failed", str(e), {"path": str(req.parquet)}) from e

    inputs = InputBundle(
        video_sha256=probe.sha256,
        parquet_sha256=loaded.sha256,
        task_text=req.task,
        robot_adapter_name=req.robot_adapter_name,
        robot_adapter_config_sha256=adapter_config_sha,
        labels_yaml_sha256=label_set.sha256,
    )
    config_hash = compute_config_hash(req.config)
    input_hash = compute_input_hash(inputs)
    run_hash = compose_run_hash(config_hash, input_hash)

    # 4) FPS resolution: prefer ffprobe value when timestamps disagree.
    timestamps = np.asarray(loaded.table.column("timestamp").to_pylist(), dtype=np.float64)
    try:
        fps_from_ts = resolve_fps(timestamps)
    except ParquetLoadError as e:
        raise MimicAnnoError("fps.unresolvable", str(e), {})
    fps = float(probe.fps) if probe.fps > 0 else fps_from_ts
    duration_sec = float(probe.duration_sec)
    episode_id = req.parquet.stem  # Phase 1: derive from filename.

    # 5) Extract signals through the adapter.
    gripper = adapter.gripper_signal(loaded.table)
    eef_pose = adapter.eef_pose(loaded.table)
    eef_vel = adapter.eef_velocity(loaded.table)
    has_eef = eef_vel is not None

    action_norm: np.ndarray | None
    if "action" in loaded.table.column_names:
        action = np.asarray(loaded.table.column("action").to_pylist(), dtype=np.float64)
        action_norm = np.linalg.norm(action, axis=1)
        if (action_norm == 0).mean() >= 0.95:
            action_norm = None
    else:
        action_norm = None

    # 6) Smooth.
    sigma = smoothing_sigma_for_fps(fps)
    gripper_s = gaussian_smooth_1d(gripper, sigma=sigma)
    vel_s = gaussian_smooth_1d(eef_vel, sigma=sigma) if has_eef else None
    # |a| in m/s²: |Δv| / dt where dt = 1/fps. Without the *fps, the values are
    # off by ~30× at 30 fps and the peak_threshold (set in m/s²) effectively
    # becomes 30× too high — the detector would never fire on real data.
    accel_s = (
        gaussian_smooth_1d(
            np.abs(np.diff(eef_vel, prepend=eef_vel[0])) * fps,
            sigma=sigma,
        )
        if has_eef else None
    )
    action_s = (
        gaussian_smooth_1d(action_norm, sigma=sigma) if action_norm is not None else None
    )

    # 7) Detect per source.
    bcfg = req.config.boundary
    events = list(detect_gripper_transition(
        gripper_s, fps=fps, delta_threshold=bcfg.thresholds.get("gripper_delta", 0.30),
    ))
    if vel_s is not None:
        events.extend(detect_eef_velocity_valley(
            vel_s, fps=fps,
            valley_threshold=bcfg.thresholds.get("velocity_valley", 0.05),
            min_valley_sec=0.10,
        ))
    if accel_s is not None:
        events.extend(detect_eef_acceleration_peak(
            accel_s, fps=fps, peak_threshold=1.0,
        ))
    if action_s is not None:
        events.extend(detect_action_norm_change(
            action_s, fps=fps, change_threshold=0.2, window_sec=0.5,
        ))

    candidates = integrated_candidates(
        events, fps=fps, merge_window_sec=bcfg.merge_window_sec,
        weights=bcfg.weights, score_threshold=bcfg.score_threshold,
    )

    # 8) Determine disabled sources from what was actually run.
    disabled: list[str] = []
    if not has_eef:
        disabled.extend(["eef_velocity_valley", "eef_acceleration_peak"])
    if action_s is None:
        disabled.append("action_norm_change")

    # 9) Bracket into Phase 1 skeleton segments.
    segments = bracket_phase1_segments(
        episode_id=episode_id, candidates=candidates,
        fps=fps, duration_sec=duration_sec,
    )

    # 10) Build pipeline_params for manifest (records what was actually used).
    pipeline_params = {
        "boundary": {
            "weights": dict(bcfg.weights),
            "thresholds": dict(bcfg.thresholds),
            "merge_window_sec": bcfg.merge_window_sec,
            "score_threshold": bcfg.score_threshold,
            "disabled_sources": disabled,
        },
    }

    # 11) Build per-channel signals downsampled for viewer.
    signal_channels: list[SignalChannel] = [
        downsample_for_viewer(
            SignalChannel(name="gripper", unit="normalized",
                          values=gripper_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ),
    ]
    if vel_s is not None:
        signal_channels.append(downsample_for_viewer(
            SignalChannel(name="eef_velocity", unit="m/s",
                          values=vel_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ))

    # 12) Build dataclass payloads.
    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    pipeline_status = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=None,
        degrade_reason=None,
    )
    task_info = TaskInfo(text=req.task, version=None)
    generator = GeneratorInfo(
        name="mimicanno", cli_version=__version__, pipeline_phase=1,
    )

    manifest = Manifest(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["manifest"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions={"sam3": None, "vlm": None},
        pipeline_params=pipeline_params,
        inputs={
            "video": InputRef(path=str(req.video), sha256=probe.sha256),
            "parquet": InputRef(path=str(req.parquet), sha256=loaded.sha256),
        },
        time_base="video_pts_seconds",
        fps=fps,
        duration_sec=duration_sec,
        pipeline_status=pipeline_status,
        compat=COMPAT_BLOCK,
        artifacts=[
            Artifact("video", "video.mp4", "video/mp4"),
            Artifact("annotation", "annotation.json", "application/json"),
            Artifact("boundaries", "boundaries.json", "application/json"),
            Artifact("signals", "signals.json", "application/json"),
        ],
    )

    annotation = AnnotationResult(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["annotation"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions={"sam3": None, "vlm": None},
        pipeline_phase=1,
        pipeline_status=pipeline_status,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )

    # 13) Publish.
    def _write_artifacts(tmp_dir: Path) -> None:
        # Materialize video (copy or symlink) FIRST so the writer.json removal
        # at finalization does not have to compete with a half-copied mp4.
        materialize_video(req.video, tmp_dir, link=req.link_video)
        write_signals_json(
            tmp_dir / "signals.json",
            episode_id=episode_id,
            duration_sec=duration_sec,
            channels=signal_channels,
        )
        write_boundaries_json(
            tmp_dir / "boundaries.json",
            episode_id=episode_id, candidates=candidates,
        )
        write_annotation_json(tmp_dir / "annotation.json", annotation)
        write_manifest_json(tmp_dir / "manifest.json", manifest)

    publish_req = PublishRequest(
        runs_root=req.runs_root,
        episode_id=episode_id,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        task_text=req.task,
        pipeline_phase=1,
        generated_at=generated_at,
        force=req.force,
    )
    outcome = publish(publish_req, write_artifacts=_write_artifacts)

    # Resolve final dir from canonical_name (re-applies collision extension if needed).
    name = canonical_name_for(episode_id, run_hash=run_hash)
    if is_collision(req.runs_root, canonical_name=name, expected_run_hash=run_hash):
        name = canonical_name_for(
            episode_id, run_hash=run_hash, length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )
    return AnnotateResult(run_dir=req.runs_root / name, outcome=outcome)
