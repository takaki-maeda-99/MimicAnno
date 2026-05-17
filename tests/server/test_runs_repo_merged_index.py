"""Tests for RunsRepository.read_merged_index — multi-run-set merging."""
from __future__ import annotations

import json
from pathlib import Path

from mimicanno.server.runs_repo import RunsRepository


def _write_index(path: Path, runs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "0.1.0", "runs": runs}))


def test_merged_index_multi_mode_no_root(tmp_path: Path) -> None:
    """Two subdirs with index.json; no root index.json. Merge tags each row."""
    _write_index(
        tmp_path / "set_a" / "index.json",
        [{"episode_id": "episode_000000", "run_hash": "sha256:" + "a" * 64,
          "manifest_url": "episode_000000__aaa/manifest.json",
          "run_hash_short": "aaaaaaaaaaaa", "config_hash_short": "1",
          "input_hash_short": "2", "task_text": "t", "pipeline_phase": 4,
          "generated_at": "2026-01-01T00:00:00Z"}],
    )
    _write_index(
        tmp_path / "set_b" / "index.json",
        [{"episode_id": "episode_000001", "run_hash": "sha256:" + "b" * 64,
          "manifest_url": "episode_000001__bbb/manifest.json",
          "run_hash_short": "bbbbbbbbbbbb", "config_hash_short": "3",
          "input_hash_short": "4", "task_text": "u", "pipeline_phase": 4,
          "generated_at": "2026-01-02T00:00:00Z"}],
    )
    repo = RunsRepository(tmp_path)
    doc = json.loads(repo.read_merged_index())
    assert doc["schema_version"] == "0.1.0"
    by_set = {r["run_set"]: r for r in doc["runs"]}
    assert set(by_set) == {"set_a", "set_b"}
    assert by_set["set_a"]["episode_id"] == "episode_000000"
    assert by_set["set_b"]["episode_id"] == "episode_000001"


def test_merged_index_includes_root_as_dot(tmp_path: Path) -> None:
    """Root index.json present + a subdir → both included, root tagged '.'."""
    _write_index(
        tmp_path / "index.json",
        [{"episode_id": "episode_000000", "run_hash": "sha256:" + "c" * 64,
          "manifest_url": "episode_000000__ccc/manifest.json",
          "run_hash_short": "cccccccccccc", "config_hash_short": "5",
          "input_hash_short": "6", "task_text": "v", "pipeline_phase": 4,
          "generated_at": "2026-01-03T00:00:00Z"}],
    )
    _write_index(
        tmp_path / "set_x" / "index.json",
        [{"episode_id": "episode_000002", "run_hash": "sha256:" + "d" * 64,
          "manifest_url": "episode_000002__ddd/manifest.json",
          "run_hash_short": "dddddddddddd", "config_hash_short": "7",
          "input_hash_short": "8", "task_text": "w", "pipeline_phase": 4,
          "generated_at": "2026-01-04T00:00:00Z"}],
    )
    repo = RunsRepository(tmp_path)
    doc = json.loads(repo.read_merged_index())
    by_set = {r["run_set"]: r["episode_id"] for r in doc["runs"]}
    assert by_set == {".": "episode_000000", "set_x": "episode_000002"}


def test_merged_index_empty_when_no_indices(tmp_path: Path) -> None:
    repo = RunsRepository(tmp_path)
    doc = json.loads(repo.read_merged_index())
    assert doc == {"schema_version": "0.1.0", "runs": []}


def test_merged_index_ignores_subdir_without_index(tmp_path: Path) -> None:
    (tmp_path / "no_index_here").mkdir()
    (tmp_path / "_vlm_dumps").mkdir()
    _write_index(
        tmp_path / "real_set" / "index.json",
        [{"episode_id": "episode_000000", "run_hash": "sha256:" + "e" * 64,
          "manifest_url": "episode_000000__eee/manifest.json",
          "run_hash_short": "eeeeeeeeeeee", "config_hash_short": "9",
          "input_hash_short": "0", "task_text": "x", "pipeline_phase": 4,
          "generated_at": "2026-01-05T00:00:00Z"}],
    )
    repo = RunsRepository(tmp_path)
    doc = json.loads(repo.read_merged_index())
    assert [r["run_set"] for r in doc["runs"]] == ["real_set"]


def test_merged_index_malformed_subdir_skipped(tmp_path: Path) -> None:
    """A subdir with corrupt index.json is silently skipped."""
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "index.json").write_text("not json{{{")
    _write_index(
        tmp_path / "good" / "index.json",
        [{"episode_id": "episode_000000", "run_hash": "sha256:" + "f" * 64,
          "manifest_url": "episode_000000__fff/manifest.json",
          "run_hash_short": "ffffffffffff", "config_hash_short": "a",
          "input_hash_short": "b", "task_text": "y", "pipeline_phase": 4,
          "generated_at": "2026-01-06T00:00:00Z"}],
    )
    repo = RunsRepository(tmp_path)
    doc = json.loads(repo.read_merged_index())
    assert [r["run_set"] for r in doc["runs"]] == ["good"]
