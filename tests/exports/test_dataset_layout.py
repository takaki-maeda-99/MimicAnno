"""Episode-path resolution tests (Phase 5 Task 9, spec §2.3 + §4.4)."""

from __future__ import annotations

import json
from pathlib import Path

from mimicanno.exports.dataset_layout import enumerate_episodes, resolve_episode_path


def _write_info(p: Path, data_path: str, total_episodes: int) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / "info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v3.0",
                "total_episodes": total_episodes,
                "chunks_size": 1000,
                "data_path": data_path,
                "video_path": (
                    "videos/{video_key}/chunk-{chunk_index:03d}/"
                    "episode_{episode_index:06d}.mp4"
                ),
                "fps": 30,
                "splits": {"train": f"0:{total_episodes}"},
                "features": {},
            }
        )
    )


def test_enumerate_episodes_v3(tmp_path: Path) -> None:
    _write_info(
        tmp_path / "meta",
        "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        5,
    )
    eps = enumerate_episodes(tmp_path)
    assert eps == list(range(5))


def test_resolve_episode_path_v3(tmp_path: Path) -> None:
    _write_info(
        tmp_path / "meta",
        "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        5,
    )
    path, row_filter = resolve_episode_path(
        tmp_path, episode_index=2, chunks_size=1000
    )
    assert path == tmp_path / "data/chunk-000/episode_000002.parquet"
    assert row_filter is None


def test_resolve_episode_path_v2_combined_file(tmp_path: Path) -> None:
    # v2 layout: file-NNN.parquet contains multiple episodes; row_filter selects.
    _write_info(
        tmp_path / "meta",
        "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        3,
    )
    path, row_filter = resolve_episode_path(
        tmp_path, episode_index=1, chunks_size=1000
    )
    assert path == tmp_path / "data/chunk-000/file-000.parquet"
    assert row_filter == {"column": "episode_index", "value": 1}
