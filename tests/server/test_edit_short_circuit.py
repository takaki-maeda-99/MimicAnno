"""Phase 5 B r1 T10b: post-edit run_hash disjointness from auto-pipeline
(spec §5.1 #16 + §7 risk).

Pure-Python invariant: edits prefix the SHA-256 input with the literal
``"edit:"`` so the edit-derived hash set is disjoint from the
auto-pipeline's ``compose_run_hash(config_hash, input_hash)`` set.

Implication: ``mimicanno publish.py``'s two reuse short-circuits —
the lock-free check at publish.py:99-102 and the locked re-check at
publish.py:134-139 — both compare ``_existing_run_hash(paths.final) ==
req.run_hash``. With ``req.run_hash`` coming from the auto-pipeline,
neither can match an edit-derived hash on disk. Therefore a subsequent
``mimicanno annotate`` cannot short-circuit on an edited run and would
re-publish, overwriting the edit (documented as expected behaviour in
spec §7).

This test does NOT spawn Gemma / SAM3; it bypasses the HTTP layer and
exercises ``edit_repo.apply_edit`` + ``publish._existing_run_hash`` +
``config.compose_run_hash`` directly.
"""
from __future__ import annotations

from pathlib import Path

from mimicanno.config import compose_run_hash
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.labelset import default_labels_path, load_label_set
from mimicanno.publish import _existing_run_hash
from mimicanno.server.edit_repo import apply_edit


def test_edited_run_hash_disjoint_from_auto_pipeline_hash(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """The post-edit on-disk run_hash is disjoint from
    compose_run_hash(config_hash, input_hash). Covers both publish.py
    short-circuit sites (lock-free + locked re-check) since they use
    the same comparison operands.
    """
    run_dir = tmp_runs_root_loadable / loadable_canonical_name

    # Fixture invariant: the on-disk manifest was produced by the
    # auto-pipeline, so its run_hash equals compose_run_hash of its
    # (config_hash, input_hash).
    pre = read_manifest(run_dir / "manifest.json")
    auto_hash = compose_run_hash(pre.config_hash, pre.input_hash)
    on_disk = _existing_run_hash(run_dir)
    assert on_disk == auto_hash, (
        "fixture invariant: pre-PATCH disk hash must equal compose_run_hash "
        "of (config_hash, input_hash)"
    )
    assert on_disk == pre.run_hash

    # PATCH directly via edit_repo (no HTTP, no Gemma).
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    apply_edit(
        runs_root=tmp_runs_root_loadable,
        name=loadable_canonical_name,
        segment_id=seg_id,
        new_phase="idle",
        if_match=auto_hash,
        reviewer="alice",
        labelset=load_label_set(default_labels_path()),
    )

    # Post-edit: on-disk hash is edit-derived, MUST NOT equal the
    # auto-pipeline hash for the same (config, input).
    edited_on_disk = _existing_run_hash(run_dir)
    assert edited_on_disk is not None
    assert edited_on_disk.startswith("sha256:")
    assert edited_on_disk != auto_hash

    # Re-deriving compose_run_hash with the same inputs still yields
    # auto_hash (deterministic), so a future `mimicanno annotate`
    # constructing req.run_hash = compose_run_hash(...) would compare
    # edited_on_disk != auto_hash → short-circuit cannot fire →
    # annotate re-publishes (= overwrites the edit).
    auto_hash_again = compose_run_hash(pre.config_hash, pre.input_hash)
    assert auto_hash_again == auto_hash
    assert edited_on_disk != auto_hash_again


def test_edit_hash_input_is_edit_prefixed(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Companion to the disjointness test: ensure the edit-derived
    hash IS reproducible from the spec's formula. Together with the
    disjointness test, this means any third party reading
    annotation.run_hash can identify it as edit- vs auto-derived by
    re-computing the formula and matching."""
    from mimicanno.hashing import sha256_hex_of_str

    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre = read_manifest(run_dir / "manifest.json")
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    new_phase = "idle"
    reviewer = "alice"

    result = apply_edit(
        runs_root=tmp_runs_root_loadable,
        name=loadable_canonical_name,
        segment_id=seg_id,
        new_phase=new_phase,
        if_match=pre.run_hash,
        reviewer=reviewer,
        labelset=load_label_set(default_labels_path()),
    )

    expected = "sha256:" + sha256_hex_of_str(
        "edit:" + pre.run_hash + ":" + seg_id + ":" + new_phase
        + ":" + reviewer,
    )
    assert result["run_hash"] == expected
