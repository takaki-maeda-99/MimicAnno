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
from typing import Any

from mimicanno.hashing import canonical_json, sha256_hex_of_str

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_config": {"boundary": self.boundary.to_dict()},
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
