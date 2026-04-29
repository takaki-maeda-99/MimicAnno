"""AnnotationConfig + the composite hashing rule from spec §4.1.

config_hash covers everything that changes how the pipeline computes:
    AnnotationConfig + target_phase + model_config (vlm/sam3 + checkpoints).

input_hash covers the bytes/text that go in:
    video_sha256, parquet_sha256, task_text,
    robot_adapter_name, robot_adapter_config_sha256, labels_yaml_sha256.

run_hash = sha256(config_hash || input_hash).
canonical_name = f"{episode_id}__{run_hash[:12]}"  (extended to [:16] on collision).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from mimicanno.errors import (
    MimicAnnoError,
    SmootherConfigInvalid,
    SmootherUnknownLabelInForbidden,
)
from mimicanno.hashing import canonical_json, sha256_hex_of_str

DEFAULT_BOUNDARY_WEIGHTS: dict[str, float] = {
    "gripper": 0.5,
    "velocity": 0.25,
    "acceleration": 0.15,
    "action": 0.1,
}


@dataclass(slots=True, frozen=True)
class BoundaryWeights:
    gripper: float = DEFAULT_BOUNDARY_WEIGHTS["gripper"]
    velocity: float = DEFAULT_BOUNDARY_WEIGHTS["velocity"]
    acceleration: float = DEFAULT_BOUNDARY_WEIGHTS["acceleration"]
    action: float = DEFAULT_BOUNDARY_WEIGHTS["action"]
    gripper_object_distance_threshold_crossing: float = 0.0  # Phase 3
    object_motion_start_stop: float = 0.0                    # Phase 3

    @classmethod
    def phase3_defaults(cls) -> BoundaryWeights:
        return cls(
            gripper=0.45,
            velocity=0.15,
            acceleration=0.03,
            action=0.02,
            gripper_object_distance_threshold_crossing=0.25,
            object_motion_start_stop=0.10,
        )

    def to_dict(self, *, target_phase: int) -> dict[str, float]:
        payload: dict[str, float] = {
            "gripper": self.gripper,
            "velocity": self.velocity,
            "acceleration": self.acceleration,
            "action": self.action,
        }
        if target_phase >= 3:
            payload["gripper_object_distance_threshold_crossing"] = (
                self.gripper_object_distance_threshold_crossing
            )
            payload["object_motion_start_stop"] = self.object_motion_start_stop
        return payload


DEFAULT_BOUNDARY_THRESHOLDS: dict[str, float] = {
    "gripper_delta": 0.30,
    "velocity_valley": 0.05,
}
DEFAULT_MERGE_WINDOW_SEC: float = 0.10
DEFAULT_SCORE_THRESHOLD: float = 0.30

_VALID_WEIGHT_KEYS: frozenset[str] = frozenset(DEFAULT_BOUNDARY_WEIGHTS)
_VALID_THRESHOLD_KEYS: frozenset[str] = frozenset(DEFAULT_BOUNDARY_THRESHOLDS)
_VALID_TOP_KEYS: frozenset[str] = frozenset(
    {"weights", "thresholds", "merge_window_sec", "score_threshold", "disabled_sources"}
)

RUN_HASH_DEFAULT_PREFIX_LEN: int = 12
RUN_HASH_FALLBACK_PREFIX_LEN: int = 16


@dataclass(slots=True)
class BoundaryConfig:
    weights: BoundaryWeights
    thresholds: dict[str, float]
    merge_window_sec: float
    score_threshold: float
    disabled_sources: list[str]

    def to_dict(self, *, target_phase: int = 1) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(target_phase=target_phase),
            "thresholds": dict(self.thresholds),
            "merge_window_sec": self.merge_window_sec,
            "score_threshold": self.score_threshold,
            "disabled_sources": list(self.disabled_sources),
        }

    @classmethod
    def with_defaults(cls, *, weights: BoundaryWeights | None = None) -> BoundaryConfig:
        """BoundaryConfig populated with the spec-§4.3 default values."""
        return cls(
            weights=weights if weights is not None else BoundaryWeights(),
            thresholds=dict(DEFAULT_BOUNDARY_THRESHOLDS),
            merge_window_sec=DEFAULT_MERGE_WINDOW_SEC,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            disabled_sources=[],
        )


@dataclass(slots=True, frozen=True)
class ClipFeatureConfig:
    """Thresholds used by clip_features.py (spec §2.4)."""
    gripper_open_threshold: float = 0.5
    dwell_speed_threshold_mps: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        return {
            "gripper_open_threshold": self.gripper_open_threshold,
            "dwell_speed_threshold_mps": self.dwell_speed_threshold_mps,
        }


@dataclass(slots=True, frozen=True)
class VLMConfig:
    """Phase 2 VLM-pipeline configuration (spec §2.4).

    `resolved_checkpoint` MUST be populated by pre-flight (§2.5) before this
    config is fed into AnnotationConfig and hashed. It is `None` only during
    construction-time defaults; at hash-time of a target_phase >= 2 run, a
    None value is a producer bug.

    `fixture_path` is a runtime-only locator used when `model_id == "fixture"`.
    It is intentionally EXCLUDED from `to_dict()` and therefore from
    `config_hash` — a fixture file at `/tmp/x.json` and `/home/u/x.json`
    with the same content MUST produce the same run_hash (the content sha
    is already in `resolved_checkpoint`).
    """
    model_id: str
    keyframes_per_segment: int = 4
    keyframe_strategy: str = "uniform"  # extension point; only "uniform" supported in Phase 2
    image_size_px: int = 224
    max_retries: int = 3
    temperature: float = 0.0
    max_output_tokens: int = 256
    timeout_sec: float = 30.0
    runtime_failure_threshold: int = 3
    device: str = "cuda"
    dtype: str = "bfloat16"
    clip_features: ClipFeatureConfig = ClipFeatureConfig()
    resolved_checkpoint: str | None = None
    fixture_path: Path | None = None  # runtime-only; NOT in to_dict / config_hash

    def to_dict(self) -> dict[str, Any]:
        # NB: fixture_path is deliberately omitted (see class docstring).
        return {
            "clip_features": self.clip_features.to_dict(),
            "device": self.device,
            "dtype": self.dtype,
            "image_size_px": self.image_size_px,
            "keyframe_strategy": self.keyframe_strategy,
            "keyframes_per_segment": self.keyframes_per_segment,
            "max_output_tokens": self.max_output_tokens,
            "max_retries": self.max_retries,
            "model_id": self.model_id,
            "resolved_checkpoint": self.resolved_checkpoint,
            "runtime_failure_threshold": self.runtime_failure_threshold,
            "temperature": self.temperature,
            "timeout_sec": self.timeout_sec,
        }


@dataclass(slots=True, frozen=True)
class TrackingConfig:
    """Phase 3 tracking configuration (spec §7.4).

    NOTE: sam3_checkpoint (path string) is INTENTIONALLY excluded from
    to_dict() — the authoritative hashed value is model_config.sam3_checkpoint
    (sha256 of file content). Including the path here would make the hash
    sensitive to filesystem location (spec §9.1)."""

    sam3_model_id: str = "facebook/sam3"
    sam3_checkpoint: str | None = None       # path; CLI preflight validates
    track_stride_frames: int | None = None
    min_track_score: float = 0.30
    max_gap_frames: int | None = None
    reacquisition_iou_threshold: float = 0.30
    visibility_threshold: float = 0.5
    gripper_object_distance_threshold: float = 0.05  # image-width-normalized
    object_motion_threshold: float = 0.02            # image-width-normalized / sec
    object_motion_min_sec: float = 0.10
    image_aspect_ratio_default: float = 16.0 / 9.0
    planner_max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        # sam3_checkpoint is excluded — see class docstring + spec §9.1
        return {
            "sam3_model_id": self.sam3_model_id,
            "track_stride_frames": self.track_stride_frames,
            "min_track_score": self.min_track_score,
            "max_gap_frames": self.max_gap_frames,
            "reacquisition_iou_threshold": self.reacquisition_iou_threshold,
            "visibility_threshold": self.visibility_threshold,
            "gripper_object_distance_threshold": self.gripper_object_distance_threshold,
            "object_motion_threshold": self.object_motion_threshold,
            "object_motion_min_sec": self.object_motion_min_sec,
            "image_aspect_ratio_default": self.image_aspect_ratio_default,
            "planner_max_retries": self.planner_max_retries,
        }

    def effective_stride(self, fps: float) -> int:
        """Default stride = max(1, round(fps / 3))."""
        return (
            self.track_stride_frames
            if self.track_stride_frames is not None
            else max(1, round(fps / 3))
        )

    def effective_max_gap_frames(self, fps: float) -> int:
        return (
            self.max_gap_frames
            if self.max_gap_frames is not None
            else round(fps * 1.0)
        )


@dataclass(slots=True, frozen=True)
class SmootherConfig:
    """Phase 4 smoother parameters (spec §2).

    Hashed via ``to_dict`` only when ``target_phase >= 4`` (gated inside
    ``AnnotationConfig.to_dict``). Phase 1-3 runs leave
    ``AnnotationConfig.smoother = None`` and contribute nothing to ``config_hash``.
    """

    min_segment_duration_sec: float = 0.30
    forbidden_transitions: tuple[tuple[str, str], ...] = (
        ("grasp_object", "approach_object"),
        ("release_object", "grasp_object"),
        ("lift_object", "idle"),
    )
    viterbi_enabled: bool = True
    lambda_forbidden: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_segment_duration_sec": self.min_segment_duration_sec,
            "forbidden_transitions": [list(p) for p in self.forbidden_transitions],
            "viterbi_enabled": self.viterbi_enabled,
            "lambda_forbidden": self.lambda_forbidden,
        }


_RESERVED_PHASES_FOR_SMOOTHER: frozenset[str] = frozenset({"unlabeled", "unknown"})


def load_smoother_config_yaml(
    path: Path, *, allowed_labels: list[str]
) -> SmootherConfig:
    """Load and validate a SmootherConfig from YAML (spec §2.1).

    Missing fields fall back to ``SmootherConfig()`` defaults. ``allowed_labels``
    is the run's labelset id list; ``forbidden_transitions`` may reference any
    of those plus the reserved ``{"unknown", "unlabeled"}``.

    Raises:
        SmootherUnknownLabelInForbidden — when ``forbidden_transitions`` names a
            label outside ``allowed_labels`` and the reserved set.
        SmootherConfigInvalid — for parse / type / range / structural errors.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SmootherConfigInvalid(
            reason=f"could not read file: {e}", path=str(path),
        ) from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SmootherConfigInvalid(
            reason=f"not valid YAML: {e}", path=str(path),
        ) from e
    if raw is None:
        return SmootherConfig()
    if not isinstance(raw, dict):
        raise SmootherConfigInvalid(
            reason=f"top level must be a mapping, got {type(raw).__name__}",
            path=str(path),
        )

    valid_top_keys = {
        "min_segment_duration_sec",
        "forbidden_transitions",
        "viterbi_enabled",
        "lambda_forbidden",
    }
    unknown_keys = sorted(set(raw) - valid_top_keys)
    if unknown_keys:
        raise SmootherConfigInvalid(
            reason=(
                f"unknown key(s) {unknown_keys!r}; "
                f"expected any of {sorted(valid_top_keys)!r}"
            ),
            path=str(path),
        )

    defaults = SmootherConfig()

    # min_segment_duration_sec
    raw_min = raw.get("min_segment_duration_sec", defaults.min_segment_duration_sec)
    if not isinstance(raw_min, (int, float)) or isinstance(raw_min, bool):
        raise SmootherConfigInvalid(
            reason=(
                f"'min_segment_duration_sec' must be a number, "
                f"got {type(raw_min).__name__}"
            ),
            path=str(path),
        )
    min_dur = float(raw_min)
    if min_dur < 0:
        raise SmootherConfigInvalid(
            reason=f"'min_segment_duration_sec' must be >= 0, got {min_dur}",
            path=str(path),
        )

    # lambda_forbidden
    raw_lam = raw.get("lambda_forbidden", defaults.lambda_forbidden)
    if not isinstance(raw_lam, (int, float)) or isinstance(raw_lam, bool):
        raise SmootherConfigInvalid(
            reason=(
                f"'lambda_forbidden' must be a number, "
                f"got {type(raw_lam).__name__}"
            ),
            path=str(path),
        )
    lam = float(raw_lam)
    if lam < 0:
        raise SmootherConfigInvalid(
            reason=f"'lambda_forbidden' must be >= 0, got {lam}",
            path=str(path),
        )

    # viterbi_enabled
    raw_viterbi = raw.get("viterbi_enabled", defaults.viterbi_enabled)
    if not isinstance(raw_viterbi, bool):
        raise SmootherConfigInvalid(
            reason=(
                f"'viterbi_enabled' must be a boolean, "
                f"got {type(raw_viterbi).__name__}"
            ),
            path=str(path),
        )
    viterbi = bool(raw_viterbi)

    # forbidden_transitions
    raw_ft = raw.get("forbidden_transitions")
    if raw_ft is None:
        ft: tuple[tuple[str, str], ...] = defaults.forbidden_transitions
    else:
        if not isinstance(raw_ft, list):
            raise SmootherConfigInvalid(
                reason=(
                    "'forbidden_transitions' must be a list of [str, str] pairs, "
                    f"got {type(raw_ft).__name__}"
                ),
                path=str(path),
            )
        validated: list[tuple[str, str]] = []
        valid_labels = set(allowed_labels) | _RESERVED_PHASES_FOR_SMOOTHER
        for entry in raw_ft:
            if not isinstance(entry, list) or len(entry) != 2:
                raise SmootherConfigInvalid(
                    reason=(
                        f"each forbidden_transitions entry must be a length-2 list, "
                        f"got {entry!r}"
                    ),
                    path=str(path),
                )
            a, b = entry
            if not isinstance(a, str) or not isinstance(b, str):
                raise SmootherConfigInvalid(
                    reason=(
                        f"forbidden_transitions entries must be [str, str], "
                        f"got {entry!r}"
                    ),
                    path=str(path),
                )
            for label in (a, b):
                if label not in valid_labels:
                    raise SmootherUnknownLabelInForbidden(
                        label=label, path=str(path),
                    )
            validated.append((a, b))
        ft = tuple(validated)

    return SmootherConfig(
        min_segment_duration_sec=min_dur,
        forbidden_transitions=ft,
        viterbi_enabled=viterbi,
        lambda_forbidden=lam,
    )


