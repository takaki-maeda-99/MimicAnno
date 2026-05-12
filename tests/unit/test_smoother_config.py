"""Phase 4 SmootherConfig dataclass + YAML loader (spec §2)."""
from __future__ import annotations

import dataclasses
import tempfile
import textwrap
from pathlib import Path

import pytest

from mimicanno.config import SmootherConfig


def test_smoother_config_defaults() -> None:
    cfg = SmootherConfig()
    assert cfg.min_segment_duration_sec == 0.30
    assert cfg.viterbi_enabled is True
    assert cfg.lambda_forbidden == 0.5
    assert cfg.forbidden_transitions == (
        ("grasp_object", "approach_object"),
        ("release_object", "grasp_object"),
        ("lift_object", "idle"),
    )


def test_smoother_config_to_dict_shape() -> None:
    cfg = SmootherConfig()
    d = cfg.to_dict()
    assert set(d.keys()) == {
        "min_segment_duration_sec",
        "forbidden_transitions",
        "viterbi_enabled",
        "lambda_forbidden",
    }
    # forbidden_transitions serializes as list-of-list (canonical JSON)
    assert d["forbidden_transitions"] == [
        ["grasp_object", "approach_object"],
        ["release_object", "grasp_object"],
        ["lift_object", "idle"],
    ]


def test_smoother_config_is_frozen() -> None:
    """Frozen dataclass must not mutate after construction (hashable)."""
    cfg = SmootherConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.viterbi_enabled = False  # type: ignore[misc]


def test_smoother_config_to_dict_round_trip_through_json() -> None:
    """to_dict output must be JSON-serializable for canonical hashing."""
    import json
    cfg = SmootherConfig()
    payload = cfg.to_dict()
    # No exception
    s = json.dumps(payload, sort_keys=True)
    parsed = json.loads(s)
    assert parsed["forbidden_transitions"][0] == ["grasp_object", "approach_object"]


# ----- Source-aware merge preserve_sources (spec 2026-05-12) -----


def test_preserve_sources_default_empty_tuple() -> None:
    """Default value MUST be empty tuple — drives backward-compat semantics."""
    cfg = SmootherConfig()
    assert cfg.merge_same_label_preserve_sources == ()


def test_preserve_sources_to_dict_omits_key_when_empty() -> None:
    """Spec §3.1 conditional emit: empty tuple must not add the key to to_dict
    so existing v3/v4 ``config_hash`` stays byte-identical."""
    d = SmootherConfig().to_dict()
    assert "merge_same_label_preserve_sources" not in d


def test_preserve_sources_to_dict_includes_key_when_set() -> None:
    """Non-empty tuple emits key as ``list[str]`` (canonical JSON friendly)."""
    cfg = SmootherConfig(
        merge_same_label_preserve_sources=("gripper_zero_crossing",),
    )
    d = cfg.to_dict()
    assert d["merge_same_label_preserve_sources"] == ["gripper_zero_crossing"]


def test_preserve_sources_default_canonical_json_unchanged() -> None:
    """Spec §4 + §5.2: canonical_json output of default SmootherConfig must be
    byte-identical to the legacy 4-key form (no trace of the new field)."""
    from mimicanno.hashing import canonical_json
    payload = canonical_json(SmootherConfig().to_dict())
    assert "merge_same_label_preserve_sources" not in payload


def test_preserve_sources_default_canonical_bytes_pinned() -> None:
    """Pin the exact canonical_json bytes for default SmootherConfig to catch
    accidental key-order or formatting drift that would silently break
    existing v3/v4 ``config_hash`` values (spec 2026-05-12 §4)."""
    from mimicanno.hashing import canonical_json, sha256_hex_of_str
    payload = canonical_json(SmootherConfig().to_dict())
    expected = (
        '{"forbidden_transitions":'
        '[["grasp_object","approach_object"],'
        '["release_object","grasp_object"],'
        '["lift_object","idle"]],'
        '"lambda_forbidden":0.5,'
        '"min_segment_duration_sec":0.3,'
        '"viterbi_enabled":true}'
    )
    assert payload == expected
    # And the sha256 of the smoother-only payload (sanity that hashing.py is
    # stable). The actual ``config_hash`` covers AnnotationConfig as a whole.
    assert sha256_hex_of_str(payload) == sha256_hex_of_str(expected)


def test_preserve_sources_explicit_empty_equals_default() -> None:
    """Constructing SmootherConfig with an explicit empty tuple must produce
    bytes identical to the default (no field) — guarantees old YAML loaders
    that don't set the field can't drift from explicit empty-tuple users."""
    from mimicanno.hashing import canonical_json
    a = canonical_json(SmootherConfig().to_dict())
    b = canonical_json(SmootherConfig(merge_same_label_preserve_sources=()).to_dict())
    assert a == b


