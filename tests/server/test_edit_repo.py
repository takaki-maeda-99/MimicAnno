"""Phase 5 B r1 T6: edit_repo.apply_edit unit tests.

Pure-Python contract — no FastAPI, no HTTP. The route layer in T8 will
translate EditError subclasses into the spec §3.6 envelope.
"""
from __future__ import annotations

from pathlib import Path

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