def load_boundary_config_yaml(path: Path) -> BoundaryConfig:
    """Load a BoundaryConfig YAML, layering supplied fields onto defaults.

    Missing top-level fields fall back to ``BoundaryConfig.with_defaults()``;
    inside ``weights``/``thresholds`` the user dict fully replaces the default
    (we don't merge per-key, so a user can intentionally drop a detector by
    omitting it from ``weights``).

    Raises ``MimicAnnoError`` for unreadable files, non-mapping documents,
    unknown top-level keys, unknown weight/threshold keys, or wrong-typed
    values — all routed to ``write_error_json`` by the CLI.
    """
    try:
        text = path.read_text()
    except OSError as e:
        raise MimicAnnoError(
            "boundary_config.unreadable",
            f"could not read --boundary-config file: {e}",
            {"path": str(path)},
        ) from e
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise MimicAnnoError(
            "boundary_config.invalid_yaml",
            f"--boundary-config file is not valid YAML: {e}",
            {"path": str(path)},
        ) from e
    if raw is None:
        return BoundaryConfig.with_defaults()
    if not isinstance(raw, dict):
        raise MimicAnnoError(
            "boundary_config.not_mapping",
            f"--boundary-config top level must be a mapping; got {type(raw).__name__}",
            {"path": str(path)},
        )

    unknown_top = sorted(set(raw) - _VALID_TOP_KEYS)
    if unknown_top:
        raise MimicAnnoError(
            "boundary_config.unknown_key",
            f"--boundary-config has unknown key(s): {unknown_top!r}; "
            f"expected any of {sorted(_VALID_TOP_KEYS)!r}",
            {"path": str(path), "unknown_keys": unknown_top},
        )

    cfg = BoundaryConfig.with_defaults()

    if "weights" in raw:
        weights = raw["weights"]
        if not isinstance(weights, dict):
            raise MimicAnnoError(
                "boundary_config.invalid_value",
                "weights must be a mapping",
                {"path": str(path)},
            )
        unknown_w = sorted(set(weights) - _VALID_WEIGHT_KEYS)
        if unknown_w:
            raise MimicAnnoError(
                "boundary_config.unknown_weight_key",
                f"weights has unknown key(s): {unknown_w!r}; "
                f"expected any of {sorted(_VALID_WEIGHT_KEYS)!r}",
                {"path": str(path), "unknown_keys": unknown_w},
            )
        # Merge user-supplied weights onto defaults for keys not specified.
        default_w = BoundaryWeights()
        merged = {
            "gripper": float(weights.get("gripper", default_w.gripper)),
            "velocity": float(weights.get("velocity", default_w.velocity)),
            "acceleration": float(weights.get("acceleration", default_w.acceleration)),
            "action": float(weights.get("action", default_w.action)),
        }
        cfg.weights = BoundaryWeights(**merged)

    if "thresholds" in raw:
        thresholds = raw["thresholds"]
        if not isinstance(thresholds, dict):
            raise MimicAnnoError(
                "boundary_config.invalid_value",
                "thresholds must be a mapping",
                {"path": str(path)},
            )
        unknown_t = sorted(set(thresholds) - _VALID_THRESHOLD_KEYS)
        if unknown_t:
            raise MimicAnnoError(
                "boundary_config.unknown_threshold_key",
                f"thresholds has unknown key(s): {unknown_t!r}; "
                f"expected any of {sorted(_VALID_THRESHOLD_KEYS)!r}",
                {"path": str(path), "unknown_keys": unknown_t},
            )
        cfg.thresholds = {k: float(v) for k, v in thresholds.items()}

    if "merge_window_sec" in raw:
        cfg.merge_window_sec = float(raw["merge_window_sec"])
    if "score_threshold" in raw:
        cfg.score_threshold = float(raw["score_threshold"])
    if "disabled_sources" in raw:
        ds = raw["disabled_sources"]
        if not isinstance(ds, list) or not all(isinstance(x, str) for x in ds):
            raise MimicAnnoError(
                "boundary_config.invalid_value",
                "disabled_sources must be a list of strings",
                {"path": str(path)},
            )
        cfg.disabled_sources = list(ds)

    return cfg


