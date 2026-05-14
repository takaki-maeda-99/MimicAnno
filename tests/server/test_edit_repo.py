"""Phase 5 B r1 T6: edit_repo.apply_edit unit tests.

Pure-Python contract — no FastAPI, no HTTP. The route layer in T8 will
translate EditError subclasses into the spec §3.6 envelope.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.labelset import default_labels_path, load_label_set


def _labelset():
    return load_label_set(default_labels_path())


def test_apply_edit_happy_path(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Single relabel: returns updated manifest dict + writes new phase
    to annotation on disk + new run_hash propagated to both files."""
    from mimicanno.server.edit_repo import apply_edit

    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    old_manifest = read_manifest(run_dir / "manifest.json")
    old_ann = read_annotation_result(run_dir / "annotation.json")
    seg0 = old_ann.segments[0]
    new_phase = "idle" if seg0.phase != "idle" else "approach_object"

    result = apply_edit(
        runs_root=tmp_runs_root_loadable,
        name=loadable_canonical_name,
        segment_id=seg0.segment_id,
        new_phase=new_phase,
        if_match=old_manifest.run_hash,
        reviewer="takaki",
        labelset=_labelset(),
    )

    # Return value is the new manifest as a dict
    assert isinstance(result, dict)
    assert result["run_hash"] != old_manifest.run_hash
    assert result["run_hash"].startswith("sha256:")

    # Disk updated: annotation.json carries the new phase + new run_hash
    new_ann = read_annotation_result(run_dir / "annotation.json")
    assert new_ann.segments[0].phase == new_phase
    assert new_ann.run_hash == result["run_hash"]

    # Disk updated: manifest.json carries the new run_hash
    new_manifest = read_manifest(run_dir / "manifest.json")
    assert new_manifest.run_hash == result["run_hash"]

    # T6e — segment mutation fields
    assert new_ann.segments[0].smoothing_ops[-1] == "edited"
    assert new_ann.segments[0].reviewed is True
    assert new_ann.segments[0].reviewer_id == "takaki"


def test_apply_edit_smoothing_ops_dedup(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6e: editing twice in a row leaves smoothing_ops ending with
    exactly one 'edited' marker (no double append)."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id

    rh1 = read_manifest(run_dir / "manifest.json").run_hash
    r1 = apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh1,
        reviewer="alice", labelset=_labelset(),
    )
    rh2 = r1["run_hash"]
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="approach_object", if_match=rh2,
        reviewer="bob", labelset=_labelset(),
    )
    final_ops = read_annotation_result(run_dir / "annotation.json").segments[0].smoothing_ops
    assert final_ops[-1] == "edited"
    assert final_ops.count("edited") == 1


def test_apply_edit_reviewer_none_keeps_reviewer_id_none(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6e: reviewer=None → segment.reviewer_id is None (not '', not 'None')."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    rh = read_manifest(run_dir / "manifest.json").run_hash
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh,
        reviewer=None, labelset=_labelset(),
    )
    seg = read_annotation_result(run_dir / "annotation.json").segments[0]
    assert seg.reviewer_id is None
    assert seg.reviewed is True


def test_apply_edit_recomputes_confidence(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6e: _recompute_confidence runs on the new segment so
    boundary_confidence matches min(start_boundary.score, end_boundary.score)."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg0 = read_annotation_result(run_dir / "annotation.json").segments[0]
    rh = read_manifest(run_dir / "manifest.json").run_hash
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg0.segment_id, new_phase="idle", if_match=rh,
        reviewer=None, labelset=_labelset(),
    )
    new_seg = read_annotation_result(run_dir / "annotation.json").segments[0]
    assert new_seg.boundary_confidence == min(
        new_seg.start_boundary.score, new_seg.end_boundary.score,
    )


