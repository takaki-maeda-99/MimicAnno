"""Phase 5 B r1 — PATCH write transaction (spec 2026-05-13 §3.2).

Pure-Python, no FastAPI imports. The HTTP layer in routes.py translates
:class:`EditError` subclasses into the spec §3.6 envelope.

Single public entry point: :func:`apply_edit`.

LOCK CONTRACT: ``apply_edit`` acquires ``runs/index.json.lock`` for the
full reread-validate-mutate-write window (spec §3.2 step 1). Concurrent
PATCHes serialise; concurrent ``mimicanno annotate`` publishes serialise
via the same lock at their final publish step.

WRITE ORDER: annotation.json → manifest.json → index.json (spec §3.2
step 6). Crash between annotation and manifest leaves "OLD manifest
(old run_hash) + NEW annotation" — recovered on next PATCH (with old
If-Match it succeeds, with new If-Match it 412s).

HASH INVARIANT: ``new_run_hash`` is derived from a SHA-256 over a
literal ``"edit:"`` prefix + the prior run_hash + segment/phase/reviewer
inputs. The input space is disjoint from the auto-pipeline's
``compose_run_hash(config_hash, input_hash)`` (config.py:835), so the
publish reuse short-circuit cannot mistakenly skip publish on an edited
run.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from mimicanno.hashing import sha256_hex_of_str
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.labelset import LabelSet
from mimicanno.locks import file_lock
from mimicanno.rundir import CANONICAL_SEPARATOR
from mimicanno.runindex import IndexRow
from mimicanno.smoother import _recompute_confidence
from mimicanno.server.event_builder import build_edit_event
from mimicanno.server.write_txn import write_run_atomically


_LOG = logging.getLogger("mimicanno.server")


_LOCK_TIMEOUT_SEC: float = 30.0


def _now_iso() -> str:
    """ISO-8601 UTC with ``Z`` suffix, matching ``Manifest.generated_at``."""
    return dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")


# ----------------------------------------------------------------------------
# Exceptions — 1:1 with spec §3.6 codes (HTTP-only errors like 415/428
# live in routes.py, not here).
# ----------------------------------------------------------------------------


class EditError(Exception):
    """Base. Routes.py translates subclasses into the §3.6 envelope."""


class RunNotFound(EditError):
    """404 run_not_found — the canonical_name has no dir under runs_root."""

    def __init__(self, *, name: str) -> None:
        super().__init__(f"run not found: {name}")
        self.name = name


class EtagMismatch(EditError):
    """412 etag_mismatch — If-Match ≠ current manifest.run_hash.

    Carries both sides so the HTTP layer (T8) can log the divergence
    without leaking it in the response envelope. Comparison is strict
    `==` per RFC 7232; case sensitivity and prefix shape are NOT
    normalised here (case is locked lowercase by the manifest schema
    regex `^sha256:[0-9a-f]{64}$`).
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        super().__init__(
            f"etag mismatch: expected={expected!r}, actual={actual!r}",
        )
        self.expected = expected
        self.actual = actual


class InvalidLabel(EditError):
    """400 invalid_label — new_phase is not in the run's labelset.

    Carries the rejected label + the allowed set so the HTTP layer (T8)
    can log it. The response envelope MUST NOT echo the full allowed
    set back (the client already fetched it via GET /api/labelset).
    """

    def __init__(self, *, label: str, allowed: set[str]) -> None:
        super().__init__(f"invalid label: {label!r} not in labelset")
        self.label = label
        self.allowed = frozenset(allowed)


class InvalidSegment(EditError):
    """400 invalid_segment — segment_id not found in annotation.segments."""

    def __init__(self, *, segment_id: str) -> None:
        super().__init__(f"invalid segment: {segment_id!r}")
        self.segment_id = segment_id