@dataclass(slots=True)
class ModelConfig:
    vlm_model: str | None
    vlm_checkpoint: str | None
    sam3_model: str | None
    sam3_checkpoint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vlm_model": self.vlm_model,
            "vlm_checkpoint": self.vlm_checkpoint,
            "sam3_model": self.sam3_model,
            "sam3_checkpoint": self.sam3_checkpoint,
        }


def build_model_config(
    *,
    target_phase: int,
    vlm: VLMConfig | None,
    tracking: TrackingConfig | None,
    sam3_checkpoint_sha256: str | None,  # ← separate kwarg, NOT from tracking
) -> ModelConfig:
    """Build ModelConfig for a given target_phase. Phase 1/2: sam3_* are
    None (preserves existing Phase 1/2 hashes). Phase 3: sam3_* are
    populated from tracking config + the sha256 of the checkpoint file
    (computed by preflight; see Task 17).

    All four ModelConfig keys are always emitted by ModelConfig.to_dict()
    (existing serialization invariant). Gating is value-only, NOT key-only
    (spec §9.1 implementation reality note)."""
    return ModelConfig(
        vlm_model=vlm.model_id if (target_phase >= 2 and vlm is not None) else None,
        vlm_checkpoint=(
            vlm.resolved_checkpoint
            if (target_phase >= 2 and vlm is not None)
            else None
        ),
        sam3_model=(
            tracking.sam3_model_id if (target_phase >= 3 and tracking is not None) else None
        ),
        sam3_checkpoint=sam3_checkpoint_sha256 if target_phase >= 3 else None,
    )


