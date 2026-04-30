"""Resolve LeRobot-style ``data/<chunk>/episode_NNNNNN.parquet`` paths.

Phase 5, Task 9 — reads the dataset's ``meta/info.json`` and resolves an
``episode_index`` to the parquet file path that contains it. Supports two
layouts:

- **v3** (default): ``data_path == "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet"``.
  Each parquet holds exactly one episode. ``row_filter`` is ``None``.
- **v2**: ``data_path == "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"``.
  Multiple episodes per parquet; the caller must filter by
  ``episode_index`` column. We return that filter spec as a dict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _DatasetInfo:
    data_path: str
    total_episodes: int
    chunks_size: int


def _read_info(dataset_root: Path) -> _DatasetInfo:
    info_path = dataset_root / "meta" / "info.json"
    raw = json.loads(info_path.read_text(encoding="utf-8"))
    return _DatasetInfo(
        data_path=str(raw["data_path"]),
        total_episodes=int(raw["total_episodes"]),
        chunks_size=int(raw["chunks_size"]),
    )


def enumerate_episodes(dataset_root: Path) -> list[int]:
    """Return ``[0, 1, ..., total_episodes - 1]`` per ``meta/info.json``."""
    info = _read_info(dataset_root)
    return list(range(info.total_episodes))


def resolve_episode_path(
    dataset_root: Path,
    *,
    episode_index: int,
    chunks_size: int | None = None,
) -> tuple[Path, dict[str, Any] | None]:
    """Resolve the parquet path for ``episode_index``.

    Returns ``(path, row_filter)``:

    - ``path``: absolute parquet file path under ``dataset_root``.
    - ``row_filter``: ``None`` for v3 (one episode per file). For v2
      (file-based chunks containing multiple episodes), a dict
      ``{"column": "episode_index", "value": episode_index}`` indicating the
      caller must filter rows post-load.

    ``chunks_size`` defaults to the value in ``meta/info.json``.
    """
    info = _read_info(dataset_root)
    size = chunks_size if chunks_size is not None else info.chunks_size
    chunk_index = episode_index // size

    template = info.data_path
    if "{file_index:" in template:
        # v2 layout: each chunk file holds multiple episodes.
        file_index = chunk_index
        rel = template.format(chunk_index=chunk_index, file_index=file_index)
        return dataset_root / rel, {
            "column": "episode_index",
            "value": episode_index,
        }
    rel = template.format(
        chunk_index=chunk_index, episode_index=episode_index
    )
    return dataset_root / rel, None
