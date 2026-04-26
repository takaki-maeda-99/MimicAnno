# tests/unit/test_adapters_generic.py
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
import yaml

from mimicanno.adapters.generic import GenericAdapter


def _table_with_cols(n: int = 30) -> pa.Table:
    return pa.table(
        {
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
        }
    )


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
    assert a.name == "custom-arm"


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
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "0.1.0",
                "name": "min",
                "gripper_column": "observation.gripper",
            }
        )
    )
    a = GenericAdapter.from_yaml(cfg_path)
    assert a.eef_pose(_table_with_cols()) is None
    assert a.eef_velocity(_table_with_cols()) is None


def test_generic_eef_velocity_handles_single_frame(tmp_path: Path):
    cfg_path = _config_yaml(tmp_path)
    a = GenericAdapter.from_yaml(cfg_path)
    table = pa.table(
        {
            "observation.state": pa.array([[0.0] * 14]),
            "observation.eef_xyz": pa.array([[0.0, 0.0, 0.0]]),
            "observation.eef_quat": pa.array([[0.0, 0.0, 0.0, 1.0]]),
            "observation.gripper": pa.array([0.5]),
            "action": pa.array([[0.0] * 14]),
            "timestamp": pa.array([0.0]),
        }
    )
    v = a.eef_velocity(table)
    assert v is not None
    assert v.shape == (1,)
    assert (v == 0.0).all()


def test_generic_from_yaml_error_messages_cite_path(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: '0.0.1'\nname: x\n")
    with pytest.raises(ValueError, match=str(bad)):
        GenericAdapter.from_yaml(bad)


def test_generic_name_uses_yaml_value(tmp_path: Path):
    cfg = tmp_path / "named.yaml"
    cfg.write_text(
        "schema_version: '0.1.0'\nname: my-arm\ngripper_column: observation.gripper\n",
    )
    a = GenericAdapter.from_yaml(cfg)
    assert a.name == "my-arm"
