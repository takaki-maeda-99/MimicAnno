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
