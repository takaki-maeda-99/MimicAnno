"""Phase 5 B r2 — boundary drag write transaction (spec §3).

Single public entry point: :func:`patch_boundary`.

LOCK CONTRACT: same as edit_repo — acquires ``runs/index.json.lock`` for the
full reread-validate-mutate-write window (spec §3.2 step 1).

WRITE ORDER: annotation.json → manifest.json → index.json (inherited from
write_txn.write_run_atomically).

HASH SPACE: ``"edit:boundary:"`` prefix at byte 5 is disjoint from r1's
``"edit:"`` (byte 5 = ``'s'``) and auto-pipeline's binary concat (no
``"edit:"`` prefix). See spec §3.5.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from mimicanno.hashing import sha256_hex_of_str
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.locks import file_lock
from mimicanno.rundir import CANONICAL_SEPARATOR
from mimicanno.runindex import IndexRow
from mimicanno.schema import BoundaryRef
from mimicanno.smoother import _dedup_consecutive, _recompute_confidence
from mimicanno.server.boundary_lookup import (
    BoundaryIsTimelineEdge,
    BoundaryNotFound,
    InvalidFrame,
    derive_n_frames,
    resolve_boundary,
    validate_new_frame,
)
from mimicanno.server.edit_repo import EtagMismatch, RunNotFound
from mimicanno.server.write_txn import write_run_atomically


_LOG = logging.getLogger("mimicanno.server")
_LOCK_TIMEOUT_SEC: float = 30.0


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")


def derive_boundary_run_hash(
    old_run_hash: str,
    boundary_id: str,
    new_frame: int,
    reviewer: str | None,
) -> str:
    """Derive new run_hash for a boundary drag edit (spec §3.5).

    Preimage: ``"edit:boundary:" + old_run_hash + ":" + boundary_id + ":"
    + str(new_frame) + ":" + (reviewer or "")``.

    Disjoint from r1 (byte[5]='s') and auto-pipeline (no "edit:" prefix).
    """
    preimage = (
        "edit:boundary:"
        + old_run_hash
        + ":"
        + boundary_id
        + ":"
        + str(new_frame)
        + ":"
        + (reviewer or "")
    )
    return "sha256:" + sha256_hex_of_str(preimage)


def patch_boundary(
    *,
    runs_root: Path,
    name: str,
    boundary_id: str,
    new_frame: int,
    if_match: str,
    reviewer: str | None,
) -> dict[str, Any]:
    """Move a shared segment boundary to new_frame (spec §2, §3).

    Returns the new manifest as a dict (route layer emits as response body
    + ETag header).

    Raises:
        RunNotFound: 404 — canonical_name directory not found.
        EtagMismatch: 412 — If-Match ≠ current manifest.run_hash.
        BoundaryIsTimelineEdge: 400 invalid_boundary — boundary_id is
            segments[0] (no left neighbour).
        BoundaryNotFound: 400 invalid_boundary — boundary_id not in segments.
        InvalidFrame: 400 invalid_frame — new_frame violates §3.3 invariants.
    """
    run_dir = runs_root / name

    with file_lock(runs_root / "index.json.lock", timeout_sec=_LOCK_TIMEOUT_SEC):
        if not run_dir.is_dir():
            raise RunNotFound(name=name)

        manifest_path = run_dir / "manifest.json"
        annotation_path = run_dir / "annotation.json"

        manifest = read_manifest(manifest_path)

        if manifest.run_hash != if_match:
            raise EtagMismatch(expected=if_match, actual=manifest.run_hash)

        annotation = read_annotation_result(annotation_path)
        segments = list(annotation.segments)

        # Resolve boundary and validate new_frame.
        left_idx, right_idx = resolve_boundary(segments, boundary_id)
        left = segments[left_idx]
        right = segments[right_idx]
        n_frames = derive_n_frames(segments)
        validate_new_frame(left, right, new_frame, n_frames)

        # Mutate both segments (spec §3.4).
        fps: float = manifest.fps
        new_end_time = (new_frame - 1) / fps
        new_start_time = new_frame / fps

        left_edited = replace(
            left,
            end_frame=new_frame - 1,
            end_time=new_end_time,
            end_boundary=BoundaryRef(
                candidate_id=None,
                time=new_end_time,
                sources=["human_edit"],
                score=1.0,
            ),
            smoothing_ops=_dedup_consecutive(list(left.smoothing_ops) + ["edited"]),
            reviewed=True,
            reviewer_id=reviewer,
        )
        right_edited = replace(
            right,
            start_frame=new_frame,
            start_time=new_start_time,
            start_boundary=BoundaryRef(
                candidate_id=None,
                time=new_start_time,
                sources=["human_edit"],
                score=1.0,
            ),
            smoothing_ops=_dedup_consecutive(list(right.smoothing_ops) + ["edited"]),
            reviewed=True,
            reviewer_id=reviewer,
        )
        segments[left_idx] = _recompute_confidence(left_edited)
        segments[right_idx] = _recompute_confidence(right_edited)

        old_run_hash = manifest.run_hash
        new_run_hash = derive_boundary_run_hash(
            old_run_hash, boundary_id, new_frame, reviewer
        )

        new_annotation = replace(annotation, segments=segments, run_hash=new_run_hash)
        new_manifest = replace(manifest, run_hash=new_run_hash, edited_at=_now_iso())

        suffix_len = len(name) - len(manifest.episode_id) - len(CANONICAL_SEPARATOR)
        new_row = IndexRow(
            episode_id=manifest.episode_id,
            run_hash=new_run_hash,
            run_hash_short=new_run_hash[len("sha256:"):][:suffix_len],
            config_hash_short=manifest.config_hash[len("sha256:"):][:8],
            input_hash_short=manifest.input_hash[len("sha256:"):][:8],
            manifest_url=f"{name}/manifest.json",
            task_text=manifest.task.text,
            pipeline_phase=manifest.generator.pipeline_phase,
            generated_at=manifest.generated_at,
        )

        write_run_atomically(
            runs_root=runs_root,
            canonical_name=name,
            annotation=new_annotation,
            manifest=new_manifest,
            index_row=new_row,
            old_run_hash=old_run_hash,
        )
        _LOG.info(
            "edit-boundary: %s → %s, boundary=%s, frame=%d, reviewer=%s",
            old_run_hash, new_run_hash, boundary_id, new_frame, reviewer,
        )

    return new_manifest.to_dict()
