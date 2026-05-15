"""S-RS T1: list_run_sets unit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.server.runs_repo import list_run_sets


def test_list_run_sets_multi(tmp_path: Path) -> None:
    (tmp_path / "so101_phase4_v5").mkdir()
    (tmp_path / "so101_phase4_v5" / "index.json").write_text("{}")
    (tmp_path / "piper_phase4_v5").mkdir()
    (tmp_path / "piper_phase4_v5" / "index.json").write_text("{}")
    result = list_run_sets(tmp_path)
    assert {r["name"] for r in result} == {"so101_phase4_v5", "piper_phase4_v5"}
    # each entry has both name and label
    for r in result:
        assert r["label"] == r["name"]


def test_list_run_sets_legacy(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text("{}")
    result = list_run_sets(tmp_path)
    assert result == [{"name": ".", "label": "(root)"}]


def test_list_run_sets_empty(tmp_path: Path) -> None:
    result = list_run_sets(tmp_path)
    assert result == []


def test_list_run_sets_ignores_dirs_without_index(tmp_path: Path) -> None:
    """Directories lacking index.json (e.g. .git, __pycache__) are skipped."""
    (tmp_path / "so101_phase4_v5").mkdir()
    (tmp_path / "so101_phase4_v5" / "index.json").write_text("{}")
    (tmp_path / "__pycache__").mkdir()
    result = list_run_sets(tmp_path)
    assert len(result) == 1
    assert result[0]["name"] == "so101_phase4_v5"


def test_list_run_sets_sorted(tmp_path: Path) -> None:
    for name in ("zzz_last", "aaa_first", "mmm_mid"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "index.json").write_text("{}")
    result = list_run_sets(tmp_path)
    assert [r["name"] for r in result] == ["aaa_first", "mmm_mid", "zzz_last"]
