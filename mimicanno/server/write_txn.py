"""Shared atomic write transaction for run edits (Phase 5 B r2).

Extracted from edit_repo.py so boundary_repo.py can reuse the same
annotation → manifest → index write order without duplicating the logic.

WRITE ORDER: annotation.json → manifest.json → index.json.
Crash between annotation and manifest leaves OLD manifest + NEW annotation;
recovered on next PATCH (old If-Match succeeds, new If-Match 412s).

LOCK: callers must hold ``runs_root / "index.json.lock"`` for the full
reread-validate-mutate-write window before calling this function.
"""
from __future__ import annotations

import logging
from pathlib import Path

from mimicanno.runindex import IndexFile, IndexRow, read_index, write_index_atomic
from mimicanno.schema import AnnotationResult, Manifest
from mimicanno.writers import write_annotation_json, write_manifest_json

_LOG = logging.getLogger("mimicanno.server")


def write_run_atomically(
    *,
    runs_root: Path,
    canonical_name: str,
    annotation: AnnotationResult,
    manifest: Manifest,
    index_row: IndexRow,
    old_run_hash: str,
) -> None:
    """Write annotation, manifest, and index atomically (caller holds lock).

    Drops the stale index row for ``old_run_hash`` and appends ``index_row``.
    """
    run_dir = runs_root / canonical_name
    annotation_path = run_dir / "annotation.json"
    manifest_path = run_dir / "manifest.json"
    idx_path = runs_root / "index.json"

    write_annotation_json(annotation_path, annotation)
    write_manifest_json(manifest_path, manifest)

    index = read_index(idx_path)
    kept = [
        r for r in index.rows
        if not (
            r.episode_id == manifest.episode_id
            and r.run_hash == old_run_hash
        )
    ]
    kept.append(index_row)
    write_index_atomic(idx_path, IndexFile(schema_version=index.schema_version, rows=kept))
