"""Tests for ``mimicanno.exports.provenance`` (Phase 5 Task 21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.profile import ExportProfile
from mimicanno.exports.provenance import read_export_manifest, write_export_manifest


def _profile(tmp_path: Path) -> ExportProfile:
    return ExportProfile.resolve("so101_sarm")


def _kwargs(tmp_path: Path) -> dict:
    return {
        "profile": _profile(tmp_path),
        "runs_used": {0: "ep0__abcdef01", 1: "ep1__abcdef02"},
        "run_hashes": {0: "sha256:" + "a" * 64, 1: "sha256:" + "b" * 64},
        "source_dataset": Path("/abs/path/SO101"),
        "runs_root": Path("/abs/path/runs"),
        "target_phase": 4,
        "config_hash_filter": None,
        "output_mode": "symlink",
        "mimicanno_version": "0.1.0",
        "generated_at": "2026-04-30T12:34:56Z",
        "cli_args": ["--dataset", "/abs/path/SO101", "--target-phase", "4"],
        "host": {"platform": "linux", "python": "3.11.7"},
        "episode_count": 2,
        "subtask_count": 5,
    }


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    out.mkdir()
    path = write_export_manifest(out, **_kwargs(tmp_path))
    assert path == out / ".mimicanno-export.json"
    assert path.is_file()

    raw = json.loads(path.read_text())
    assert raw["schema_version"] == "1"
    assert raw["kind"] == "mimicanno.export"
    assert raw["profile"]["name"] == "so101_sarm"
    assert len(raw["profile"]["hash"]) == 64
    assert raw["target_phase"] == 4
    assert raw["output_mode"] == "symlink"
    assert raw["runs_used"] == {"0": "ep0__abcdef01", "1": "ep1__abcdef02"}
    assert raw["run_hashes"] == {
        "0": "sha256:" + "a" * 64,
        "1": "sha256:" + "b" * 64,
    }
    assert raw["episode_count"] == 2
    assert raw["subtask_count"] == 5
    assert raw["sidecar_schema_version"] == "1"
    assert raw["mimicanno_version"] == "0.1.0"
    assert raw["host"] == {"platform": "linux", "python": "3.11.7"}

    # read_export_manifest returns the parsed dict.
    again = read_export_manifest(out)
    assert again == raw


def test_read_export_manifest_missing(tmp_path: Path) -> None:
    out = tmp_path / "EMPTY"
    out.mkdir()
    assert read_export_manifest(out) is None


def test_optional_config_hash_filter(tmp_path: Path) -> None:
    out = tmp_path / "OUT"
    out.mkdir()
    kwargs = _kwargs(tmp_path)
    kwargs["config_hash_filter"] = "sha256:" + "c" * 64
    write_export_manifest(out, **kwargs)
    raw = json.loads((out / ".mimicanno-export.json").read_text())
    assert raw["config_hash_filter"] == "sha256:" + "c" * 64


def test_home_paths_sanitized_in_provenance(tmp_path: Path, monkeypatch) -> None:
    """S7: $HOME-prefixed paths in cli_args / source_dataset_path / runs_root
    are rewritten to $HOME/... so publishing the dataset doesn't leak the
    user's absolute home path."""
    fake_home = "/home/alice_test"
    monkeypatch.setenv("HOME", fake_home)
    out = tmp_path / "OUT"
    out.mkdir()
    kwargs = _kwargs(tmp_path)
    kwargs["source_dataset"] = Path(f"{fake_home}/datasets/SO101")
    kwargs["runs_root"] = Path(f"{fake_home}/runs")
    kwargs["cli_args"] = [
        "annotate",
        "--video", f"{fake_home}/data/ep0.mp4",
        "--task", "pick",
        "--robot", "so100",
    ]
    write_export_manifest(out, **kwargs)
    raw = json.loads((out / ".mimicanno-export.json").read_text())
    assert raw["source_dataset_path"] == "$HOME/datasets/SO101"
    assert raw["runs_root"] == "$HOME/runs"
    assert raw["cli_args"] == [
        "annotate",
        "--video", "$HOME/data/ep0.mp4",
        "--task", "pick",
        "--robot", "so100",
    ]


def test_non_home_paths_preserved_in_provenance(tmp_path: Path, monkeypatch) -> None:
    """Non-$HOME absolute paths and bare flags are left as-is (no
    over-aggressive sanitization)."""
    monkeypatch.setenv("HOME", "/home/alice_test")
    out = tmp_path / "OUT"
    out.mkdir()
    kwargs = _kwargs(tmp_path)
    kwargs["source_dataset"] = Path("/srv/datasets/foo")
    kwargs["runs_root"] = Path("/var/lib/mimicanno/runs")
    kwargs["cli_args"] = ["--target-phase", "4", "--profile", "so101_sarm"]
    write_export_manifest(out, **kwargs)
    raw = json.loads((out / ".mimicanno-export.json").read_text())
    assert raw["source_dataset_path"] == "/srv/datasets/foo"
    assert raw["runs_root"] == "/var/lib/mimicanno/runs"
    assert raw["cli_args"] == ["--target-phase", "4", "--profile", "so101_sarm"]


def test_invalid_target_phase_rejected(tmp_path: Path) -> None:
    """Schema enforces target_phase in [1, 4]."""
    out = tmp_path / "OUT"
    out.mkdir()
    kwargs = _kwargs(tmp_path)
    kwargs["target_phase"] = 99
    with pytest.raises(MimicAnnoError) as ei:
        write_export_manifest(out, **kwargs)
    # Internal-manifest violation (mimicanno bug) — NOT user-profile
    # violation (which is EXPORT_PROFILE_INVALID).
    assert ei.value.code == ErrorCode.EXPORT_INTERNAL_MANIFEST_INVALID
