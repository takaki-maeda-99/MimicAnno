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
    BoundaryWeights,
    ZeroCrossingConfig,
    load_boundary_config_yaml,
)
from mimicanno.errors import MimicAnnoError


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "boundary.yaml"
    p.write_text(body)
    return p


def test_with_defaults_matches_spec_4_3() -> None:
    cfg = BoundaryConfig.with_defaults()
    assert cfg.weights == BoundaryWeights()
    assert cfg.weights.to_dict(target_phase=1) == DEFAULT_BOUNDARY_WEIGHTS
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
    assert cfg.weights.to_dict(target_phase=1) == DEFAULT_BOUNDARY_WEIGHTS
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
    assert cfg.weights == BoundaryWeights(gripper=0.4, velocity=0.3, acceleration=0.2, action=0.1)
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


# --- Phase 4 finer segmentation: ZeroCrossingConfig -------------------------


def test_zero_crossing_defaults_match_spec_4_2() -> None:
    zc = ZeroCrossingConfig()
    assert zc.enabled is False
    assert zc.signal == "gripper"
    assert zc.ref == "midpoint"
    assert zc.hysteresis == 0.05
    assert zc.span_eps == 0.05
    assert zc.merge_window_sec == 0.0
    assert zc.weight == 0.5


def test_zero_crossing_to_dict_round_trip() -> None:
    zc = ZeroCrossingConfig(
        enabled=True,
        ref="fixed:0.15",
        hysteresis=0.12,
        span_eps=0.06,
        merge_window_sec=0.3,
        weight=0.6,
    )
    assert zc.to_dict() == {
        "enabled": True,
        "signal": "gripper",
        "ref": "fixed:0.15",
        "hysteresis": 0.12,
        "span_eps": 0.06,
        "merge_window_sec": 0.3,
        "weight": 0.6,
    }


def test_boundary_config_default_zero_crossing_disabled() -> None:
    cfg = BoundaryConfig.with_defaults()
    assert cfg.zero_crossing == ZeroCrossingConfig()
    assert cfg.zero_crossing.enabled is False


def test_boundary_config_to_dict_omits_zero_crossing_when_disabled() -> None:
    cfg = BoundaryConfig.with_defaults()
    assert "zero_crossing" not in cfg.to_dict(target_phase=1)
    assert "zero_crossing" not in cfg.to_dict(target_phase=4)


def test_boundary_config_to_dict_includes_zero_crossing_when_enabled() -> None:
    cfg = BoundaryConfig.with_defaults()
    cfg.zero_crossing = ZeroCrossingConfig(enabled=True, hysteresis=0.12)
    d = cfg.to_dict(target_phase=4)
    assert d["zero_crossing"]["enabled"] is True
    assert d["zero_crossing"]["hysteresis"] == 0.12


def test_zero_crossing_yaml_full_load(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "zero_crossing:\n"
        "  enabled: true\n"
        "  ref: midpoint\n"
        "  hysteresis: 0.12\n"
        "  span_eps: 0.06\n"
        "  merge_window_sec: 0.2\n"
        "  weight: 0.6\n",
    )
    cfg = load_boundary_config_yaml(p)
    assert cfg.zero_crossing == ZeroCrossingConfig(
        enabled=True,
        ref="midpoint",
        hysteresis=0.12,
        span_eps=0.06,
        merge_window_sec=0.2,
        weight=0.6,
    )


def test_zero_crossing_yaml_partial_fields_fill_defaults(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  enabled: true\n  hysteresis: 0.10\n")
    cfg = load_boundary_config_yaml(p)
    zc = cfg.zero_crossing
    assert zc.enabled is True
    assert zc.hysteresis == 0.10
    # other fields fall back to defaults
    assert zc.ref == "midpoint"
    assert zc.span_eps == 0.05
    assert zc.merge_window_sec == 0.0
    assert zc.weight == 0.5


def test_zero_crossing_section_absent_keeps_defaults(tmp_path: Path) -> None:
    p = _write(tmp_path, "merge_window_sec: 0.15\n")
    cfg = load_boundary_config_yaml(p)
    assert cfg.zero_crossing == ZeroCrossingConfig()


def test_zero_crossing_ref_fixed_with_float_accepted(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  enabled: true\n  ref: 'fixed:0.18'\n")
    cfg = load_boundary_config_yaml(p)
    assert cfg.zero_crossing.ref == "fixed:0.18"


def test_zero_crossing_ref_bogus_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  ref: bogus\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_zero_crossing_ref_fixed_nonnumeric_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  ref: 'fixed:abc'\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_zero_crossing_negative_hysteresis_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  hysteresis: -0.1\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_zero_crossing_unknown_subkey_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  foo: 1\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.unknown_key"


def test_zero_crossing_enabled_must_be_bool(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  enabled: 1\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_zero_crossing_signal_must_be_gripper(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing:\n  signal: foo\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"


def test_zero_crossing_not_mapping_rejected(tmp_path: Path) -> None:
    p = _write(tmp_path, "zero_crossing: 7\n")
    with pytest.raises(MimicAnnoError) as exc:
        load_boundary_config_yaml(p)
    assert exc.value.code == "boundary_config.invalid_value"
