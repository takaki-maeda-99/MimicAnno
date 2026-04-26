"""Unit tests for ``load_boundary_config_yaml``.

Covers the partial-overlay semantics, the validation paths exposed via
``MimicAnnoError``, and the contract that an empty/None YAML still returns
spec-§4.3 defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.config import (
    DEFAULT_BOUNDARY_THRESHOLDS,
    DEFAULT_BOUNDARY_WEIGHTS,
    DEFAULT_MERGE_WINDOW_SEC,
    DEFAULT_SCORE_THRESHOLD,
    BoundaryConfig,
    load_boundary_config_yaml,
)
from mimicanno.errors import MimicAnnoError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "boundary.yaml"
    p.write_text(body)
    return p


def test_with_defaults_matches_spec_4_3() -> None:
    cfg = BoundaryConfig.with_defaults()
    assert cfg.weights == DEFAULT_BOUNDARY_WEIGHTS
    assert cfg.thresholds == DEFAULT_BOUNDARY_THRESHOLDS
    assert cfg.merge_window_sec == DEFAULT_MERGE_WINDOW_SEC
    assert cfg.score_threshold == DEFAULT_SCORE_THRESHOLD
    assert cfg.disabled_sources == []


def test_empty_yaml_returns_defaults(tmp_path: Path) -> None:
    p = _write(tmp_path, "")
    cfg = load_boundary_config_yaml(p)
    assert cfg.thresholds == DEFAULT_BOUNDARY_THRESHOLDS


def test_partial_overlay_only_replaces_specified_fields(tmp_path: Path) -> None:
    p = _write(tmp_path, "thresholds:\n  gripper_delta: 0.15\n")
    cfg = load_boundary_config_yaml(p)
    # thresholds dict is replaced wholesale; defaults for unspecified fields stay.
    assert cfg.thresholds == {"gripper_delta": 0.15}
    assert cfg.weights == DEFAULT_BOUNDARY_WEIGHTS
    assert cfg.merge_window_sec == DEFAULT_MERGE_WINDOW_SEC
    assert cfg.score_threshold == DEFAULT_SCORE_THRESHOLD


def test_full_yaml_round_trips(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "weights:\n"
        "  gripper: 0.4\n"
        "  velocity: 0.3\n"
        "  acceleration: 0.2\n"
        "  action: 0.1\n"
        "thresholds:\n"
        "  gripper_delta: 0.15\n"
        "  velocity_valley: 0.04\n"
        "merge_window_sec: 0.20\n"
        "score_threshold: 0.25\n"
        "disabled_sources:\n"
        "  - action_norm_change\n",
    )
    cfg = load_boundary_config_yaml(p)
    assert cfg.weights == {"gripper": 0.4, "velocity": 0.3, "acceleration": 0.2, "action": 0.1}
    assert cfg.thresholds == {"gripper_delta": 0.15, "velocity_valley": 0.04}
    assert cfg.merge_window_sec == 0.20
    assert cfg.score_threshold == 0.25
    assert cfg.disabled_sources == ["action_norm_change"]


def test_unknown_top_level_key_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "weights:\n  gripper: 0.5\nbogus: 1\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.unknown_key"


def test_unknown_weight_key_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "weights:\n  not_a_detector: 0.5\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.unknown_weight_key"


def test_unknown_threshold_key_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "thresholds:\n  bogus_threshold: 0.1\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.unknown_threshold_key"


def test_top_level_not_mapping_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "- a\n- b\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.not_mapping"


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "weights:\n  - this is invalid\n  : oops\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_yaml"


def test_disabled_sources_must_be_string_list(tmp_path: Path) -> None:
    p = _write(tmp_path, "disabled_sources: 7\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_unreadable_path_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(missing)
    assert exc.value.code == "boundary_config.unreadable"
