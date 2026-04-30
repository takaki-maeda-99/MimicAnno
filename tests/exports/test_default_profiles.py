"""Phase 5 — verify shipped default export profile YAMLs validate."""

from __future__ import annotations

import json
from importlib import resources

import jsonschema
import yaml


def _validate(yaml_name: str) -> dict:  # type: ignore[type-arg]
    sch = json.loads(
        resources.files("mimicanno.jsonschemas")
        .joinpath("export_profile.schema.json")
        .read_text()
    )
    cfg = yaml.safe_load(
        resources.files("mimicanno.configs.exports").joinpath(yaml_name).read_text()
    )
    jsonschema.Draft202012Validator(sch).validate(cfg)
    return cfg


def test_so101_sarm_profile_loads() -> None:
    cfg = _validate("so101_sarm.yaml")
    assert cfg["name"] == "so101_sarm"
    # SO101 uses the extended GenericAdapter (no so101.py adapter exists).
    assert cfg["source"]["robot_adapter"] == "generic"
    assert cfg["sink"]["params"]["annotation_prefix"] == "mimicanno"


def test_aloha_sarm_profile_loads() -> None:
    cfg = _validate("aloha_sarm.yaml")
    assert cfg["source"]["robot_adapter"] == "aloha"


def test_generic_profile_loads() -> None:
    cfg = _validate("generic.yaml")
    assert cfg["source"]["robot_adapter"] == "generic"