# Remaining T6 sub-steps add: smoothing_ops dedup + _recompute_confidence (T6e),
# cross-file consistency (T6f), edited_at + canonical_name (T6g), reviewer hash
# pinning (T6h), index upsert (T6i), non-target preservation (T6j).


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def apply_edit(
    *,
    runs_root: Path,
    name: str,
    segment_id: str,
    new_phase: str,
    if_match: str,
    reviewer: str | None,
    labelset: LabelSet,
    client_edit_duration_ms: int | None = None,
) -> dict[str, Any]:
    """Apply a single-field phase relabel under the publish lock.

    Returns the new manifest as a dict (route layer emits as response
    body + ETag header).
    """
    run_dir = runs_root / name

    with file_lock(runs_root / "index.json.lock", timeout_sec=_LOCK_TIMEOUT_SEC):
        # Step 1.5 (T6b): check existence inside the lock so the publish
        # dir-gap window (publish.py:149-165) doesn't false-positive.
        if not run_dir.is_dir():
            raise RunNotFound(name=name)

        manifest_path = run_dir / "manifest.json"
        annotation_path = run_dir / "annotation.json"

        # Step 2 (spec §3.2): reread inside the lock.
        manifest = read_manifest(manifest_path)

        # Step 3 (T6c): If-Match precondition — strict `==`, no normalisation.
        if manifest.run_hash != if_match:
            raise EtagMismatch(expected=if_match, actual=manifest.run_hash)

        annotation = read_annotation_result(annotation_path)

        # Step 4a (T6d): label set membership. Cheap to fail before
        # walking segments.
        allowed = labelset.label_ids()
        if new_phase not in allowed:
            raise InvalidLabel(label=new_phase, allowed=allowed)

        # Step 4b (T6d): find target segment, raise InvalidSegment if
        # absent (replaces the T6a bare ``next(...)`` whose StopIteration
        # could leak through to the HTTP layer as a 500).
        idx = next(
            (i for i, s in enumerate(annotation.segments) if s.segment_id == segment_id),
            None,
        )
        if idx is None:
            raise InvalidSegment(segment_id=segment_id)

        # Step 5: derive new_run_hash (deterministic, disjoint from auto).
        old_run_hash = manifest.run_hash
        reviewer_norm = reviewer or ""
        new_run_hash = "sha256:" + sha256_hex_of_str(
            "edit:" + old_run_hash + ":" + segment_id +
            ":" + new_phase + ":" + reviewer_norm,
        )

        # Step 4c (T6e): mutate the target segment per spec §3.2 step 4.
        old_seg = annotation.segments[idx]
        new_ops = list(old_seg.smoothing_ops)
        if not new_ops or new_ops[-1] != "edited":
            new_ops.append("edited")
        new_seg = replace(
            old_seg,
            phase=new_phase,
            smoothing_ops=new_ops,
            reviewed=True,
            reviewer_id=reviewer,
        )
        # boundary_confidence is recomputed from start/end boundary scores;
        # overall_confidence depends on (boundary, vlm_confidence) and on
        # reserved-phase membership — for r1 the phase is always in the
        # labelset (T6d guard) so the formula reduces to sqrt(bc * vlm).
        new_seg = _recompute_confidence(new_seg)
        annotation.segments[idx] = new_seg

        # Step 6-8: write annotation → manifest → index atomically.
        event = build_edit_event(
            edit_type="relabel",
            segment_id=segment_id,
            client_edit_duration_ms=client_edit_duration_ms,
            reviewer=reviewer,
        )
        new_history = [*annotation.history, event]
        annotation = replace(annotation, run_hash=new_run_hash, history=new_history)
        manifest = replace(
            manifest,
            run_hash=new_run_hash,
            edited_at=_now_iso(),
        )

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
            annotation=annotation,
            manifest=manifest,
            index_row=new_row,
            old_run_hash=old_run_hash,
        )
        _LOG.info(
            "edit: %s → %s, segment=%s, phase=%s, reviewer=%s",
            old_run_hash, new_run_hash, segment_id, new_phase, reviewer,
        )

    return manifest.to_dict()
