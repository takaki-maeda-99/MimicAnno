# mimicanno/adapters/base.py
"""RobotAdapter Protocol — see spec §7.2."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pyarrow as pa


@runtime_checkable
class RobotAdapter(Protocol):
    """Per-robot accessor for the signals Phase 1 needs.

    ``gripper_signal`` is mandatory. The two EEF accessors are optional —
    return ``None`` when the robot's parquet does not carry Cartesian EEF
    data; the boundary detector will auto-disable EEF-based detectors and
    record them in ``manifest.pipeline_params.boundary.disabled_sources``.
    Forward kinematics from joint angles is out of scope for Phase 1.
    """

    name: str

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        """Return ``[T]`` float64 array in [0.0, 1.0] (1.0 = open)."""
        ...

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        """Return ``[T, 7]`` float64 (xyz + quat). May return None."""
        ...

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        """Return ``[T]`` float64 in m/s (magnitude). May return None."""
        ...
