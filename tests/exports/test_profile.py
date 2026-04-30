"""Phase 5 Task 5 — ExportProfile dataclass + YAML loader + profile_hash."""

from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.errors import MimicAnnoError
from mimicanno.exports.profile import ExportProfile

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_load_so101_sarm_by_name() -> None:
    p = ExportProfile.resolve("so101_sarm")
    assert p.name == "so101_sarm"
    assert p.source.robot_adapter == "generic"
    assert p.canonical.delta_basis == "body_frame_t"
    assert p.sidecar.enabled is True
    assert p.sink.params["annotation_prefix"] == "mimicanno"


def test_load_aloha_sarm_by_name() -> None:
    p = ExportProfile.resolve("aloha_sarm")
    assert p.source.robot_adapter == "aloha"


def test_load_generic_by_name() -> None:
    p = ExportProfile.resolve("generic")
    assert p.source.robot_adapter == "generic"


def test_load_by_absolute_path(tmp_path: Path) -> None:
    yml = tmp_path / "x.yaml"
    yml.write_text(
        (REPO_ROOT / "mimicanno/configs/exports/so101_sarm.yaml").read_text()
    )
    p = ExportProfile.resolve(str(yml))
    assert p.name == "so101_sarm"


def test_unknown_profile_raises_EXPORT_PROFILE_NOT_FOUND() -> None:
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve("nonexistent_profile_xyz")
    assert ei.value.code.name == "EXPORT_PROFILE_NOT_FOUND"


def test_invalid_yaml_raises_EXPORT_PROFILE_INVALID(tmp_path: Path) -> None:
    yml = tmp_path / "bad.yaml"
    yml.write_text("schema_version: '1'\nname: bad\n")  # missing required sections
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve(str(yml))
    assert ei.value.code.name == "EXPORT_PROFILE_INVALID"


def test_profile_hash_is_stable_across_loads() -> None:
    a = ExportProfile.resolve("so101_sarm")
    b = ExportProfile.resolve("so101_sarm")
    assert a.hash() == b.hash()
    assert len(a.hash()) == 64  # sha256 hex


def test_two_different_profiles_have_different_hashes() -> None:
    a = ExportProfile.resolve("so101_sarm")
    b = ExportProfile.resolve("aloha_sarm")
    assert a.hash() != b.hash()
