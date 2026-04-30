"""SO(3) helpers: rotvec <-> rotation matrix <-> quaternion (xyzw).

Wraps ``scipy.spatial.transform.Rotation`` so the rest of Phase 5 has a single
import surface for axis-angle / matrix / quaternion conversions used by
``ee_delta_6d`` math (spec §2.2) and adapter ee-pose normalization.
"""

from __future__ import annotations

import sys

import numpy as np
from scipy.spatial.transform import Rotation  # type: ignore[import-untyped]


class _StubTorchTensor:
    """Sentinel used only when ``sys.modules['torch']`` is a test stub.

    ``scipy.spatial.transform.Rotation`` (via ``scipy._lib.array_api_compat``)
    calls ``getattr(torch, 'Tensor')`` on every input array. The Phase 1/2 test
    suite installs a fake ``torch`` module (``tests/unit/test_local_gemma_skeleton.py``)
    that lacks ``Tensor``; the guard below patches a harmless stub so the
    ``isinstance(numpy_array, _StubTorchTensor)`` check in scipy returns False.
    """


def _ensure_torch_tensor_attr() -> None:
    mod = sys.modules.get("torch")
    if mod is not None and not hasattr(mod, "Tensor"):
        mod.Tensor = _StubTorchTensor  # type: ignore[attr-defined]


def exp_so3(rotvec: np.ndarray) -> np.ndarray:
    """Rotvec ``(3,)`` -> rotation matrix ``(3, 3)``."""
    _ensure_torch_tensor_attr()
    return np.asarray(Rotation.from_rotvec(rotvec).as_matrix(), dtype=np.float64)


def log_so3(R: np.ndarray) -> np.ndarray:  # noqa: N803 — math convention
    """Rotation matrix ``(3, 3)`` -> rotvec ``(3,)``."""
    _ensure_torch_tensor_attr()
    return np.asarray(Rotation.from_matrix(R).as_rotvec(), dtype=np.float64)


def quat_to_rotvec(quat_xyzw: np.ndarray) -> np.ndarray:
    """Quaternion ``(..., 4)`` in ``(x, y, z, w)`` -> rotvec ``(..., 3)``."""
    _ensure_torch_tensor_attr()
    return np.asarray(Rotation.from_quat(quat_xyzw).as_rotvec(), dtype=np.float64)


def rotvec_to_quat(rotvec: np.ndarray) -> np.ndarray:
    """Rotvec ``(..., 3)`` -> quaternion ``(..., 4)`` in ``(x, y, z, w)``."""
    _ensure_torch_tensor_attr()
    return np.asarray(Rotation.from_rotvec(rotvec).as_quat(), dtype=np.float64)