@pytest.mark.parametrize("stale_etag", [
    "sha256:" + "0" * 64,                    # complete stale
    "sha256:" + "0" * 63 + "X",              # right shape, hex-only violation
    "SHA256:" + "0" * 64,                    # case-sensitive contract
    "md5:" + "a" * 32,                       # wrong prefix
    "",                                      # empty (HTTP layer responsibility,
                                              # but defensive check here too)
])
def test_apply_edit_stale_etag_raises_and_disk_untouched(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    stale_etag: str,
) -> None:
    """Spec §5.1 #3 + T6c: If-Match ≠ current manifest.run_hash → 412
    EtagMismatch, no disk writes, cross-file annotation.run_hash
    invariant preserved.

    Note: index.json.lock is created/touched by file_lock(a+ open),
    so it is NOT in the byte-identical assertion set."""
    from mimicanno.server.edit_repo import EtagMismatch, apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    ann_path = run_dir / "annotation.json"
    mani_path = run_dir / "manifest.json"
    index_path = tmp_runs_root_loadable / "index.json"
    pre_ann = ann_path.read_bytes()
    pre_mani = mani_path.read_bytes()
    pre_index = index_path.read_bytes()
    pre_ann_run_hash = read_annotation_result(ann_path).run_hash
    real_run_hash = read_manifest(mani_path).run_hash
    seg_id = read_annotation_result(ann_path).segments[0].segment_id

    with pytest.raises(EtagMismatch) as ei:
        apply_edit(
            runs_root=tmp_runs_root_loadable,
            name=loadable_canonical_name,
            segment_id=seg_id,
            new_phase="idle",
            if_match=stale_etag,
            reviewer=None,
            labelset=_labelset(),
        )
    assert ei.value.expected == stale_etag
    assert ei.value.actual == real_run_hash
    assert ann_path.read_bytes() == pre_ann
    assert mani_path.read_bytes() == pre_mani
    assert index_path.read_bytes() == pre_index
    # Cross-file consistency: annotation.run_hash unchanged.
    assert read_annotation_result(ann_path).run_hash == pre_ann_run_hash


@pytest.mark.parametrize("bad_phase", [
    "not_a_real_phase",
    "",
    "approach object",   # space
    "approach-object",   # hyphen (real label uses underscore)
])
def test_apply_edit_invalid_label_raises(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    bad_phase: str,
) -> None:
    """T6d: ``new_phase`` not in labelset → InvalidLabel (spec §3.6 → 400).
    Disk untouched."""
    from mimicanno.server.edit_repo import InvalidLabel, apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    ann_path = run_dir / "annotation.json"
    mani_path = run_dir / "manifest.json"
    pre_ann = ann_path.read_bytes()
    pre_mani = mani_path.read_bytes()
    seg_id = read_annotation_result(ann_path).segments[0].segment_id
    real_run_hash = read_manifest(mani_path).run_hash

    with pytest.raises(InvalidLabel) as ei:
        apply_edit(
            runs_root=tmp_runs_root_loadable,
            name=loadable_canonical_name,
            segment_id=seg_id,
            new_phase=bad_phase,
            if_match=real_run_hash,
            reviewer=None,
            labelset=_labelset(),
        )
    assert ei.value.label == bad_phase
    assert "approach_object" in ei.value.allowed
    # Disk untouched.
    assert ann_path.read_bytes() == pre_ann
    assert mani_path.read_bytes() == pre_mani


def test_apply_edit_invalid_segment_raises(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6d: unknown ``segment_id`` → InvalidSegment (spec §3.6 → 400).
    Disk untouched."""
    from mimicanno.server.edit_repo import InvalidSegment, apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    ann_path = run_dir / "annotation.json"
    mani_path = run_dir / "manifest.json"
    pre_ann = ann_path.read_bytes()
    pre_mani = mani_path.read_bytes()
    real_run_hash = read_manifest(mani_path).run_hash

    with pytest.raises(InvalidSegment) as ei:
        apply_edit(
            runs_root=tmp_runs_root_loadable,
            name=loadable_canonical_name,
            segment_id="does_not_exist__seg9999",
            new_phase="idle",
            if_match=real_run_hash,
            reviewer=None,
            labelset=_labelset(),
        )
    assert ei.value.segment_id == "does_not_exist__seg9999"
    # Disk untouched.
    assert ann_path.read_bytes() == pre_ann
    assert mani_path.read_bytes() == pre_mani


def test_apply_edit_run_not_found_raises(
    tmp_runs_root_loadable: Path,
) -> None:
    """Missing run dir → RunNotFound (spec §3.6 → 404 run_not_found).
    Checked inside the lock so the publish dir-gap window doesn't
    false-positive (T6b)."""
    from mimicanno.server.edit_repo import RunNotFound, apply_edit
    with pytest.raises(RunNotFound) as ei:
        apply_edit(
            runs_root=tmp_runs_root_loadable,
            name="episode_999999__nonexistent",
            segment_id="any",
            new_phase="idle",
            if_match="sha256:" + "0" * 64,
            reviewer=None,
            labelset=_labelset(),
        )
    assert ei.value.name == "episode_999999__nonexistent"
