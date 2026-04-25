# mimicanno/adapters/aloha.py
"""Aloha adapter: Cartesian EEF available, gripper at the last state index."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class AlohaAdapter:
    name: str = "aloha"

    # Indices into observation.state for the single-arm Aloha layout.
    EEF_XYZ_SLICE: slice = slice(0, 3)
    EEF_QUAT_SLICE: slice = slice(3, 7)
    GRIPPER_INDEX: int = 13

    def _state(self, df: pa.Table) -> np.ndarray:
        # Each row of observation.state is a list/array of floats; convert to (T, D).
        col = df.column("observation.state")
        return np.asarray(col.to_pylist(), dtype=np.float64)

    def _timestamps(self, df: pa.Table) -> np.ndarray:
        return np.asarray(df.column("timestamp").to_pylist(), dtype=np.float64)

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = self._state(df)
        g = state[:, self.GRIPPER_INDEX].astype(np.float64)
        # Defensive clip; downstream code assumes [0,1].
        return np.clip(g, 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        state = self._state(df)
        xyz = state[:, self.EEF_XYZ_SLICE]
        quat = state[:, self.EEF_QUAT_SLICE]
        return np.concatenate([xyz, quat], axis=1).astype(np.float64)

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        pose = self.eef_pose(df)
        if pose is None:
            return None
        ts = self._timestamps(df)
        # Backward-difference magnitude. dt[0] handled by replicating dt[1].
        dt = np.diff(ts)
        if (dt <= 0).any():
            raise ValueError("non-monotonic timestamps in parquet")
        d_xyz = np.diff(pose[:, :3], axis=0)
        speed = np.linalg.norm(d_xyz, axis=1) / dt
        return np.concatenate([[speed[0]], speed]).astype(np.float64)
