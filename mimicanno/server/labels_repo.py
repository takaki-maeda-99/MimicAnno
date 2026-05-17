"""Phase 5 B r4 — labels-field edit write transaction (spec §3).

Single public entry point: :func:`patch_labels`.

LOCK CONTRACT: same as edit_repo / boundary_repo / reviewed_repo — acquires
``runs/index.json.lock`` for the full reread-validate-mutate-write window.

WRITE ORDER: annotation.json → manifest.json → index.json (via
:func:`write_run_atomically`).

HASH SPACE: ``"edit:labels:"`` prefix; byte[5] = ``'l'``.
Disjoint from r3 (byte[5]='r'), r2 (byte[5]='b'), r1 (byte[5]=':'),
and auto-pipeline (no ``"edit:"`` prefix).
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
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
from mimicanno.server.edit_repo import EtagMismatch, InvalidSegment, RunNotFound
from mimicanno.server.event_builder import build_edit_event
from mimicanno.server.write_txn import write_run_atomically


_LOG = logging.getLogger("mimicanno.server")
_LOCK_TIMEOUT_SEC: float = 30.0


class LabelsNoChange(Exception):
    """Segment already has the requested label values (all four fields match)."""

    def __init__(self, segment_id: str) -> None:
        super().__init__(f"segment {segment_id!r} already has these label values")
        self.segment_id = segment_id


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")


def derive_labels_run_hash(
    old_run_hash: str,
    segment_id: str,
    verb: str | None,
    object_: str | None,
    target: str | None,
    failure_flags: list[str],
    reviewer: str | None,
) -> str:
    """Derive new run_hash for a labels-field edit (spec §3.5).

    Preimage: ``"edit:labels:" + old_run_hash + ":" + segment_id + ":"
    + (verb or "") + ":" + (object_ or "") + ":" + (target or "") + ":"
    + ",".join(sorted(failure_flags)) + ":" + (reviewer or "")``.

    byte[5] = 'l' — disjoint from r3 ('r'), r2 ('b'), r1 (':'),
    and auto-pipeline (no prefix).
    """
    preimage = (
        "edit:labels:"
        + old_run_hash
        + ":"
        + segment_id
        + ":"
        + (verb or "")
        + ":"
        + (object_ or "")
        + ":"
        + (target or "")
        + ":"
        + ",".join(sorted(failure_flags))
        + ":"
        + (reviewer or "")
    )
    return "sha256:" + sha256_hex_of_str(preimage)


def patch_labels(
    *,
    runs_root: Path,
    name: str,
    segment_id: str,
    verb: str | None,
    object_: str | None,
    target: str | None,
    failure_flags: list[str],
    if_match: str,
    reviewer: str | None,
    client_edit_duration_ms: int | None = None,
) -> dict[str, Any]:
    """Edit verb/object/target/failure_flags on a single segment (spec §2, §3).

    Returns the new manifest as a dict (route layer emits as response body
    + ETag header).

    Raises:
        RunNotFound: 404 — canonical_name directory not found.
        EtagMismatch: 412 — If-Match ≠ current manifest.run_hash.
        InvalidSegment: 400 invalid_segment — segment_id not in annotation.
        LabelsNoChange: 400 no_change — all four fields already equal requested.
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

        # Find target segment.
        idx = next(
            (i for i, s in enumerate(segments) if s.segment_id == segment_id),
            None,
        )
        if idx is None:
            raise InvalidSegment(segment_id=segment_id)

        seg = segments[idx]

        # No-op check: all four fields must differ from at least one current value.
        if (
            seg.verb == verb
            and seg.object == object_
            and seg.target == target
            and list(seg.failure_flags) == list(failure_flags)
        ):
            raise LabelsNoChange(segment_id=segment_id)

        # Mutate: update label fields; set label_source, reviewed, reviewer_id.
        segments[idx] = replace(
            seg,
            verb=verb,
            object=object_,
            target=target,
            failure_flags=list(failure_flags),
            label_source="human_edit",
            reviewed=True,
            reviewer_id=reviewer,
        )

        old_run_hash = manifest.run_hash
        new_run_hash = derive_labels_run_hash(
            old_run_hash, segment_id, verb, object_, target, failure_flags, reviewer
        )

        event = build_edit_event(
            edit_type="labels",
            segment_id=segment_id,
            client_edit_duration_ms=client_edit_duration_ms,
            reviewer=reviewer,
        )
        new_history = [*annotation.history, event]
        new_annotation = replace(
            annotation,
            segments=segments,
            run_hash=new_run_hash,
            history=new_history,
            schema_version=ARTIFACT_SCHEMA_VERSIONS["annotation"],
        )
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
            "edit-labels: %s → %s, segment=%s, verb=%r, object=%r, target=%r, "
            "failure_flags=%r, reviewer=%s",
            old_run_hash, new_run_hash, segment_id, verb, object_, target,
            failure_flags, reviewer,
        )

    return new_manifest.to_dict()
