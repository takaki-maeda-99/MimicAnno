# mimicanno/adapters/generic.py
"""GenericAdapter: column mapping driven by a user-supplied YAML.

Schema versions:

- ``0.1.0`` (Phase 1): ``gripper_column``, ``eef_xyz_column``, ``eef_quat_column``.
  Gripper signal is clipped to [0, 1]. EE pose is xyz + quat -> shape (T, 7).
- ``0.2.0`` (Phase 5): adds ``eef_rotvec_column``, ``gripper_scale_min``,
  ``gripper_scale_max``, ``gripper_offset``. Gripper pipeline:
  1. ``g += gripper_offset`` (default 0.0 — no-op when omitted).
  2. ``g = (g - min) / (max - min)`` when both scale bounds are set.
  3. ``g = clip(g, 0, 1)``.
  ``gripper_offset`` is applied before normalization so it can fix sensors
  whose zero-point drifted by a known constant (e.g. ``+2π ≈ +6.2832`` for
  a rotary encoder that reset mid-session). EE pose is xyz + rotvec ->
  shape (T, 6) when ``eef_rotvec_column`` is set; xyz + quat -> (T, 7) is
  still supported. ``eef_rotvec_column`` and ``eef_quat_column`` are
  mutually exclusive.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import yaml  # type: ignore[import-untyped]

_SUPPORTED_SCHEMAS = ("0.1.0", "0.2.0")


@dataclass(slots=True)
class GenericAdapter:
    name: str
    gripper_column: str
    eef_xyz_column: str | None
    eef_quat_column: str | None
    eef_rotvec_column: str | None = None
    gripper_scale_min: float | None = None
    gripper_scale_max: float | None = None
    gripper_offset: float = 0.0

    @classmethod
    def from_yaml(cls, path: Path) -> GenericAdapter:
        cfg = yaml.safe_load(path.read_text())
        schema_version = cfg.get("schema_version")
        if schema_version not in _SUPPORTED_SCHEMAS:
            raise ValueError(
                f"{path}: unsupported robot-config schema_version "
                f"(expected one of {_SUPPORTED_SCHEMAS}, got {schema_version!r})",
            )
        if "gripper_column" not in cfg:
            raise ValueError(f"{path}: robot-config must specify gripper_column")

        eef_quat_column = cfg.get("eef_quat_column")
        eef_rotvec_column = cfg.get("eef_rotvec_column")
        if eef_quat_column is not None and eef_rotvec_column is not None:
            raise ValueError(
                f"{path}: eef_quat_column and eef_rotvec_column are mutually exclusive",
            )

        return cls(
            name=cfg.get("name", "generic"),
            gripper_column=cfg["gripper_column"],
            eef_xyz_column=cfg.get("eef_xyz_column"),
            eef_quat_column=eef_quat_column,
            eef_rotvec_column=eef_rotvec_column,
            gripper_scale_min=cfg.get("gripper_scale_min"),
            gripper_scale_max=cfg.get("gripper_scale_max"),
            gripper_offset=float(cfg.get("gripper_offset", 0.0)),
        )

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        col = df.column(self.gripper_column)
        g = np.asarray(col.to_pylist(), dtype=np.float64)
        if self.gripper_offset != 0.0:
            g = g + self.gripper_offset
        if (
            self.gripper_scale_min is not None
            and self.gripper_scale_max is not None
        ):
            span = self.gripper_scale_max - self.gripper_scale_min
            if span <= 0:
                raise ValueError(
                    f"gripper_scale_max ({self.gripper_scale_max}) must be "
                    f"strictly greater than gripper_scale_min ({self.gripper_scale_min})",
                )
            g = (g - self.gripper_scale_min) / span
        return np.clip(g, 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        if self.eef_xyz_column is None:
            return None
        xyz = np.asarray(df.column(self.eef_xyz_column).to_pylist(), dtype=np.float64)
        if self.eef_rotvec_column is not None:
            rv = np.asarray(
                df.column(self.eef_rotvec_column).to_pylist(), dtype=np.float64
            )
            return np.concatenate([xyz, rv], axis=1)
        if self.eef_quat_column is not None:
            quat = np.asarray(
                df.column(self.eef_quat_column).to_pylist(), dtype=np.float64
            )
            return np.concatenate([xyz, quat], axis=1)
        return None

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        pose = self.eef_pose(df)
        if pose is None:
            return None
        if len(pose) < 2:
            # Single-frame (or empty) episode: velocity is undefined; return zeros.
            return np.zeros(len(pose), dtype=np.float64)
        ts = np.asarray(df.column("timestamp").to_pylist(), dtype=np.float64)
        dt = np.diff(ts)
        if (dt <= 0).any():
            raise ValueError("non-monotonic timestamps in parquet")
        d_xyz = np.diff(pose[:, :3], axis=0)
        speed = np.linalg.norm(d_xyz, axis=1) / dt
        return np.concatenate([[speed[0]], speed]).astype(np.float64)
