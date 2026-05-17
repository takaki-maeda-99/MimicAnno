# mimicanno/pipeline.py
"""End-to-end Phase 1 + Phase 2 pipeline orchestrator."""

from __future__ import annotations

import datetime as dt
import json as _json
import logging
import sys as _sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from mimicanno import __version__
from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter
from mimicanno.adapters.generic import GenericAdapter
from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter
from mimicanno.boundaries import (
    Phase3BoundaryDetector,
    detect_action_norm_change,
    detect_eef_acceleration_peak,
    detect_eef_velocity_valley,
    detect_gripper_transition,
    detect_gripper_zero_crossing,
    integrated_candidates,
)
from mimicanno.bracketing import bracket_phase1_segments
from mimicanno.config import (
    RUN_HASH_FALLBACK_PREFIX_LEN,
    AnnotationConfig,
    InputBundle,
    TrackingConfig,
    VLMConfig,
    compose_run_hash,
    compute_config_hash,
    compute_input_hash,
)
from mimicanno.errors import MimicAnnoError, SAM3InitFailed
from mimicanno.io import write_tracks_json
from mimicanno.io_parquet import (
    ParquetLoadError,
    load_episode_parquet,
    resolve_fps,
)
from mimicanno.io_video import VideoProbe, materialize_video, probe_video
from mimicanno.labelset import default_labels_path, load_label_set
from mimicanno.object_tracker import (
    GroundingAttempt,
    SAM3Runtime,
    ground_initial_detections,
    ground_initial_detections_with_retry,
)
from mimicanno.object_tracker.planner import (
    EntityPlan,
    LocalGemmaTrackingPlanner,
)
from mimicanno.object_tracker.propagator import Propagator
from mimicanno.object_tracker.signals import compute_object_signals
from mimicanno.publish import PublishOutcome, PublishRequest, publish
from mimicanno.rundir import canonical_name_for, is_collision
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    SmoothingSummary,
    SubtaskSegment,
    TaskInfo,
    TracksFile,
    TracksGap,
    TracksSample,
    TracksStats,
    TracksTrack,
    TracksTrackingPlan,
)
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS, COMPAT_BLOCK
from mimicanno.signals import (
    SignalChannel,
    downsample_for_viewer,
    gaussian_smooth_1d,
    smoothing_sigma_for_fps,
)
from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelerFactory,
    LocalGemmaVLMLabeler,
    RunOutcome,
    apply_phase3_labeling,
    label_run,
)
from mimicanno.writers import (
    write_annotation_json,
    write_boundaries_json,
    write_manifest_json,
    write_signals_json,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 2 helpers
# ---------------------------------------------------------------------------

def _make_labeler_factory(vlm_config: VLMConfig) -> LabelerFactory:
    """Choose the right labeler implementation based on VLMConfig.

    `model_id == "fixture"` is set by pre-flight (§2.5 Case C); the original
    fixture file path lives on `vlm_config.fixture_path` (Task 1 — runtime-only,
    excluded from to_dict / config_hash). For real adapters we instantiate
    `LocalGemmaVLMLabeler` against the pre-flight-resolved revision."""
    if vlm_config.model_id == "fixture":
        if vlm_config.fixture_path is None:
            raise ValueError(
                "VLMConfig.model_id == 'fixture' but fixture_path is None — "
                "pre-flight (§2.5 Case C) must populate fixture_path."
            )
        path = vlm_config.fixture_path
        return lambda c: FixtureVLMLabeler(path)
    return lambda c: LocalGemmaVLMLabeler(c)


def _emit_vlm_log(event: dict[str, Any]) -> None:
    enriched = {
        "ts": dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z"),
        **event,
    }
    _sys.stderr.write(_json.dumps(enriched, ensure_ascii=False) + "\n")
    _sys.stderr.flush()


def apply_phase2_labeling(
    *,
    segments: list[SubtaskSegment],
    extractor: Any,
    gripper: np.ndarray,
    eef_velocity: np.ndarray | None,
    episode_meta: dict[str, Any],
    vlm_config: VLMConfig,
    labeler_factory_override: LabelerFactory | None = None,
) -> tuple[list[SubtaskSegment], RunOutcome, str | None]:
    """Phase 2 wrapper. Returns (labeled_segments, outcome, notes_aggregate)."""
    factory = labeler_factory_override or _make_labeler_factory(vlm_config)
    labeled, attempts, outcome = label_run(
        segments=segments, extractor=extractor,
        gripper=gripper, eef_velocity=eef_velocity,
        episode_meta=episode_meta, config=vlm_config, labeler_factory=factory,
    )
    for a in attempts:
        for i, reason in enumerate(a.reject_reasons, start=1):
            _emit_vlm_log({
                "event": "vlm_attempt", "segment_id": a.segment_id,
                "attempt": i, "status": "rejected", "reject_reason": reason,
            })
        for i, runtime_reason in enumerate(a.runtime_errors, start=1):
            _emit_vlm_log({
                "event": "vlm_runtime_fault", "segment_id": a.segment_id,
                "attempt": i, "reason": runtime_reason,
            })
        if a.final_status == "ok":
            _emit_vlm_log({
                "event": "vlm_attempt", "segment_id": a.segment_id,
                "attempt": a.attempt_count, "status": "ok",
                "vlm_confidence": a.response["vlm_confidence"],
            })
        else:
            _emit_vlm_log({
                "event": "vlm_segment_fallback", "segment_id": a.segment_id,
                "attempts": a.attempt_count,
                "reject_reasons": list(a.reject_reasons),
            })

    if outcome.kind == "degraded":
        _emit_vlm_log({
            "event": "vlm_run_degrade",
            "degrade_reason": outcome.degrade_reason,
            "underlying_error": outcome.underlying_error,
        })
        notes = (
            f"vlm_labeler: degraded to Phase 1 output "
            f"(degrade_reason={outcome.degrade_reason}); 0/{len(segments)} segments labeled."
        )
        return labeled, outcome, notes

    n_ok = sum(1 for a in attempts if a.final_status == "ok")
    n_fallback = sum(1 for a in attempts if a.final_status == "unknown_fallback")
    n_retried = sum(1 for a in attempts if a.attempt_count > 1)
    notes = (
        f"vlm_labeler: {n_ok}/{len(segments)} segments labeled; "
        f"{n_retried} needed retry; {n_fallback} fell back to unknown."
    )
    return labeled, outcome, notes


# ---------------------------------------------------------------------------
# Maps BoundaryConfig.weights short keys (spec §4.3 manifest example)
# to the detector source names emitted by RawEvent.source in boundaries.py.
_WEIGHT_KEY_TO_SOURCE: dict[str, str] = {
    "gripper": "gripper_transition",
    "velocity": "eef_velocity_valley",
    "acceleration": "eef_acceleration_peak",
    "action": "action_norm_change",
    # Phase 3 long keys — identity mapping (already the detector source name).
    "gripper_object_distance_threshold_crossing": "gripper_object_distance_threshold_crossing",
    "object_motion_start_stop": "object_motion_start_stop",
}


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
    # バッチ実行時に事前ロード済みのVLMを差し込めるようにする。
    # None のときは従来通り pipeline 内部で LocalGemmaVLMLabeler を新規ロードする。
    preloaded_vlm: object | None = None
    # バッチ実行時に事前ロード済みのSAM3 Runtime を差し込めるようにする。
    # None のときは従来通り annotate_episode_phase3 内部で SAM3Runtime.load()
    # を呼び、関数末尾で close() する。preloaded を渡したときは close せず
    # _close_all_sessions() のみ呼び、ライフサイクルは呼び出し元の責務。
    preloaded_sam3_runtime: object | None = None


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


# ---------------------------------------------------------------------------
# Phase 3 helpers
# ---------------------------------------------------------------------------

def _extract_frame_at(
    video_path: Path, n_frames: int, frame_index: int,
) -> np.ndarray:
    """Extract a specific video frame as HxWx3 RGB uint8.

    For frame_index == 0 only, falls back to ``int(0.05 * n_frames)`` if
    the read fails (preserving the pre-2026-05-17 frame-0 I/O fallback).
    For frame_index > 0, a read failure raises ``OSError`` so the retry
    helper (``ground_initial_detections_with_retry``) can mark the
    attempt as skipped and continue.
    """
    import imageio_ffmpeg as _iio  # type: ignore[import-untyped]

    def _read_frame(target_index: int) -> np.ndarray:
        reader = _iio.read_frames(str(video_path))
        meta = next(reader)
        w, h = meta["size"]
        for i, frame_bytes in enumerate(reader):
            if i == target_index:
                return np.frombuffer(frame_bytes, dtype=np.uint8).reshape(h, w, 3)
        raise OSError(f"no frame at index {target_index}")

    try:
        return _read_frame(frame_index)
    except Exception as exc:
        if frame_index == 0:
            # Preserve the legacy 5% fallback for frame 0 only.
            target = int(0.05 * n_frames)
            try:
                return _read_frame(target)
            except Exception as e2:
                raise MimicAnnoError(
                    "video.initial_frame_failed",
                    f"failed to read frame 0 + 5% fallback: {e2!r}",
                    {"video_path": str(video_path)},
                ) from e2
        # For retry frames: raise OSError so the caller skips this attempt.
        raise OSError(
            f"failed to read frame {frame_index} of {video_path}: {exc!r}"
        ) from exc


# Wire pipeline.py's _extract_frame_at into the object_tracker module so
# ground_initial_detections_with_retry can call it via monkey-patchable
# injection. (Avoids a circular import: propagator.py mustn't import
# pipeline.py directly.)
import mimicanno.object_tracker.propagator as _propagator_mod
_propagator_mod._extract_frame_at = _extract_frame_at


def _count_missing_mask_frames(
    mask_cache: "MaskCache | None",
    segment_keyframes: list[int],
) -> int:
    """Count segment keyframes whose mask is missing from the cache.

    Returns 0 when mask_cache is None (overlay not requested) or when all
    segment keyframes have an entry in mask_cache.by_frame.
    """
    if mask_cache is None or not segment_keyframes:
        return 0
    return sum(1 for k in segment_keyframes if k not in mask_cache.by_frame)


def _compute_image_aspect_ratio(probe: VideoProbe, tracking_config: TrackingConfig) -> float:
    """Image aspect ratio (width/height); falls back to tracking_config default
    when probe height is 0 or width is 0."""
    if probe.height <= 0 or probe.width <= 0:
        return tracking_config.image_aspect_ratio_default
    return float(probe.width) / float(probe.height)


def _degrade_to_phase3_objectless(
    req: AnnotateRequest,
    config: AnnotationConfig,
    vlm: Any,  # LocalGemmaVLMLabeler in prod; FixtureVLMLabeler in tests
    *,
    fps: float,
    duration_sec: float,
    n_frames: int,
    episode_id: str,
    config_hash: str,
    input_hash: str,
    run_hash: str,
    label_set: Any,
    probe: VideoProbe,
    loaded: Any,
    adapter: RobotAdapter,
    adapter_config_sha: str | None,
    timestamps: np.ndarray,
    gripper_s: np.ndarray,
    vel_s: np.ndarray | None,
    accel_s: np.ndarray | None,
    action_s: np.ndarray | None,
    has_eef: bool,
    disabled_sources_phase1: list[str],
    degrade_reason: Literal[
        "gemma_no_object_prompts", "sam3_no_initial_detection", "sam3_init_failed",
    ],
    underlying_log: str | None = None,
    grounding_attempts: list[GroundingAttempt] | None = None,  # NEW
    adopted_frame_index: int | None = None,  # NEW (degrade → always None)
) -> AnnotateResult:
    """Phase 3 whole-run degrade — produces a Phase 3 objectless run (spec §7.2).

    Uses Phase3BoundaryDetector with Phase 3 weights + empty object_signals;
    labels via apply_phase2_labeling (object_state_summary=None); does NOT
    write tracks.json; sets pipeline_status.object_state_available=False.
    """
    from mimicanno.object_tracker.signals import ObjectSignals

    # 1) Emit underlying_log to stderr WARN (NEVER to notes — PII rule §7.2/§8).
    if underlying_log is not None:
        _sys.stderr.write(
            f"WARN: phase3 degrade {degrade_reason}: {underlying_log}\n"
        )
        _sys.stderr.flush()

    # 2) Phase 1 disabled sources + Phase 3 always-disabled object sources.
    disabled_sources: list[str] = [
        *disabled_sources_phase1,
        "gripper_object_distance_threshold_crossing",
        "object_motion_start_stop",
    ]

    # 3) Build empty ObjectSignals (NaN-filled arrays, no tracks).
    empty_signals = ObjectSignals(
        gripper_object_distance={},
        object_speed={},
        object_center={},
        primary_object_track_id=None,
        primary_target_track_id=None,
        gripper_tool_track_id=None,
    )

    # 4) Phase3BoundaryDetector with Phase 3 weights.
    bcfg = config.boundary
    tracking_cfg = config.tracking
    assert tracking_cfg is not None  # guaranteed by annotate_episode_phase3 pre-check

    detector = Phase3BoundaryDetector(
        fps=fps,
        weights=bcfg.weights,
        score_threshold=bcfg.score_threshold,
        merge_window_sec=bcfg.merge_window_sec,
        disabled_sources=disabled_sources,
        tracking_config=tracking_cfg,
        zero_crossing=bcfg.zero_crossing,
    )
    eef_vel_for_detector = vel_s if vel_s is not None else np.zeros(n_frames, dtype=np.float64)
    accel_for_detector = accel_s if accel_s is not None else np.zeros(n_frames, dtype=np.float64)
    action_for_detector = action_s if action_s is not None else np.zeros(n_frames, dtype=np.float64)
    candidates, final_disabled = detector.detect(
        gripper=gripper_s,
        eef_vel=eef_vel_for_detector,
        eef_accel=accel_for_detector,
        action_norm=action_for_detector,
        object_signals=empty_signals,
        tracks=[],
    )

    # 5) Bracket into segments.
    segments = bracket_phase1_segments(
        episode_id=episode_id,
        candidates=candidates,
        fps=fps,
        duration_sec=duration_sec,
    )

    # 6) Label via apply_phase2_labeling (object_state_summary=None → Phase 2 prompt).
    from mimicanno.clip_features import ClipFeatureExtractor

    vlm_cfg = config.vlm
    assert vlm_cfg is not None  # guaranteed by annotate_episode_phase3 pre-check

    extractor = ClipFeatureExtractor(
        video_path=req.video,
        fps=fps,
        clip_features_config=vlm_cfg.clip_features,
        image_size_px=vlm_cfg.image_size_px,
    )
    episode_meta = {
        "task_text": req.task,
        "allowed_labels": list(label_set.label_ids()),
        "label_version": label_set.schema_version,
        "robot_type": req.robot_adapter_name,
        "fps": fps,
        "episode_duration_sec": duration_sec,
    }

    def _labeler_factory(c: VLMConfig) -> Any:
        return vlm

    gripper_raw = adapter.gripper_signal(loaded.table)
    eef_vel_raw = adapter.eef_velocity(loaded.table)

    segments, _outcome, _notes = apply_phase2_labeling(
        segments=segments,
        extractor=extractor,
        gripper=gripper_raw,
        eef_velocity=eef_vel_raw,
        episode_meta=episode_meta,
        vlm_config=vlm_cfg,
        labeler_factory_override=_labeler_factory,
    )

    # 7) Stamp every segment with Phase 3 degrade fields.
    for seg in segments:
        seg.label_source = "vlm_robot_state_only"
        seg.object_state_unavailable = True
        seg.object_track_ids = []

    # 8) Build pipeline_status.
    pipeline_status = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=3,
        degrade_reason=degrade_reason,
        object_state_segment_coverage=0.0,
        adopted_frame_index=adopted_frame_index,
        grounding_attempts=(
            [a.to_dict() for a in grounding_attempts]
            if grounding_attempts else []
        ),
        # mask_overlay_unavailable_frames is irrelevant in degrade (no
        # SAM3 tracking happened), but write 0 for schema uniformity.
        mask_overlay_unavailable_frames=0,
    )

    # 9) annotation.notes — exact canonical message, NO underlying_log (PII rule §7.2/§8).
    notes = f"phase3: degraded to object-state-unavailable path (degrade_reason={degrade_reason})."

    # 10) Build manifest payloads.
    generated_at = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")

    pipeline_params: dict[str, Any] = {
        "boundary": {
            "weights": bcfg.weights.to_dict(target_phase=config.target_phase),
            "thresholds": dict(bcfg.thresholds),
            "merge_window_sec": bcfg.merge_window_sec,
            "score_threshold": bcfg.score_threshold,
            "disabled_sources": final_disabled,
        },
        "vlm": vlm_cfg.to_dict(),
        "tracking": tracking_cfg.to_dict(),
    }
    if bcfg.zero_crossing.enabled:
        pipeline_params["boundary"]["zero_crossing"] = bcfg.zero_crossing.to_dict()

    signal_channels: list[SignalChannel] = [
        downsample_for_viewer(
            SignalChannel(name="gripper", unit="normalized", values=gripper_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ),
    ]
    if vel_s is not None:
        signal_channels.append(
            downsample_for_viewer(
                SignalChannel(name="eef_velocity", unit="m/s", values=vel_s, dt_sec=1.0 / fps),
                target_hz=30.0,
            )
        )

    assert vlm_cfg.resolved_checkpoint is not None, (
        "pre-flight must populate vlm.resolved_checkpoint before _degrade_to_phase3_objectless"
    )
    model_versions: dict[str, str | None] = {
        "vlm": f"{vlm_cfg.model_id}:{vlm_cfg.resolved_checkpoint}",
        "sam3": tracking_cfg.sam3_model_id,
        "sam3_checkpoint": config.model_config.sam3_checkpoint,
    }

    task_info = TaskInfo(text=req.task, version=None)
    generator = GeneratorInfo(
        name="mimicanno",
        cli_version=__version__,
        pipeline_phase=config.target_phase,
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
        model_versions=model_versions,
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
        # spec §3.4: tracks artifact MUST NOT be present on degrade path
        artifacts=[
            Artifact("video", "video.mp4", "video/mp4"),
            Artifact("annotation", "annotation.json", "application/json"),
            Artifact("boundaries", "boundaries.json", "application/json"),
            Artifact("signals", "signals.json", "application/json"),
        ],
        # Phase 5 B r1: publish.py upserts the resolved name post-rename.
        canonical_name=None,
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
        model_versions=model_versions,
        pipeline_phase=config.target_phase,
        pipeline_status=pipeline_status,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=notes,
    )

    # 11) Publish — NO tracks.json written.
    def _write_artifacts(tmp_dir: Path) -> None:
        materialize_video(req.video, tmp_dir, link=req.link_video)
        write_signals_json(
            tmp_dir / "signals.json",
            episode_id=episode_id,
            duration_sec=duration_sec,
            channels=signal_channels,
        )
        write_boundaries_json(
            tmp_dir / "boundaries.json",
            episode_id=episode_id,
            candidates=candidates,
        )
        write_annotation_json(tmp_dir / "annotation.json", annotation)
        write_manifest_json(tmp_dir / "manifest.json", manifest)
        # tracks.json intentionally NOT written (spec §3.4 / §7.2)

    publish_req = PublishRequest(
        runs_root=req.runs_root,
        episode_id=episode_id,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        task_text=req.task,
        pipeline_phase=config.target_phase,
        generated_at=generated_at,
        force=req.force,
    )
    outcome = publish(publish_req, write_artifacts=_write_artifacts)

    name = canonical_name_for(episode_id, run_hash=run_hash)
    if is_collision(req.runs_root, canonical_name=name, expected_run_hash=run_hash):
        name = canonical_name_for(
            episode_id,
            run_hash=run_hash,
            length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )
    return AnnotateResult(run_dir=req.runs_root / name, outcome=outcome)


def _build_tracks_file(
    *,
    episode_id: str,
    fps: float,
    n_frames: int,
    image_width: int,
    image_height: int,
    stride: int,
    task_text: str,
    entities: EntityPlan,
    tracks: list[Any],
) -> TracksFile:
    """Convert a list of Track objects to the TracksFile wire format."""
    from mimicanno.object_tracker.propagator import Track

    tracks_wire: list[TracksTrack] = []
    for t in tracks:
        assert isinstance(t, Track)
        samples_wire = [
            TracksSample(
                frame=s.frame,
                time_sec=s.time_sec,
                bbox=[s.bbox.x, s.bbox.y, s.bbox.w, s.bbox.h],
                score=s.score,
            )
            for s in t.samples
        ]
        gaps_wire = [
            TracksGap(
                from_frame=g.from_frame,
                to_frame=g.to_frame,
                reason=g.reason,
            )
            for g in t.gap_events
        ]
        tracks_wire.append(
            TracksTrack(
                track_id=t.track_id,
                role=t.role,
                prompt=t.prompt,
                slug=t.slug,
                index=t.index,
                primary=t.primary,
                samples=samples_wire,
                gap_events=gaps_wire,
            )
        )

    n_samples_total = sum(len(tw.samples) for tw in tracks_wire)
    all_scores = [s.score for tw in tracks_wire for s in tw.samples]
    mean_score = float(np.mean(all_scores)) if all_scores else float("nan")

    # failed_prompts: all (role, prompt) pairs with no grounded detection
    # (We don't have a reference to the TrackingPlan here, so we infer from
    # entity prompts vs. tracks produced.)
    grounded_prompts: set[tuple[str, str]] = {(t.role, t.prompt) for t in tracks}
    all_prompts = entities.all_prompts_with_role()
    failed: list[tuple[str, str]] = [
        (role, prompt) for role, prompt in all_prompts
        if (role, prompt) not in grounded_prompts
    ]

    return TracksFile(
        schema_version="0.1.0",
        episode_id=episode_id,
        fps=fps,
        n_frames=n_frames,
        image_width=image_width,
        image_height=image_height,
        track_stride_frames=stride,
        tracking_plan=TracksTrackingPlan(
            task_text=task_text,
            object_prompts=list(entities.object_prompts),
            target_prompts=list(entities.target_prompts),
            tool_prompts=list(entities.tool_prompts),
            failed_prompts=failed,
        ),
        tracks=tracks_wire,
        stats=TracksStats(
            n_tracks=len(tracks_wire),
            n_samples_total=n_samples_total,
            mean_track_score=mean_score,
            tracking_wall_time_sec=0.0,
        ),
    )


def annotate_episode_phase3(req: AnnotateRequest) -> AnnotateResult:
    """Phase 3 orchestrator (spec §7.1).

    Stage 1a: robot signals (Phase 1 unchanged).
    Stage 1b: tracking — Step A entity extraction → SAM3 load → Step B ground
              → Step C propagate, with degrade gates and finally: cleanup.
    Stage 2:  Phase3BoundaryDetector (6 sources).
    Stage 3:  apply_phase3_labeling.
    """
    # Phase 3 requires VLM config + tracking config.
    if req.config.vlm is None:
        raise MimicAnnoError(
            "vlm.model_required",
            "target_phase >= 3 requires a vlm_config; got None.",
            {"target_phase": req.config.target_phase},
        )
    if req.config.tracking is None:
        raise MimicAnnoError(
            "tracking.config_required",
            "target_phase >= 3 requires a tracking_config; got None.",
            {"target_phase": req.config.target_phase},
        )
    tracking_cfg = req.config.tracking

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

    # 4) FPS resolution.
    timestamps = np.asarray(loaded.table.column("timestamp").to_pylist(), dtype=np.float64)
    try:
        fps_from_ts = resolve_fps(timestamps)
    except ParquetLoadError as e:
        raise MimicAnnoError("fps.unresolvable", str(e), {}) from e
    fps = float(probe.fps) if probe.fps > 0 else fps_from_ts
    duration_sec = float(probe.duration_sec)
    episode_id = req.parquet.stem

    # n_frames: number of rows in parquet is the ground truth
    n_frames = len(timestamps)

    # 5) Extract robot signals.
    gripper = adapter.gripper_signal(loaded.table)
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
    if eef_vel is not None:
        vel_s: np.ndarray | None = gaussian_smooth_1d(eef_vel, sigma=sigma)
        accel_s: np.ndarray | None = gaussian_smooth_1d(
            np.abs(np.diff(eef_vel, prepend=eef_vel[0])) * fps,
            sigma=sigma,
        )
    else:
        vel_s = None
        accel_s = None
    action_s = gaussian_smooth_1d(action_norm, sigma=sigma) if action_norm is not None else None

    # Phase 1 disabled sources (computed before the degrade gates so they
    # can be forwarded to _degrade_to_phase3_objectless when needed).
    disabled_phase1: list[str] = []
    if not has_eef:
        disabled_phase1.extend(["eef_velocity_valley", "eef_acceleration_peak"])
    if action_s is None:
        disabled_phase1.append("action_norm_change")

    # Stage 1b: tracking — Step A → SAM3 load → Step B → Step C

    # Extract initial frame (frame 0 with @5% retry)
    initial_frame = _extract_frame_at(req.video, n_frames, 0)

    # Load shared Gemma instance (バッチモードでは事前ロード済みを再利用)
    vlm_cfg = req.config.vlm
    if req.preloaded_vlm is not None:
        vlm = req.preloaded_vlm  # type: ignore[assignment]
    else:
        vlm = LocalGemmaVLMLabeler(vlm_cfg)
    planner = LocalGemmaTrackingPlanner(vlm.shared_handle())

    # Step A — entity extraction
    entities = planner.extract_entities(
        task_text=req.task,
        initial_frame=initial_frame,
        allowed_labels=label_set,
        attempt_max=tracking_cfg.planner_max_retries,
    )
    if not entities.object_prompts:
        return _degrade_to_phase3_objectless(
            req, req.config, vlm,
            fps=fps, duration_sec=duration_sec, n_frames=n_frames,
            episode_id=episode_id, config_hash=config_hash,
            input_hash=input_hash, run_hash=run_hash,
            label_set=label_set, probe=probe, loaded=loaded,
            adapter=adapter, adapter_config_sha=adapter_config_sha,
            timestamps=timestamps, gripper_s=gripper_s,
            vel_s=vel_s, accel_s=accel_s, action_s=action_s,
            has_eef=has_eef, disabled_sources_phase1=disabled_phase1,
            degrade_reason="gemma_no_object_prompts",
            grounding_attempts=None, adopted_frame_index=None,
        )

    # Step B + C with try/finally for SAM3.close
    stride = tracking_cfg.effective_stride(fps)
    image_aspect_ratio = _compute_image_aspect_ratio(probe, tracking_cfg)

    # CLI Task 18 guarantees sam3_checkpoint is set when target_phase >= 3.
    assert tracking_cfg.sam3_checkpoint is not None, (
        "tracking.sam3_checkpoint must be set by CLI for target_phase=3"
    )
    # --- SAM3 ランタイム取得 (preloaded を優先、無ければ新規 load) ---
    if req.preloaded_sam3_runtime is not None:
        # preloaded 経路: ライフサイクルは呼び出し元の責務。
        # close() は呼ばず、_close_all_sessions() で次の ep に備える。
        sam3_runtime = req.preloaded_sam3_runtime  # type: ignore[assignment]
        _owns_sam3_runtime = False
    else:
        # 従来経路 (mimicanno annotate CLI 1ep 1プロセス): 自前で load/close。
        try:
            sam3_runtime = SAM3Runtime.load(checkpoint=tracking_cfg.sam3_checkpoint)
        except SAM3InitFailed as e:
            return _degrade_to_phase3_objectless(
                req, req.config, vlm,
                fps=fps, duration_sec=duration_sec, n_frames=n_frames,
                episode_id=episode_id, config_hash=config_hash,
                input_hash=input_hash, run_hash=run_hash,
                label_set=label_set, probe=probe, loaded=loaded,
                adapter=adapter, adapter_config_sha=adapter_config_sha,
                timestamps=timestamps, gripper_s=gripper_s,
                vel_s=vel_s, accel_s=accel_s, action_s=action_s,
                has_eef=has_eef, disabled_sources_phase1=disabled_phase1,
                degrade_reason="sam3_init_failed",
                underlying_log=repr(e),
                grounding_attempts=None, adopted_frame_index=None,
            )
        _owns_sam3_runtime = True

    try:
        (
            adopted_frame_idx,
            initial_frame_used,
            plan,
            grounding_attempts,
        ) = ground_initial_detections_with_retry(
            runtime=sam3_runtime,
            video_path=req.video,
            n_frames=n_frames,
            entities=entities,
            retry_fractions=tracking_cfg.grounding_retry_fractions,
        )
        # Check that at least one "object" role was grounded
        object_grounded = [
            (role, prompt)
            for (role, prompt) in plan.initial_detections
            if role == "object"
        ]
        if not object_grounded:
            return _degrade_to_phase3_objectless(
                req, req.config, vlm,
                fps=fps, duration_sec=duration_sec, n_frames=n_frames,
                episode_id=episode_id, config_hash=config_hash,
                input_hash=input_hash, run_hash=run_hash,
                label_set=label_set, probe=probe, loaded=loaded,
                adapter=adapter, adapter_config_sha=adapter_config_sha,
                timestamps=timestamps, gripper_s=gripper_s,
                vel_s=vel_s, accel_s=accel_s, action_s=action_s,
                has_eef=has_eef, disabled_sources_phase1=disabled_phase1,
                degrade_reason="sam3_no_initial_detection",
                grounding_attempts=grounding_attempts,  # NEW
                adopted_frame_index=None,  # NEW (degrade → no adoption)
            )
        # Task 8 (vlm-mask-overlay): collect SAM3 masks at the keyframe
        # resolution when overlay is enabled so Stage 3 can paint them onto
        # Gemma's input keyframes. mask_cache stays None when overlay is
        # disabled — that path is bit-identical to pre-overlay behaviour.
        mask_overlay_enabled = (
            vlm_cfg is not None and vlm_cfg.mask_overlay.enabled
        )
        mask_image_size_px = (
            vlm_cfg.image_size_px if mask_overlay_enabled else None
        )
        tracks, mask_cache = Propagator().run(
            runtime=sam3_runtime,
            plan=plan,
            video_path=req.video,
            fps=fps,
            n_frames=n_frames,
            stride=stride,
            config=tracking_cfg,
            mask_image_size_px=mask_image_size_px,
            anchor_frame_index=adopted_frame_idx,
            propagation_direction="both" if adopted_frame_idx > 0 else "forward",
        )
    finally:
        if _owns_sam3_runtime:
            sam3_runtime.close()  # free GPU before Stage 3
        else:
            # preloaded 経路: ライフサイクルは呼び出し元の責務。
            # ここではセッションだけ片付けて次のエピソードで使えるようにする。
            sam3_runtime._close_all_sessions()

    object_signals = compute_object_signals(
        tracks,
        fps=fps,
        n_frames=n_frames,
        image_aspect_ratio=image_aspect_ratio,
    )

    # Stage 2: Phase3BoundaryDetector (6 sources)
    bcfg = req.config.boundary
    detector = Phase3BoundaryDetector(
        fps=fps,
        weights=bcfg.weights,
        score_threshold=bcfg.score_threshold,
        merge_window_sec=bcfg.merge_window_sec,
        disabled_sources=list(disabled_phase1),
        tracking_config=tracking_cfg,
        zero_crossing=bcfg.zero_crossing,
    )
    # Build smoothed signal arrays needed by the detector
    eef_vel_for_detector = vel_s if vel_s is not None else np.zeros(n_frames, dtype=np.float64)
    accel_for_detector = accel_s if accel_s is not None else np.zeros(n_frames, dtype=np.float64)
    action_for_detector = action_s if action_s is not None else np.zeros(n_frames, dtype=np.float64)
    candidates, final_disabled = detector.detect(
        gripper=gripper_s,
        eef_vel=eef_vel_for_detector,
        eef_accel=accel_for_detector,
        action_norm=action_for_detector,
        object_signals=object_signals,
        tracks=tracks,
    )

    segments = bracket_phase1_segments(
        episode_id=episode_id,
        candidates=candidates,
        fps=fps,
        duration_sec=duration_sec,
    )

    # Stage 3: Phase 3 labeling
    from mimicanno.clip_features import ClipFeatureExtractor

    extractor = ClipFeatureExtractor(
        video_path=req.video,
        fps=fps,
        clip_features_config=vlm_cfg.clip_features,
        image_size_px=vlm_cfg.image_size_px,
    )
    episode_meta = {
        "task_text": req.task,
        "allowed_labels": list(label_set.label_ids()),
        "label_version": label_set.schema_version,
        "robot_type": req.robot_adapter_name,
        "fps": fps,
        "episode_duration_sec": duration_sec,
    }
    def labeler_factory(c: VLMConfig) -> LocalGemmaVLMLabeler:  # reuse already-loaded model
        return vlm

    # Task 8 (vlm-mask-overlay): forward mask_cache + alpha so Stage 3
    # paints SAM3 masks on Gemma's keyframes and attaches the color legend
    # to the prompt. Both default to None / 0.4 when overlay is disabled.
    if mask_cache is not None:
        n_frames_cached = len(mask_cache.by_frame)
        nonempty = sum(
            1 for fmasks in mask_cache.by_frame.values()
            for blob in fmasks.values()
            if blob is not None
        )
        rle_bytes = sum(
            len(blob)
            for fmasks in mask_cache.by_frame.values()
            for blob in fmasks.values()
            if blob is not None
        )
        logger.info(
            "vlm_mask_overlay: frames_cached=%d nonempty_entries=%d "
            "palette=%s rle_bytes=%d shape=%s alpha=%.2f",
            n_frames_cached, nonempty, dict(mask_cache.palette),
            rle_bytes, mask_cache.shape, vlm_cfg.mask_overlay.alpha,
        )
    segments, _attempts, phase3_outcome, object_state_coverage = apply_phase3_labeling(
        segments=segments,
        tracks=tracks,
        object_signals=object_signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef_vel,
        episode_meta=episode_meta,
        config=vlm_cfg,
        tracking_config=tracking_cfg,
        labeler_factory=labeler_factory,
        mask_cache=mask_cache,
        mask_alpha=vlm_cfg.mask_overlay.alpha,
    )

    # Phase 4: temporal smoothing (spec §3, §7.1).
    smoothing_summary: SmoothingSummary | None = None
    if req.config.target_phase >= 4:
        if req.config.smoother is None:
            raise MimicAnnoError(
                "smoother.config_required",
                "target_phase >= 4 requires a smoother_config; got None.",
                {"target_phase": req.config.target_phase},
            )
        from mimicanno.smoother import apply_smoothing
        labelset_in_order = [lbl.id for lbl in label_set.labels]
        smoothing_result = apply_smoothing(
            segments,
            config=req.config.smoother,
            labelset=labelset_in_order,
        )
        segments = smoothing_result.segments
        smoothing_summary = smoothing_result.summary

    # Build tracks.json artifact
    tracks_file = _build_tracks_file(
        episode_id=episode_id,
        fps=fps,
        n_frames=n_frames,
        image_width=probe.width,
        image_height=probe.height,
        stride=stride,
        task_text=req.task,
        entities=entities,
        tracks=tracks,
    )

    # 7) Build pipeline_params for manifest.
    pipeline_params: dict[str, Any] = {
        "boundary": {
            "weights": bcfg.weights.to_dict(target_phase=req.config.target_phase),
            "thresholds": dict(bcfg.thresholds),
            "merge_window_sec": bcfg.merge_window_sec,
            "score_threshold": bcfg.score_threshold,
            "disabled_sources": final_disabled,
        },
        "vlm": vlm_cfg.to_dict(),
        "tracking": tracking_cfg.to_dict(),
    }
    if bcfg.zero_crossing.enabled:
        pipeline_params["boundary"]["zero_crossing"] = bcfg.zero_crossing.to_dict()
    if req.config.target_phase >= 4 and req.config.smoother is not None:
        pipeline_params["smoother"] = req.config.smoother.to_dict()

    # 8) Build per-channel signals downsampled for viewer.
    signal_channels: list[SignalChannel] = [
        downsample_for_viewer(
            SignalChannel(name="gripper", unit="normalized", values=gripper_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ),
    ]
    if vel_s is not None:
        signal_channels.append(
            downsample_for_viewer(
                SignalChannel(name="eef_velocity", unit="m/s", values=vel_s, dt_sec=1.0 / fps),
                target_hz=30.0,
            )
        )

    # 9) Build dataclass payloads.
    generated_at = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    _degraded = phase3_outcome.kind == "degraded"
    pipeline_status = PipelineStatus(
        object_state_available=True,
        degraded_from_phase=(req.config.target_phase if _degraded else None),
        degrade_reason=phase3_outcome.degrade_reason if _degraded else None,
        object_state_segment_coverage=object_state_coverage,
        adopted_frame_index=adopted_frame_idx,
        grounding_attempts=[a.to_dict() for a in grounding_attempts],
        # TODO: count missing mask frames (spec §7.4)
        mask_overlay_unavailable_frames=0,
    )
    task_info = TaskInfo(text=req.task, version=None)
    generator = GeneratorInfo(
        name="mimicanno",
        cli_version=__version__,
        pipeline_phase=req.config.target_phase,
    )

    assert vlm_cfg.resolved_checkpoint is not None, (
        "pre-flight (§2.5) must populate vlm.resolved_checkpoint before annotate_episode_phase3"
    )
    # Spec §1.3 line 188 + §7.1 line 968: `sam3` is the model id (informational
    # name like "facebook/sam3"); `sam3_checkpoint` is the sha256 (additive,
    # for downstream provenance). The composite "vlm" value matches Phase 2's
    # `annotate_episode` convention (see line 994+ below) and is preserved.
    model_versions: dict[str, str | None] = {
        "vlm": f"{vlm_cfg.model_id}:{vlm_cfg.resolved_checkpoint}",
        "sam3": tracking_cfg.sam3_model_id,
        "sam3_checkpoint": req.config.model_config.sam3_checkpoint,
    }

    manifest = Manifest(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["manifest"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions=model_versions,
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
            Artifact("tracks", "tracks.json", "application/json"),
        ],
        smoothing_summary=smoothing_summary,
        # Phase 5 B r1: publish.py upserts the resolved name post-rename.
        canonical_name=None,
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
        model_versions=model_versions,
        pipeline_phase=req.config.target_phase,
        pipeline_status=pipeline_status,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )

    # 10) Publish.
    def _write_artifacts(tmp_dir: Path) -> None:
        materialize_video(req.video, tmp_dir, link=req.link_video)
        write_signals_json(
            tmp_dir / "signals.json",
            episode_id=episode_id,
            duration_sec=duration_sec,
            channels=signal_channels,
        )
        write_boundaries_json(
            tmp_dir / "boundaries.json",
            episode_id=episode_id,
            candidates=candidates,
        )
        write_annotation_json(tmp_dir / "annotation.json", annotation)
        write_manifest_json(tmp_dir / "manifest.json", manifest)
        write_tracks_json(tmp_dir / "tracks.json", tracks_file)
        # U-A4: persist SAM3 masks as _masks/ sidecar for the frontend overlay.
        # mask_cache is None when mask_overlay_enabled=False (pre-bake skipped).
        if mask_cache is not None:
            from mimicanno.masks.sidecar import write_masks_sidecar
            write_masks_sidecar(tmp_dir, mask_cache, tracks, canonical=episode_id)

    publish_req = PublishRequest(
        runs_root=req.runs_root,
        episode_id=episode_id,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        task_text=req.task,
        pipeline_phase=req.config.target_phase,
        generated_at=generated_at,
        force=req.force,
    )
    outcome = publish(publish_req, write_artifacts=_write_artifacts)

    name = canonical_name_for(episode_id, run_hash=run_hash)
    if is_collision(req.runs_root, canonical_name=name, expected_run_hash=run_hash):
        name = canonical_name_for(
            episode_id,
            run_hash=run_hash,
            length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )
    return AnnotateResult(run_dir=req.runs_root / name, outcome=outcome)


def annotate_episode_phase4(req: AnnotateRequest) -> AnnotateResult:
    """Phase 4 orchestrator (spec §1.1).

    Phase 4 is a thin wrapper over :func:`annotate_episode_phase3`: the same
    inner pipeline (signals → boundaries → SAM3 → labeling) runs, the smoother
    is applied to the labeled segments, and ``manifest.smoothing_summary`` is
    populated. Phase 4 requires Phase 3 inputs (``--vlm-model``,
    ``--sam3-checkpoint``) plus a ``SmootherConfig`` on
    ``AnnotationConfig.smoother``.
    """
    if req.config.target_phase != 4:
        raise MimicAnnoError(
            "phase4.target_phase_mismatch",
            f"annotate_episode_phase4 requires target_phase=4; got {req.config.target_phase}",
            {"target_phase": req.config.target_phase},
        )
    if req.config.smoother is None:
        raise MimicAnnoError(
            "smoother.config_required",
            "target_phase=4 requires AnnotationConfig.smoother != None.",
            {"target_phase": req.config.target_phase},
        )
    return annotate_episode_phase3(req)


def annotate_episode(req: AnnotateRequest) -> AnnotateResult:
    # 1) Resolve label set.
    labels_path = req.labels_path or Path(default_labels_path("manipulation"))
    label_set = load_label_set(labels_path)

    # Phase 2 requires a VLMConfig; without it, refuse early.
    if req.config.target_phase >= 2 and req.config.vlm is None:
        raise MimicAnnoError(
            "vlm.model_required",
            "target_phase >= 2 requires a vlm_config; got None.",
            {"target_phase": req.config.target_phase},
        )

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
        raise MimicAnnoError("fps.unresolvable", str(e), {}) from e
    fps = float(probe.fps) if probe.fps > 0 else fps_from_ts
    duration_sec = float(probe.duration_sec)
    episode_id = req.parquet.stem  # Phase 1: derive from filename.

    # 5) Extract signals through the adapter.
    gripper = adapter.gripper_signal(loaded.table)
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
    if eef_vel is not None:
        vel_s: np.ndarray | None = gaussian_smooth_1d(eef_vel, sigma=sigma)
        # |a| in m/s2: |Δv| / dt where dt = 1/fps. Without the *fps, the values are
        # off by ~30x at 30 fps and the peak_threshold (set in m/s2) effectively
        # becomes 30x too high -- the detector would never fire on real data.
        accel_s: np.ndarray | None = gaussian_smooth_1d(
            np.abs(np.diff(eef_vel, prepend=eef_vel[0])) * fps,
            sigma=sigma,
        )
    else:
        vel_s = None
        accel_s = None
    action_s = gaussian_smooth_1d(action_norm, sigma=sigma) if action_norm is not None else None

    # 7) Detect per source.
    bcfg = req.config.boundary
    events = list(
        detect_gripper_transition(
            gripper_s,
            fps=fps,
            delta_threshold=bcfg.thresholds.get("gripper_delta", 0.30),
        )
    )
    if bcfg.zero_crossing.enabled:
        events.extend(
            detect_gripper_zero_crossing(
                gripper_s, fps=fps, cfg=bcfg.zero_crossing
            )
        )
    if vel_s is not None:
        events.extend(
            detect_eef_velocity_valley(
                vel_s,
                fps=fps,
                valley_threshold=bcfg.thresholds.get("velocity_valley", 0.05),
                min_valley_sec=0.10,
            )
        )
    if accel_s is not None:
        events.extend(
            detect_eef_acceleration_peak(
                accel_s,
                fps=fps,
                peak_threshold=1.0,
            )
        )
    if action_s is not None:
        events.extend(
            detect_action_norm_change(
                action_s,
                fps=fps,
                change_threshold=0.2,
                window_sec=0.5,
            )
        )

    # Translate BoundaryConfig.weights short keys to detector source names.
    # e.g. {"gripper": 0.5} → {"gripper_transition": 0.5}
    weights_dict = bcfg.weights.to_dict(target_phase=req.config.target_phase)
    unknown_keys = [k for k in weights_dict if k not in _WEIGHT_KEY_TO_SOURCE]
    if unknown_keys:
        raise MimicAnnoError(
            "boundary_config.unknown_weight_key",
            f"BoundaryConfig.weights contains unknown key(s): {unknown_keys!r}; "
            f"expected keys: {list(_WEIGHT_KEY_TO_SOURCE)!r}",
            {"unknown_keys": unknown_keys},
        )
    detector_weights = {_WEIGHT_KEY_TO_SOURCE[k]: v for k, v in weights_dict.items()}
    if bcfg.zero_crossing.enabled:
        detector_weights["gripper_zero_crossing"] = bcfg.zero_crossing.weight
    candidates = integrated_candidates(
        events,
        fps=fps,
        merge_window_sec=bcfg.merge_window_sec,
        weights=detector_weights,
        score_threshold=bcfg.score_threshold,
    )

    # 8) Determine disabled sources from what was actually run.
    disabled: list[str] = []
    if not has_eef:
        disabled.extend(["eef_velocity_valley", "eef_acceleration_peak"])
    if action_s is None:
        disabled.append("action_norm_change")

    # 9) Bracket into Phase 1 skeleton segments.
    segments = bracket_phase1_segments(
        episode_id=episode_id,
        candidates=candidates,
        fps=fps,
        duration_sec=duration_sec,
    )

    # Phase 2: VLM labeling (only if target_phase >= 2 and vlm config present).
    phase2_outcome: RunOutcome | None = None
    phase2_notes: str | None = None
    if req.config.target_phase >= 2 and req.config.vlm is not None:
        from mimicanno.clip_features import ClipFeatureExtractor

        vlm_cfg = req.config.vlm
        extractor = ClipFeatureExtractor(
            video_path=req.video,
            fps=fps,
            clip_features_config=vlm_cfg.clip_features,
            image_size_px=vlm_cfg.image_size_px,
        )
        episode_meta = {
            "task_text": req.task,
            "allowed_labels": list(label_set.label_ids()),
            "label_version": label_set.schema_version,
            "robot_type": req.robot_adapter_name,
            "fps": fps,
            "episode_duration_sec": duration_sec,
        }
        segments, phase2_outcome, phase2_notes = apply_phase2_labeling(
            segments=segments,
            extractor=extractor,
            gripper=gripper,
            eef_velocity=eef_vel,
            episode_meta=episode_meta,
            vlm_config=vlm_cfg,
        )

    # 10) Build pipeline_params for manifest (records what was actually used).
    pipeline_params: dict[str, Any] = {
        "boundary": {
            "weights": bcfg.weights.to_dict(target_phase=req.config.target_phase),
            "thresholds": dict(bcfg.thresholds),
            "merge_window_sec": bcfg.merge_window_sec,
            "score_threshold": bcfg.score_threshold,
            "disabled_sources": disabled,
        },
    }
    if bcfg.zero_crossing.enabled:
        pipeline_params["boundary"]["zero_crossing"] = bcfg.zero_crossing.to_dict()
    if req.config.target_phase >= 2 and req.config.vlm is not None:
        pipeline_params["vlm"] = req.config.vlm.to_dict()

    # 11) Build per-channel signals downsampled for viewer.
    signal_channels: list[SignalChannel] = [
        downsample_for_viewer(
            SignalChannel(name="gripper", unit="normalized", values=gripper_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ),
    ]
    if vel_s is not None:
        signal_channels.append(
            downsample_for_viewer(
                SignalChannel(name="eef_velocity", unit="m/s", values=vel_s, dt_sec=1.0 / fps),
                target_hz=30.0,
            )
        )

    # 12) Build dataclass payloads.
    generated_at = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    _degraded = phase2_outcome is not None and phase2_outcome.kind == "degraded"
    pipeline_status = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=(req.config.target_phase if _degraded else None),
        degrade_reason=(
            phase2_outcome.degrade_reason
            if (_degraded and phase2_outcome is not None)
            else None
        ),
    )
    task_info = TaskInfo(text=req.task, version=None)
    generator = GeneratorInfo(
        name="mimicanno",
        cli_version=__version__,
        pipeline_phase=req.config.target_phase,
    )

    model_versions: dict[str, str | None] = {"sam3": None, "vlm": None}
    if req.config.target_phase >= 2 and req.config.vlm is not None:
        assert req.config.vlm.resolved_checkpoint is not None, (
            "pre-flight (§2.5) must populate vlm.resolved_checkpoint before annotate_episode"
        )
        model_versions["vlm"] = f"{req.config.vlm.model_id}:{req.config.vlm.resolved_checkpoint}"

    manifest = Manifest(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["manifest"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions=model_versions,
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
        # Phase 5 B r1: publish.py upserts the resolved name post-rename.
        canonical_name=None,
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
        model_versions=model_versions,
        pipeline_phase=req.config.target_phase,
        pipeline_status=pipeline_status,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=phase2_notes,
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
            episode_id=episode_id,
            candidates=candidates,
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
        pipeline_phase=req.config.target_phase,
        generated_at=generated_at,
        force=req.force,
    )
    outcome = publish(publish_req, write_artifacts=_write_artifacts)

    # Resolve final dir from canonical_name (re-applies collision extension if needed).
    name = canonical_name_for(episode_id, run_hash=run_hash)
    if is_collision(req.runs_root, canonical_name=name, expected_run_hash=run_hash):
        name = canonical_name_for(
            episode_id,
            run_hash=run_hash,
            length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )
    return AnnotateResult(run_dir=req.runs_root / name, outcome=outcome)
