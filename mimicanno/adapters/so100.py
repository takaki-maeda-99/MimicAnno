# mimicanno/adapters/so100.py
"""SO-100 adapter: joint-only, layout shared with Koch for Phase 1."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class SO100Adapter:
    name: str = "so100"
    GRIPPER_INDEX: int = 5

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = np.asarray(df.column("observation.state").to_pylist(), dtype=np.float64)
        return np.clip(state[:, self.GRIPPER_INDEX], 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        return None

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        return None