def test_preserve_sources_is_part_of_frozen_dataclass() -> None:
    """Field must be immutable — preserve_sources contributes to the frozen
    dataclass hash (used as dict key etc.)."""
    cfg = SmootherConfig(merge_same_label_preserve_sources=("x",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.merge_same_label_preserve_sources = ()  # type: ignore[misc]


def test_load_smoother_yaml_preserve_sources_happy_path() -> None:
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml(
        """
        merge_same_label_preserve_sources:
          - gripper_zero_crossing
          - depth_contact
        """
    )
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert cfg.merge_same_label_preserve_sources == (
        "gripper_zero_crossing", "depth_contact",
    )


def test_load_smoother_yaml_preserve_sources_absent_default_empty() -> None:
    """Old v3/v4 YAML (no preserve_sources key) must load with empty tuple."""
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml("min_segment_duration_sec: 0.3")
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert cfg.merge_same_label_preserve_sources == ()


def test_load_smoother_yaml_preserve_sources_not_list_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("merge_same_label_preserve_sources: gripper_zero_crossing")
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert "merge_same_label_preserve_sources" in exc_info.value.message


def test_load_smoother_yaml_preserve_sources_non_str_element_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml(
        """
        merge_same_label_preserve_sources:
          - gripper_zero_crossing
          - 42
        """
    )
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert "merge_same_label_preserve_sources" in exc_info.value.message


def test_load_smoother_yaml_preserve_sources_round_trip() -> None:
    """to_dict → YAML-shape → loader should round-trip the tuple."""
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml(
        """
        merge_same_label_preserve_sources:
          - gripper_zero_crossing
        """
    )
    allowed = [
        "approach_object", "grasp_object", "release_object",
        "lift_object", "idle",
    ]
    cfg1 = load_smoother_config_yaml(p, allowed_labels=allowed)
    # Synthesize an equivalent YAML from to_dict and re-load.
    import yaml
    p2 = _write_yaml(yaml.safe_dump(cfg1.to_dict()))
    cfg2 = load_smoother_config_yaml(p2, allowed_labels=allowed)
    assert cfg2.merge_same_label_preserve_sources == cfg1.merge_same_label_preserve_sources


def test_load_smoother_yaml_unknown_top_key_still_rejected() -> None:
    """Adding the new key to valid_top_keys must not accidentally allow others."""
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("totally_unknown_key: 1")
    with pytest.raises(SmootherConfigInvalid):
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])


# ----- YAML loader -----


def _write_yaml(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    f.write(textwrap.dedent(content).strip() + "\n")
    f.flush()
    f.close()
    return Path(f.name)


def test_load_smoother_yaml_happy_path() -> None:
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml(
        """
        min_segment_duration_sec: 0.5
        forbidden_transitions:
          - [grasp_object, approach_object]
        viterbi_enabled: false
        lambda_forbidden: 1.0
        """
    )
    allowed = ["approach_object", "grasp_object"]
    cfg = load_smoother_config_yaml(p, allowed_labels=allowed)
    assert cfg.min_segment_duration_sec == 0.5
    assert cfg.viterbi_enabled is False
    assert cfg.lambda_forbidden == 1.0
    assert cfg.forbidden_transitions == (("grasp_object", "approach_object"),)


def test_load_smoother_yaml_missing_fields_use_defaults() -> None:
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml("min_segment_duration_sec: 0.5")
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert cfg.viterbi_enabled is True
    assert cfg.lambda_forbidden == 0.5
    assert cfg.forbidden_transitions == SmootherConfig().forbidden_transitions


def test_load_smoother_yaml_unknown_label_in_forbidden_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherUnknownLabelInForbidden
    p = _write_yaml(
        """
        forbidden_transitions:
          - [grasp_object, no_such_label]
        """
    )
    with pytest.raises(SmootherUnknownLabelInForbidden) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_unknown_label_in_forbidden"
    assert "no_such_label" in exc_info.value.message


def test_load_smoother_yaml_negative_lambda_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("lambda_forbidden: -0.1")
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_config_invalid"


def test_load_smoother_yaml_negative_min_duration_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("min_segment_duration_sec: -0.1")
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_config_invalid"


def test_load_smoother_yaml_malformed_transition_raises() -> None:
    """Each forbidden_transitions entry must be a length-2 sequence."""
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml(
        """
        forbidden_transitions:
          - [grasp_object]
        """
    )
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_config_invalid"


def test_load_smoother_yaml_unparseable_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("[: not yaml")
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_config_invalid"


def test_load_smoother_yaml_reserved_labels_in_forbidden_ok() -> None:
    """`unknown` and `unlabeled` are reserved but valid forbidden-transition members."""
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml(
        """
        forbidden_transitions:
          - [grasp_object, unknown]
        """
    )
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert ("grasp_object", "unknown") in cfg.forbidden_transitions


def test_load_smoother_yaml_top_level_not_mapping_raises() -> None:
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.errors import SmootherConfigInvalid
    p = _write_yaml("- list_at_top_level")
    with pytest.raises(SmootherConfigInvalid) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.code == "smoother_config_invalid"


def test_load_smoother_yaml_empty_file_uses_all_defaults() -> None:
    from mimicanno.config import load_smoother_config_yaml
    p = _write_yaml("")
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert cfg == SmootherConfig()
