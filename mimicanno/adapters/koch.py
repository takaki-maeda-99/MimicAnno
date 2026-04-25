# mimicanno/adapters/koch.py
"""Koch adapter: joint-only state; no Cartesian EEF in the parquet by default."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class KochAdapter:
    name: str = "koch"
    GRIPPER_INDEX: int = 5

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = np.asarray(df.column("observation.state").to_pylist(), dtype=np.float64)
        return np.clip(state[:, self.GRIPPER_INDEX], 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        # Joint-only; FK is out of scope for Phase 1 (spec §7.2).
        return None

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        return None
