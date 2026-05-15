"""Phase 5 B r1 T4.5: smoke tests for the ``tmp_runs_root_loadable``
fixture. The PATCH writer tests in T6+ need a runs/ tree whose
manifest.json round-trips through ``read_manifest`` (full schema) and
whose annotation.json carries real SubtaskSegment data.
"""
from __future__ import annotations

import json
from pathlib import Path

from mimicanno.io import read_manifest
from mimicanno.runindex import read_index


def test_tmp_runs_root_loadable_manifest_round_trips(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """``read_manifest`` succeeds on the fixture manifest; canonical_name
    is the injected value (matches dir name), artifacts list excludes
    video.mp4 per T4.5 spec."""
    m = read_manifest(
        tmp_runs_root_loadable / loadable_canonical_name / "manifest.json",
    )
    assert m.canonical_name == loadable_canonical_name
    roles = {a.role for a in m.artifacts}
    assert {"annotation", "boundaries", "signals", "tracks"} <= roles
    assert "video" not in roles


def test_tmp_runs_root_loadable_video_and_vlm_dumps_not_copied(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Allow-list copy: video.mp4 and _vlm_dumps must NOT be in the
    fixture (spec §S-5 + plan T4.5 step 3)."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    assert not (run_dir / "video.mp4").exists()
    assert not (run_dir / "_vlm_dumps").exists()
    assert not (tmp_runs_root_loadable / "_vlm_dumps").exists()


def test_tmp_runs_root_loadable_artifacts_actually_present(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Each allow-listed artifact file must exist on disk and parse as
    JSON (the PATCH writer will load + mutate annotation.json)."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    for fname in (
        "manifest.json", "annotation.json", "boundaries.json",
        "signals.json", "tracks.json",
    ):
        path = run_dir / fname
        assert path.exists(), f"missing {fname}"
        json.loads(path.read_text())  # must parse


def test_tmp_runs_root_loadable_index_well_formed(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """index.json points at the single run, parseable via
    ``read_index``."""
    idx = read_index(tmp_runs_root_loadable / "index.json")
    assert len(idx.rows) == 1
    row = idx.rows[0]
    assert row.manifest_url == f"{loadable_canonical_name}/manifest.json"
    assert row.episode_id == "episode_000000"


def test_tmp_runs_root_loadable_annotation_has_segments(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """annotation.json carries at least one segment with the standard
    SubtaskSegment fields the PATCH writer mutates."""
    ann_path = tmp_runs_root_loadable / loadable_canonical_name / "annotation.json"
    ann = json.loads(ann_path.read_text())
    assert "segments" in ann
    assert len(ann["segments"]) >= 1
    seg = ann["segments"][0]
    for field in (
        "segment_id", "phase", "smoothing_ops", "reviewed", "reviewer_id",
        "start_boundary", "end_boundary",
    ):
        assert field in seg, f"segment missing {field}"
