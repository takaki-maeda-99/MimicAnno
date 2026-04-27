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

from mimicanno.errors import MimicAnnoError
from mimicanno.hashing import canonical_json, sha256_hex_of_str

DEFAULT_BOUNDARY_WEIGHTS: dict[str, float] = {
    "gripper": 0.5,
    "velocity": 0.25,
    "acceleration": 0.15,
    "action": 0.1,
}
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
    weights: dict[str, float]
    thresholds: dict[str, float]
    merge_window_sec: float
    score_threshold: float
    disabled_sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": dict(self.weights),
            "thresholds": dict(self.thresholds),
            "merge_window_sec": self.merge_window_sec,
            "score_threshold": self.score_threshold,
            "disabled_sources": list(self.disabled_sources),
        }

    @classmethod
    def with_defaults(cls) -> BoundaryConfig:
        """BoundaryConfig populated with the spec-§4.3 default values."""
        return cls(
            weights=dict(DEFAULT_BOUNDARY_WEIGHTS),
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
        cfg.weights = {k: float(v) for k, v in weights.items()}

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


@dataclass(slots=True)
class AnnotationConfig:
    boundary: BoundaryConfig
    target_phase: int
    model_config: ModelConfig
    vlm: VLMConfig | None = None  # required iff target_phase >= 2

    def to_dict(self) -> dict[str, Any]:
        ann_inner: dict[str, Any] = {"boundary": self.boundary.to_dict()}
        if self.vlm is not None:
            ann_inner["vlm"] = self.vlm.to_dict()
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
