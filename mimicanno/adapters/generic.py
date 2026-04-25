# mimicanno/adapters/generic.py
"""GenericAdapter: column mapping driven by a user-supplied YAML."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import yaml


@dataclass(slots=True)
class GenericAdapter:
    """Configurable adapter — column names come from a user-supplied YAML.

    Schema (``schema_version: "0.1.0"``):
        name: str               # informational
        gripper_column: str     # required; values clipped to [0,1]
        eef_xyz_column: str | None
        eef_quat_column: str | None
    """

    name: str
    gripper_column: str
    eef_xyz_column: str | None
    eef_quat_column: str | None

    @classmethod
    def from_yaml(cls, path: Path) -> "GenericAdapter":
        cfg = yaml.safe_load(path.read_text())
        if cfg.get("schema_version") != "0.1.0":
            raise ValueError(
                f"{path}: unsupported robot-config schema_version "
                f"(expected 0.1.0, got {cfg.get('schema_version')!r})",
            )
        if "gripper_column" not in cfg:
            raise ValueError(f"{path}: robot-config must specify gripper_column")
        return cls(
            name=cfg.get("name", "generic"),
            gripper_column=cfg["gripper_column"],
            eef_xyz_column=cfg.get("eef_xyz_column"),
            eef_quat_column=cfg.get("eef_quat_column"),
        )

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        col = df.column(self.gripper_column)
        g = np.asarray(col.to_pylist(), dtype=np.float64)
        return np.clip(g, 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        if self.eef_xyz_column is None or self.eef_quat_column is None:
            return None
        xyz = np.asarray(df.column(self.eef_xyz_column).to_pylist(), dtype=np.float64)
        quat = np.asarray(df.column(self.eef_quat_column).to_pylist(), dtype=np.float64)
        return np.concatenate([xyz, quat], axis=1)

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
