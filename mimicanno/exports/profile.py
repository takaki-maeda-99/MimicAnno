"""ExportProfile: typed wrapper around export YAML profiles (spec §5).

The profile is the single configuration object passed from the CLI down through
the bulk orchestrator and into the sink writer. Loaded from either a name
(``so101_sarm`` -> ``mimicanno/configs/exports/so101_sarm.yaml`` shipped with
the package) or an absolute / ``./``-prefixed path (spec §5.3).

After loading, ``ExportProfile.hash()`` returns the sha256 of canonical JSON of
``to_dict()``; this hash is recorded in ``.mimicanno-export.json`` and used by
the idempotency short-circuit (spec §9.1).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import jsonschema  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]

from mimicanno.errors import ErrorCode, MimicAnnoError


@dataclass(frozen=True)
class SourceConfig:
    robot_adapter: Literal["aloha", "koch", "so100", "generic"]
    pass_through_raw_action: bool
    generic_adapter_config: dict[str, Any] | None = None
    # When None, build_canonical_episode auto-detects: it concatenates all
    # parquet columns matching ``action.*`` (LeRobot v3 convention). Explicit
    # list overrides for datasets that mix or omit ``action.*`` columns.
    raw_action_columns: list[str] | None = None


@dataclass(frozen=True)
class CanonicalConfig:
    delta_basis: Literal["body_frame_t", "world", "base"]
    rotation_repr: Literal["rotvec"]
    gripper_source: Literal["observation", "action"]


@dataclass(frozen=True)
class SinkConfig:
    writer: Literal["lerobot_v3"]
    params: dict[str, Any]


@dataclass(frozen=True)
class SidecarConfig:
    enabled: bool
    path: str


@dataclass(frozen=True)
class GatesConfig:
    require_reviewed: bool
    forbid_degraded_pipeline: bool
    forbid_unlabeled_segments: bool


@dataclass(frozen=True)
class ExportProfile:
    schema_version: Literal["1"]
    name: str
    description: str
    source: SourceConfig
    canonical: CanonicalConfig
    sink: SinkConfig
    sidecar: SidecarConfig
    gates: GatesConfig

    @classmethod
    def resolve(cls, name_or_path: str) -> ExportProfile:
        """Resolve a profile name (package data) or load a YAML by path."""
        path = cls._resolve_path(name_or_path)
        if path is None:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_NOT_FOUND,
                f"profile {name_or_path!r} not found",
                {"name_or_path": name_or_path},
            )
        return cls.from_yaml(path)

    @staticmethod
    def _resolve_path(name_or_path: str) -> Path | None:
        if name_or_path.endswith((".yaml", ".yml")):
            p = Path(name_or_path)
            return p if p.is_file() else None
        try:
            t = resources.files("mimicanno.configs.exports").joinpath(
                f"{name_or_path}.yaml"
            )
            return Path(str(t)) if t.is_file() else None
        except (ModuleNotFoundError, FileNotFoundError):
            return None

    @classmethod
    def from_yaml(cls, path: Path) -> ExportProfile:
        try:
            cfg = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_INVALID,
                f"YAML parse error: {e}",
                {"path": str(path)},
            ) from e
        sch = json.loads(
            resources.files("mimicanno.jsonschemas")
            .joinpath("export_profile.schema.json")
            .read_text()
        )
        try:
            jsonschema.Draft202012Validator(sch).validate(cfg)
        except jsonschema.ValidationError as e:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_INVALID,
                f"profile schema violation: {e.message}",
                {"path": str(path), "json_path": list(e.absolute_path)},
            ) from e
        return cls(
            schema_version=cfg["schema_version"],
            name=cfg["name"],
            description=cfg.get("description", ""),
            source=SourceConfig(**cfg["source"]),
            canonical=CanonicalConfig(**cfg["canonical"]),
            sink=SinkConfig(**cfg["sink"]),
            sidecar=SidecarConfig(**cfg["sidecar"]),
            gates=GatesConfig(**cfg["gates"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def hash(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
