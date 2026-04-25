# tests/unit/test_adapters_generic.py
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
import yaml

from mimicanno.adapters.generic import GenericAdapter


def _table_with_cols(n: int = 30) -> pa.Table:
    return pa.table({
        "observation.state": pa.array(
            [[0.0] * 14 for _ in range(n)],
        ),
        "observation.eef_xyz": pa.array(
            np.cumsum(np.zeros((n, 3)) + 0.01, axis=0).tolist(),
        ),
        "observation.eef_quat": pa.array([[0.0, 0.0, 0.0, 1.0]] * n),
        "observation.gripper": pa.array(np.linspace(1.0, 0.0, n).tolist()),
        "action": pa.array([[0.0] * 14 for _ in range(n)]),
        "timestamp": pa.array((np.arange(n) / 30.0).tolist()),
    })


def _config_yaml(tmp_path: Path) -> Path:
    cfg = {
        "schema_version": "0.1.0",
        "name": "custom-arm",
        "gripper_column": "observation.gripper",
        "eef_xyz_column": "observation.eef_xyz",
        "eef_quat_column": "observation.eef_quat",
    }
    p = tmp_path / "robot.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_generic_loads_yaml(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    assert a.name == "generic"


def test_generic_gripper_from_named_column(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    g = a.gripper_signal(_table_with_cols())
    assert g.shape == (30,)
    assert g[0] == pytest.approx(1.0)
    assert g[-1] == pytest.approx(0.0)


def test_generic_eef_pose_assembled_from_xyz_and_quat(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    pose = a.eef_pose(_table_with_cols())
    assert pose is not None
    assert pose.shape == (30, 7)


def test_generic_no_eef_when_columns_unmapped(tmp_path: Path):
    cfg_path = tmp_path / "min.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "schema_version": "0.1.0",
        "name": "min",
        "gripper_column": "observation.gripper",
    }))
    a = GenericAdapter.from_yaml(cfg_path)
    assert a.eef_pose(_table_with_cols()) is None
    assert a.eef_velocity(_table_with_cols()) is None
