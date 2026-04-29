"""Public I/O helpers for MimicAnno artifacts.

Exposes:
- ``write_json_atomic`` — primitive atomic JSON write (writers.py re-exports this)
- ``write_tracks_json`` / ``read_tracks_json`` — Phase 3 tracks.json I/O (spec §3)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mimicanno.errors import ArtifactIntegrityError
from mimicanno.schema import TracksFile


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write *payload* as JSON to *path* via tmp-file replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def write_tracks_json(path: Path, tracks: TracksFile) -> None:
    """Serialize and atomically write a ``tracks.json`` artifact (spec §3)."""
    write_json_atomic(path, tracks.to_dict())


def read_tracks_json(
    path: Path,
    *,
    expected: tuple[str, float, int] | None = None,
) -> TracksFile:
    """Read and validate a ``tracks.json`` artifact (spec §3).

    Parameters
    ----------
    path:
        Filesystem path to ``tracks.json``.
    expected:
        Optional ``(episode_id, fps, n_frames)`` tuple taken from ``manifest.json``.
        When provided, the values are compared against the file and
        ``ArtifactIntegrityError`` is raised on any mismatch (spec §3.3).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    tf = TracksFile.from_dict(raw)

    if expected is not None:
        exp_episode_id, exp_fps, exp_n_frames = expected
        if tf.episode_id != exp_episode_id:
            raise ArtifactIntegrityError("episode_id", exp_episode_id, tf.episode_id)
        if tf.fps != exp_fps:
            raise ArtifactIntegrityError("fps", exp_fps, tf.fps)
        if tf.n_frames != exp_n_frames:
            raise ArtifactIntegrityError("n_frames", exp_n_frames, tf.n_frames)

    return tf
