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
# Phase 5 B r1 — `tmp_runs_root_loadable`
#
# The Phase 5 A `tmp_runs_root` above writes a minimal manifest that lacks
# fields `mimicanno/io.py::read_manifest` requires; sufficient for A's
# bytes-passthrough route tests, but the PATCH writer (T6+) needs to parse
# manifest + annotation contents. This fixture copies a real SO101 v5 run
# (allow-list of 5 artifacts, no video / no _vlm_dumps) and injects
# `canonical_name` since the source predates T4.
# ----------------------------------------------------------------------------


import shutil  # noqa: E402

from mimicanno.schema_versions import INDEX_SCHEMA_VERSION  # noqa: E402

_REAL_SO101_RUN = (
    Path(__file__).resolve().parent.parent.parent
    / "runs" / "so101_phase4_v5" / "episode_000000__e35061106394"
)
_LOADABLE_ARTIFACT_FILES = (
    "annotation.json", "boundaries.json", "signals.json", "tracks.json",
)


def _build_loadable_fixture(dst_runs_root: Path) -> str:
    """Build a loadable runs/ tree under ``dst_runs_root`` from
    ``_REAL_SO101_RUN``. Returns the run dir name."""
    name = _REAL_SO101_RUN.name
    dst_run = dst_runs_root / name
    dst_run.mkdir(parents=True)

    # Allow-list copy: 5 files only. video.mp4 and _vlm_dumps are skipped.
    for fname in _LOADABLE_ARTIFACT_FILES:
        shutil.copy(_REAL_SO101_RUN / fname, dst_run / fname)

    # Manifest: inject canonical_name (source predates T4) + strip video row.
    raw = json.loads((_REAL_SO101_RUN / "manifest.json").read_text())
    raw["canonical_name"] = name
    raw["artifacts"] = [a for a in raw["artifacts"] if a.get("role") != "video"]
    (dst_run / "manifest.json").write_text(json.dumps(raw, indent=2))

    # Single-row index.json (real index has 23 rows; tests only need one).
    rh = str(raw["run_hash"])
    rh_hex = rh[len("sha256:"):] if rh.startswith("sha256:") else rh
    ch = str(raw["config_hash"])
    ch_hex = ch[len("sha256:"):] if ch.startswith("sha256:") else ch
    ih = str(raw["input_hash"])
    ih_hex = ih[len("sha256:"):] if ih.startswith("sha256:") else ih
    suffix_len = len(name) - len("episode_000000__")
    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "runs": [{
            "episode_id": raw["episode_id"],
            "run_hash": rh,
            "run_hash_short": rh_hex[:suffix_len],
            "config_hash_short": ch_hex[:8],
            "input_hash_short": ih_hex[:8],
            "manifest_url": f"{name}/manifest.json",
            "task_text": raw["task"]["text"],
            "pipeline_phase": raw["generator"]["pipeline_phase"],
            "generated_at": raw["generated_at"],
        }],
    }
    (dst_runs_root / "index.json").write_text(json.dumps(index, indent=2))
    return name


@pytest.fixture
def tmp_runs_root_loadable(tmp_path: Path) -> Path:
    """runs/ tree where manifest.json round-trips through ``read_manifest``
    (full schema) and annotation.json carries real SubtaskSegment data —
    for PATCH writer tests that actually parse and mutate the contents.

    Skips test if the real SO101 v5 run isn't checked out locally."""
    if not _REAL_SO101_RUN.is_dir():
        pytest.skip(
            f"loadable fixture source missing: {_REAL_SO101_RUN}; "
            "this dev box only — CI should commit a frozen fixture instead.",
        )
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


@pytest.fixture
def loadable_canonical_name() -> str:
    """The dir name in ``tmp_runs_root_loadable`` (matches real SO101 ep0)."""
    return _REAL_SO101_RUN.name
