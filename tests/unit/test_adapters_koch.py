# tests/unit/test_adapters_koch.py
import numpy as np
import pyarrow as pa

from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter


def _joint_only_table(n: int = 30) -> pa.Table:
    rng = np.random.default_rng(0)
    state = rng.uniform(-1.0, 1.0, size=(n, 6)).astype(np.float32)
    state[:, 5] = np.linspace(1.0, 0.0, n)
    action = rng.uniform(-1.0, 1.0, size=(n, 6)).astype(np.float32)
    ts = np.arange(n, dtype=np.float64) / 30.0
    return pa.table({
        "observation.state": pa.array(state.tolist()),
        "action": pa.array(action.tolist()),
        "timestamp": pa.array(ts.tolist()),
    })


class TestKoch:
    def test_name(self):
        assert KochAdapter().name == "koch"

    def test_gripper_signal_at_last_index(self):
        g = KochAdapter().gripper_signal(_joint_only_table())
        assert g.shape == (30,)
        assert g.min() >= 0.0 and g.max() <= 1.0

    def test_no_eef(self):
        a = KochAdapter()
        assert a.eef_pose(_joint_only_table()) is None
        assert a.eef_velocity(_joint_only_table()) is None

    def test_gripper_signal_clips_out_of_range(self):
        # Synthesize a table with joint-5 values outside [0,1] to confirm np.clip fires.
        n = 5
        state = np.zeros((n, 6), dtype=np.float32)
        state[:, 5] = np.array([-0.5, 0.0, 0.5, 1.5, 2.0])
        action = np.zeros((n, 6), dtype=np.float32)
        ts = np.arange(n, dtype=np.float64) / 30.0
        table = pa.table({
            "observation.state": pa.array(state.tolist()),
            "action": pa.array(action.tolist()),
            "timestamp": pa.array(ts.tolist()),
        })
        g = KochAdapter().gripper_signal(table)
        assert (g >= 0.0).all()
        assert (g <= 1.0).all()
        assert g[0] == 0.0   # -0.5 clipped to 0
        assert g[-1] == 1.0  # 2.0 clipped to 1


class TestSo100:
    def test_name(self):
        assert SO100Adapter().name == "so100"

    def test_gripper_signal(self):
        g = SO100Adapter().gripper_signal(_joint_only_table())
        assert g.shape == (30,)

    def test_no_eef(self):
        a = SO100Adapter()
        assert a.eef_pose(_joint_only_table()) is None
        assert a.eef_velocity(_joint_only_table()) is None
