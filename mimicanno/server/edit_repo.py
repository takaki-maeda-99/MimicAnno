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

from dataclasses import replace
from pathlib import Path
from typing import Any

from mimicanno.hashing import sha256_hex_of_str
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.labelset import LabelSet
from mimicanno.locks import file_lock
from mimicanno.writers import write_annotation_json, write_manifest_json


_LOCK_TIMEOUT_SEC: float = 30.0


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


# More subclasses get filled in by subsequent T6 sub-steps
# (T6d InvalidLabel/InvalidSegment, ...).


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

        # T6d will add: labelset / segment_id validation.

        # Find target segment (T6d will replace with InvalidSegment guard).
        idx = next(
            i for i, s in enumerate(annotation.segments)
            if s.segment_id == segment_id
        )

        # Step 5: derive new_run_hash (deterministic, disjoint from auto).
        reviewer_norm = reviewer or ""
        new_run_hash = "sha256:" + sha256_hex_of_str(
            "edit:" + manifest.run_hash + ":" + segment_id +
            ":" + new_phase + ":" + reviewer_norm,
        )

        # Mutate segment (T6e will add smoothing_ops dedup +
        # _recompute_confidence + reviewed/reviewer_id).
        annotation.segments[idx] = replace(annotation.segments[idx], phase=new_phase)

        # Step 5b: annotation.run_hash ← new (cross-file consistency).
        annotation = replace(annotation, run_hash=new_run_hash)

        # Step 6: annotation FIRST, manifest SECOND.
        write_annotation_json(annotation_path, annotation)
        manifest = replace(manifest, run_hash=new_run_hash)
        write_manifest_json(manifest_path, manifest)

        # T6g will add: manifest.edited_at = now_iso()
        # T6i will add: runs/index.json upsert

    return manifest.to_dict()
