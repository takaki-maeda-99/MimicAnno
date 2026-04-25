# tests/unit/test_adapters_aloha.py
import numpy as np
import pyarrow as pa

from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter


def _aloha_table(n_frames: int = 30) -> pa.Table:
    # Aloha state layout (Phase-1 simplification): 14 floats per frame
    # for one arm with the LAST entry being the gripper position in [0,1],
    # and 6 entries before the gripper representing EEF pose (xyz + rpy quat-ish).
    # We synthesize a minimal-but-shaped vector here.
    rng = np.random.default_rng(0)
    state = rng.uniform(-1.0, 1.0, size=(n_frames, 14)).astype(np.float32)
    # Gripper at index 13: monotonic close
    state[:, 13] = np.linspace(1.0, 0.0, n_frames, dtype=np.float32)
    # EEF position columns (0..2 = xyz)
    state[:, 0:3] = np.cumsum(
        rng.normal(0, 0.01, size=(n_frames, 3)).astype(np.float32), axis=0,
    )
    action = rng.uniform(-1.0, 1.0, size=(n_frames, 14)).astype(np.float32)
    timestamps = np.arange(n_frames, dtype=np.float64) / 30.0
    return pa.table(
        {
            "observation.state": pa.array(state.tolist()),
            "action": pa.array(action.tolist()),
            "timestamp": pa.array(timestamps.tolist()),
        },
    )


def test_aloha_implements_protocol():
    a = AlohaAdapter()
    assert isinstance(a, RobotAdapter)


def test_aloha_name():
    assert AlohaAdapter().name == "aloha"


def test_aloha_gripper_signal_in_unit_interval():
    table = _aloha_table()
    g = AlohaAdapter().gripper_signal(table)
    assert g.shape == (30,)
    assert g.dtype == np.float64
    assert g.min() >= 0.0 and g.max() <= 1.0


def test_aloha_gripper_signal_is_strictly_decreasing_for_synthetic_close():
    table = _aloha_table()
    g = AlohaAdapter().gripper_signal(table)
    diffs = np.diff(g)
    assert (diffs <= 0).all()  # monotonic decrease per fixture


def test_aloha_eef_pose_returns_array():
    pose = AlohaAdapter().eef_pose(_aloha_table())
    assert pose is not None
    assert pose.shape == (30, 7)


def test_aloha_eef_velocity_is_finite_and_nonneg():
    v = AlohaAdapter().eef_velocity(_aloha_table())
    assert v is not None
    assert v.shape == (30,)
    assert np.isfinite(v).all()
    assert (v >= 0).all()


def test_aloha_eef_velocity_handles_single_frame():
    """1-frame episode: velocity is undefined; return zeros (length-T) without crashing."""
    table = pa.table({
        "observation.state": pa.array([[0.0] * 14]),
        "action": pa.array([[0.0] * 14]),
        "timestamp": pa.array([0.0]),
    })
    v = AlohaAdapter().eef_velocity(table)
    assert v is not None
    assert v.shape == (1,)
    assert (v == 0.0).all()
