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


# ----------------------------------------------------------------------------
# Phase 5 B r1 — `tmp_runs_root_loadable` (frozen fixture)
#
# The Phase 5 A `tmp_runs_root` above writes a minimal manifest that lacks
# fields `mimicanno/io.py::read_manifest` requires; sufficient for A's
# bytes-passthrough route tests, but the PATCH writer (T6+) needs to parse
# manifest + annotation contents. This fixture copies a frozen SO101 v5
# ep0 snapshot from `tests/fixtures/loadable_run/` (committed to the repo)
# so CI does not depend on the live `runs/` tree.
#
# See `docs/superpowers/specs/2026-05-16-loadable-run-fixture-design.md`.
# ----------------------------------------------------------------------------


import shutil  # noqa: E402

_FROZEN_FIXTURE_ROOT = (
    Path(__file__).resolve().parent.parent / "fixtures" / "loadable_run"
)
_FROZEN_RUN_FILES = (
    "manifest.json", "annotation.json", "boundaries.json",
    "signals.json", "tracks.json",
)
_FROZEN_INDEX_FILE = "index.json"
_LOADABLE_RUN_NAME = "episode_000000__e35061106394"


def _build_loadable_fixture(dst_runs_root: Path) -> str:
    """Copy the frozen loadable-run snapshot into ``dst_runs_root``.

    Returns the run dir name (== ``_LOADABLE_RUN_NAME``)."""
    dst_run = dst_runs_root / _LOADABLE_RUN_NAME
    dst_run.mkdir(parents=True)
    for fname in _FROZEN_RUN_FILES:
        shutil.copy(_FROZEN_FIXTURE_ROOT / fname, dst_run / fname)
    shutil.copy(
        _FROZEN_FIXTURE_ROOT / _FROZEN_INDEX_FILE,
        dst_runs_root / _FROZEN_INDEX_FILE,
    )
    return _LOADABLE_RUN_NAME


@pytest.fixture
def tmp_runs_root_loadable(tmp_path: Path) -> Path:
    """runs/ tree where manifest.json round-trips through ``read_manifest``
    (full schema) and annotation.json carries real SubtaskSegment data —
    for PATCH writer tests that actually parse and mutate the contents.

    Always available: backed by a frozen fixture committed to the repo."""
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


@pytest.fixture
def loadable_canonical_name() -> str:
    """The dir name in ``tmp_runs_root_loadable``."""
    return _LOADABLE_RUN_NAME


# ----------------------------------------------------------------------------
# S-RS — `tmp_parent_runs_root`
#
# Parent directory containing 2 run-set subdirectories (multi-mode).
# Used by run-set switcher tests (T2+).
# ----------------------------------------------------------------------------

@pytest.fixture
def tmp_parent_runs_root(tmp_path: Path) -> Path:
    """Parent dir with 2 run-set subdirectories — multi-mode fixture for S-RS."""
    for name in ("so101_phase4_v5", "piper_phase4_v5"):
        sub = tmp_path / name
        sub.mkdir()
        (sub / "index.json").write_bytes(b'{"schema_version":"0.1.0","runs":[]}')
    return tmp_path


@pytest.fixture
def tmp_parent_runs_root_loadable(tmp_path: Path) -> Path:
    """Multi-mode parent dir with a frozen loadable so101 run-set subdirectory.

    Used for S-RS T5: PATCH with ?run_set= integration test.
    """
    sub = tmp_path / "so101_phase4_v5"
    sub.mkdir()
    _build_loadable_fixture(sub)
    return tmp_path


@pytest.fixture
def loadable_run_set_name() -> str:
    """The run-set subdirectory name in ``tmp_parent_runs_root_loadable``."""
    return "so101_phase4_v5"
