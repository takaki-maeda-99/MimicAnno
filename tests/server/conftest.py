"""Phase 5 A — shared fixtures for server tests (plan T2.5).

Provides a minimal but realistic ``runs/`` tree mirroring the on-disk shape
produced by ``mimicanno annotate`` (see real example at
``runs/so101_phase4_v5/episode_000000__*``), plus helpers for spinning up
the FastAPI app and picking a free TCP port.
"""
from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest


CANONICAL_NAME = "episode_000000__abc123def456"
RUN_HASH = "sha256:abc123def456" + "0" * 52  # 64-hex like real
EPISODE_ID = "episode_000000"
ARTIFACT_FILES = (
    "annotation.json", "boundaries.json", "signals.json", "tracks.json",
)


def _write_manifest(run_dir: Path) -> None:
    manifest = {
        "schema_version": "0.2.0",
        "run_hash": RUN_HASH,
        "episode_id": EPISODE_ID,
        "config_hash": "sha256:de448f5d5d7c43416a1037f248c2164c9070244993d448f23048804f0054de6d",
        "input_hash": "sha256:" + "f" * 64,
        "generated_at": "2026-05-12T22:00:00.000Z",
        "generator": {"name": "mimicanno", "cli_version": "0.1.0", "pipeline_phase": 4},
        "artifacts": [
            {"role": "annotation", "url": "annotation.json",
             "content_type": "application/json"},
            {"role": "boundaries", "url": "boundaries.json",
             "content_type": "application/json"},
            {"role": "signals", "url": "signals.json",
             "content_type": "application/json"},
            {"role": "tracks", "url": "tracks.json",
             "content_type": "application/json"},
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


@pytest.fixture
def tmp_runs_root(tmp_path: Path) -> Path:
    """Build a runs/ tree with one populated run dir + index.json.

    Returns the runs root path. Each artifact file holds a small JSON
    payload so byte-level read tests have something deterministic to
    compare against.
    """
    root = tmp_path / "runs"
    root.mkdir()
    run_dir = root / CANONICAL_NAME
    run_dir.mkdir()
    _write_manifest(run_dir)
    for fname in ARTIFACT_FILES:
        (run_dir / fname).write_text(json.dumps({"file": fname}))

    index = {
        "schema_version": "0.1.0",
        "runs": [
            {
                "canonical_name": CANONICAL_NAME,
                "episode_id": EPISODE_ID,
                "run_hash": RUN_HASH,
                "run_hash_short": "abc123def456",
                "config_hash_short": "de448f5d",
                "input_hash_short": "ffffffff",
                "generated_at": "2026-05-12T22:00:00.000Z",
                "manifest_url": f"{CANONICAL_NAME}/manifest.json",
                "pipeline_phase": 4,
                "task_text": "Put the tape into the bottle",
            },
        ],
    }
    (root / "index.json").write_text(json.dumps(index, indent=2))
    return root


@pytest.fixture
def empty_runs_root(tmp_path: Path) -> Path:
    """runs/ with only an empty index.json — for the 'no runs yet' case."""
    root = tmp_path / "runs_empty"
    root.mkdir()
    (root / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0", "runs": [],
    }))
    return root


@pytest.fixture
def runs_root_no_index(tmp_path: Path) -> Path:
    """runs/ with no index.json — for the 404 ``index_missing`` case."""
    root = tmp_path / "runs_noindex"
    root.mkdir()
    return root


@pytest.fixture
def free_port() -> int:
    """Ask the OS for a port that is currently free and return it.

    Avoids hardcoded 8000 collisions in CI / multi-test runs. The socket
    is closed before the fixture returns so the caller can bind it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def canonical_name() -> str:
    """The known canonical_name in ``tmp_runs_root``."""
    return CANONICAL_NAME


@pytest.fixture
def known_run_hash() -> str:
    """The known run_hash in ``tmp_runs_root``."""
    return RUN_HASH
