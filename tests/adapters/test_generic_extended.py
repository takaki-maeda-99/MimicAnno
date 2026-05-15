"""Phase 5 Task 4 — GenericAdapter schema 0.2.0:
- new fields: eef_rotvec_column, gripper_scale_min, gripper_scale_max
- backwards compat: 0.1.0 YAMLs continue to load and behave identically
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import yaml

from mimicanno.adapters.generic import GenericAdapter


def _write_yaml(tmp_path: Path, cfg: dict) -> Path:  # type: ignore[type-arg]
    p = tmp_path / "robot.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_rotvec_column_passthrough(tmp_path: Path) -> None:
    cfg = {
        "schema_version": "0.2.0",
        "name": "so101_test",
        "gripper_column": "g",
        "eef_xyz_column": "xyz",
        "eef_rotvec_column": "rv",
        "eef_quat_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table(
        {
            "g": pa.array([0.0, 50.0, 100.0]),
            "xyz": pa.array([[0.1, 0.0, 0.0], [0.2, 0.0, 0.0], [0.3, 0.0, 0.0]]),
            "rv": pa.array([[0.0, 0.0, 0.5], [0.0, 0.0, 0.6], [0.0, 0.0, 0.7]]),
        }
    )
    pose = a.eef_pose(df)
    assert pose is not None
    # xyz + rotvec when rotvec column is set
    assert pose.shape == (3, 6)
    np.testing.assert_allclose(
        pose[:, 3:], [[0, 0, 0.5], [0, 0, 0.6], [0, 0, 0.7]]
    )


def test_gripper_scale_min_max(tmp_path: Path) -> None:
    cfg = {
        "schema_version": "0.2.0",
        "name": "so101_test",
        "gripper_column": "g",
        "gripper_scale_min": 0.0,
        "gripper_scale_max": 100.0,
        "eef_xyz_column": None,
        "eef_quat_column": None,
        "eef_rotvec_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table({"g": pa.array([0.0, 25.0, 50.0, 100.0, 200.0])})
    g = a.gripper_signal(df)
    # 200 -> 2.0 -> clipped to 1.0
    np.testing.assert_allclose(g, [0.0, 0.25, 0.5, 1.0, 1.0])


def test_gripper_offset_applied_before_normalization(tmp_path: Path) -> None:
    # Simulates ep030-114 of GEM4_replace_the_cookie where the sensor zero-point
    # drifted by -2π. offset=+2π shifts raw values back into the normal range
    # before (g - min) / (max - min) normalization.
    cfg = {
        "schema_version": "0.2.0",
        "name": "offset_test",
        "gripper_column": "g",
        "gripper_offset": 6.2832,   # +2π
        "gripper_scale_min": 0.3,
        "gripper_scale_max": 6.5,
        "eef_xyz_column": None,
        "eef_quat_column": None,
        "eef_rotvec_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    # raw -5.5 + 6.2832 = 0.7832 → (0.7832 - 0.3) / 6.2 ≈ 0.0779
    # raw -1.5 + 6.2832 = 4.7832 → (4.7832 - 0.3) / 6.2 ≈ 0.7231
    df = pa.table({"g": pa.array([-5.5, -1.5])})
    g = a.gripper_signal(df)
    np.testing.assert_allclose(g[0], ((-5.5 + 6.2832) - 0.3) / (6.5 - 0.3), rtol=1e-5)
    np.testing.assert_allclose(g[1], ((-1.5 + 6.2832) - 0.3) / (6.5 - 0.3), rtol=1e-5)


def test_gripper_offset_zero_is_noop(tmp_path: Path) -> None:
    cfg = {
        "schema_version": "0.2.0",
        "name": "noop_offset",
        "gripper_column": "g",
        "gripper_offset": 0.0,
        "gripper_scale_min": 0.0,
        "gripper_scale_max": 100.0,
        "eef_xyz_column": None,
        "eef_quat_column": None,
        "eef_rotvec_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table({"g": pa.array([0.0, 50.0, 100.0])})
    g = a.gripper_signal(df)
    np.testing.assert_allclose(g, [0.0, 0.5, 1.0])


def test_gripper_offset_omitted_defaults_to_zero(tmp_path: Path) -> None:
    cfg = {
        "schema_version": "0.2.0",
        "name": "no_offset_field",
        "gripper_column": "g",
        "gripper_scale_min": 0.0,
        "gripper_scale_max": 10.0,
        "eef_xyz_column": None,
        "eef_quat_column": None,
        "eef_rotvec_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    assert a.gripper_offset == 0.0
    df = pa.table({"g": pa.array([5.0])})
    np.testing.assert_allclose(a.gripper_signal(df), [0.5])


def test_old_v0_1_0_yaml_still_loads_with_quat_column(tmp_path: Path) -> None:
    cfg = {
        "schema_version": "0.1.0",
        "name": "legacy",
        "gripper_column": "g",
        "eef_xyz_column": "xyz",
        "eef_quat_column": "q",
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table(
        {
            "g": pa.array([0.5]),
            "xyz": pa.array([[0.1, 0.0, 0.0]]),
            "q": pa.array([[0.0, 0.0, 0.0, 1.0]]),
        }
    )
    pose = a.eef_pose(df)
    assert pose is not None
    # legacy path returns xyz+quat (T, 7)
    assert pose.shape == (1, 7)