@dataclass(slots=True)
class AnnotationConfig:
    boundary: BoundaryConfig
    target_phase: int
    model_config: ModelConfig
    vlm: VLMConfig | None = None  # required iff target_phase >= 2
    tracking: TrackingConfig | None = None  # required iff target_phase >= 3
    smoother: SmootherConfig | None = None  # required iff target_phase >= 4

    def to_dict(self) -> dict[str, Any]:
        ann_inner: dict[str, Any] = {
            "boundary": self.boundary.to_dict(target_phase=self.target_phase),
        }
        if self.vlm is not None:
            ann_inner["vlm"] = self.vlm.to_dict()
        if self.target_phase >= 3 and self.tracking is not None:
            ann_inner["tracking"] = self.tracking.to_dict()
        if self.target_phase >= 4 and self.smoother is not None:
            ann_inner["smoother"] = self.smoother.to_dict()
        return {
            "annotation_config": ann_inner,
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }


@dataclass(slots=True)
class InputBundle:
    """Identity of the inputs for one run. All sha256 strings are ``sha256:<hex>``."""

    video_sha256: str
    parquet_sha256: str
    task_text: str
    robot_adapter_name: str
    robot_adapter_config_sha256: str | None
    labels_yaml_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_sha256": self.video_sha256,
            "parquet_sha256": self.parquet_sha256,
            "task_text": self.task_text,
            "robot_adapter_name": self.robot_adapter_name,
            "robot_adapter_config_sha256": self.robot_adapter_config_sha256,
            "labels_yaml_sha256": self.labels_yaml_sha256,
        }


def compute_config_hash(cfg: AnnotationConfig) -> str:
    return "sha256:" + sha256_hex_of_str(canonical_json(cfg.to_dict()))


def compute_input_hash(inputs: InputBundle) -> str:
    return "sha256:" + sha256_hex_of_str(canonical_json(inputs.to_dict()))


def compose_run_hash(config_hash: str, input_hash: str) -> str:
    if not config_hash.startswith("sha256:"):
        raise ValueError(f"config_hash must be 'sha256:'-prefixed; got {config_hash!r}")
    if not input_hash.startswith("sha256:"):
        raise ValueError(f"input_hash must be 'sha256:'-prefixed; got {input_hash!r}")
    combined = config_hash + input_hash
    return "sha256:" + hashlib.sha256(combined.encode("utf-8")).hexdigest()


def run_hash_short(run_hash: str, length: int = RUN_HASH_DEFAULT_PREFIX_LEN) -> str:
    """Return the truncated hex prefix used as the canonical-name suffix."""
    if not run_hash.startswith("sha256:"):
        raise ValueError(f"run_hash must be 'sha256:'-prefixed; got {run_hash!r}")
    hex_part = run_hash[len("sha256:") :]
    return hex_part[:length]
