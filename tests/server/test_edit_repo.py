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


def test_apply_edit_cross_file_run_hash_matches(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6f / spec §5b: post-edit annotation.run_hash equals manifest.run_hash."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    rh = read_manifest(run_dir / "manifest.json").run_hash
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh,
        reviewer=None, labelset=_labelset(),
    )
    new_manifest_hash = read_manifest(run_dir / "manifest.json").run_hash
    new_ann_hash = read_annotation_result(run_dir / "annotation.json").run_hash
    assert new_manifest_hash == new_ann_hash


def test_apply_edit_run_hash_format_sha256_prefix(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6f: the derived run_hash matches the manifest JSON-schema pattern
    ^sha256:[0-9a-f]{64}$."""
    import re
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    rh = read_manifest(run_dir / "manifest.json").run_hash
    result = apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh,
        reviewer="x", labelset=_labelset(),
    )
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", result["run_hash"])


def test_apply_edit_sets_edited_at_iso8601(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6g / spec §3.2 step 7: post-edit manifest.edited_at is set to
    ISO-8601 UTC (Z suffix). Pre-edit edited_at is None."""
    import re
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre = read_manifest(run_dir / "manifest.json")
    assert pre.edited_at is None  # fixture is pre-r1
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=pre.run_hash,
        reviewer=None, labelset=_labelset(),
    )
    post = read_manifest(run_dir / "manifest.json")
    assert post.edited_at is not None
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", post.edited_at,
    ), f"unexpected format: {post.edited_at!r}"


def test_apply_edit_preserves_generated_at(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6g / spec §3.2 step 7: generated_at documents pipeline production
    time and MUST NOT be touched by edits."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre = read_manifest(run_dir / "manifest.json")
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=pre.run_hash,
        reviewer=None, labelset=_labelset(),
    )
    post = read_manifest(run_dir / "manifest.json")
    assert post.generated_at == pre.generated_at


def test_apply_edit_preserves_canonical_name(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6g / spec §3.3: canonical_name does NOT change on edit; the dir
    name stays historical, and the manifest field stays equal to it."""
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre = read_manifest(run_dir / "manifest.json")
    assert pre.canonical_name == loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=pre.run_hash,
        reviewer=None, labelset=_labelset(),
    )
    post = read_manifest(run_dir / "manifest.json")
    assert post.canonical_name == loadable_canonical_name


def test_apply_edit_upserts_index_row(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6i / spec §3.2 step 8: post-edit runs/index.json row has the new
    run_hash + new run_hash_short."""
    from mimicanno.runindex import read_index
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    rh_pre = read_manifest(run_dir / "manifest.json").run_hash

    result = apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh_pre,
        reviewer="alice", labelset=_labelset(),
    )

    idx = read_index(tmp_runs_root_loadable / "index.json")
    assert len(idx.rows) == 1
    row = idx.rows[0]
    assert row.run_hash == result["run_hash"]
    # run_hash_short is the suffix of the canonical_name (after "__").
    suffix_len = len(loadable_canonical_name) - len(row.episode_id) - 2
    assert row.run_hash_short == result["run_hash"][len("sha256:"):][:suffix_len]


def test_apply_edit_index_row_preserves_episode_metadata(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """T6i: episode_id, task_text, pipeline_phase, generated_at, and
    config/input hash shorts are unchanged by an edit."""
    from mimicanno.runindex import read_index
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    rh = read_manifest(run_dir / "manifest.json").run_hash
    idx_pre = read_index(tmp_runs_root_loadable / "index.json")
    row_pre = idx_pre.rows[0]

    apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg_id, new_phase="idle", if_match=rh,
        reviewer=None, labelset=_labelset(),
    )
    idx_post = read_index(tmp_runs_root_loadable / "index.json")
    assert len(idx_post.rows) == 1
    row_post = idx_post.rows[0]
    assert row_post.episode_id == row_pre.episode_id
    assert row_post.task_text == row_pre.task_text
    assert row_post.pipeline_phase == row_pre.pipeline_phase
    assert row_post.generated_at == row_pre.generated_at
    assert row_post.config_hash_short == row_pre.config_hash_short
    assert row_post.input_hash_short == row_pre.input_hash_short
    assert row_post.manifest_url == row_pre.manifest_url


@pytest.mark.parametrize("reviewer,reviewer_norm", [
    (None, ""),
    ("takaki", "takaki"),
    ("", ""),
])
def test_apply_edit_run_hash_reviewer_encoding_pinned(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    reviewer: str | None, reviewer_norm: str,
) -> None:
    """T6h / spec §5.1 #12: pin the exact hash input string. None and ""
    normalize to ""; non-empty stays as-is. Replay reproducibility is
    what D's evaluation harness depends on (release 3+)."""
    from mimicanno.hashing import sha256_hex_of_str
    from mimicanno.server.edit_repo import apply_edit
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg0 = read_annotation_result(run_dir / "annotation.json").segments[0]
    old_run_hash = read_manifest(run_dir / "manifest.json").run_hash
    new_phase = "idle" if seg0.phase != "idle" else "approach_object"

    expected_input = (
        "edit:" + old_run_hash + ":" + seg0.segment_id
        + ":" + new_phase + ":" + reviewer_norm
    )
    expected_hash = "sha256:" + sha256_hex_of_str(expected_input)

    result = apply_edit(
        runs_root=tmp_runs_root_loadable, name=loadable_canonical_name,
        segment_id=seg0.segment_id, new_phase=new_phase,
        if_match=old_run_hash, reviewer=reviewer, labelset=_labelset(),
    )
    assert result["run_hash"] == expected_hash


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
