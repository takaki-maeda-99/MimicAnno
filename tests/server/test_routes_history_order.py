"""Phase 5 D r2 B2 — Two consecutive PATCHes append to history in order.

The append-only history contract from spec §3.1 must survive two back-to-back
edits on the same segment: the second PATCH's event lands after the first,
not in place of it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.app import create_app
from tests.server.conftest import _LOADABLE_RUN_NAME, _build_loadable_fixture


def _client(runs_root: Path) -> TestClient:
    app = create_app(runs_root=runs_root, cors_origins=[])
    return TestClient(app)


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


def test_patch_twice_history_in_chronological_order(runs_root_with_loadable: Path) -> None:
    """PATCH phase then PATCH reviewed on the same segment.

    Expectations:
    - history has exactly 2 events
    - history[0].edit_type == "relabel" (first PATCH)
    - history[1].edit_type == "reviewed" (second PATCH)
    - edited_at[0] <= edited_at[1] (chronological — ISO-8601 sort is fine)
    - Both events reference the same segment_id
    """
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME

    # --- First PATCH: phase relabel ---
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id
    current_phase = ann.segments[0].phase

    from mimicanno.labelset import default_labels_path, load_label_set
    ls = load_label_set(Path(default_labels_path("manipulation")))
    new_phase = next(l.id for l in ls.labels if l.id != current_phase)

    client = _client(root)
    resp1 = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase}),
    )
    assert resp1.status_code == 200, resp1.text
    new_rh = resp1.json()["run_hash"]

    # --- Second PATCH: reviewed toggle on the same segment ---
    ann_after_first = read_annotation_result(root / name / "annotation.json")
    current_reviewed = next(s for s in ann_after_first.segments if s.segment_id == seg_id).reviewed
    resp2 = client.patch(
        f"/api/runs/{name}/segments/{seg_id}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": new_rh},
        content=json.dumps({"reviewed": not current_reviewed}),
    )
    assert resp2.status_code == 200, resp2.text

    # --- Verify history order ---
    final_ann = read_annotation_result(root / name / "annotation.json")
    assert len(final_ann.history) == 2, f"expected 2 events, got {len(final_ann.history)}"

    ev0, ev1 = final_ann.history[0], final_ann.history[1]
    assert ev0.edit_type == "relabel", f"first event type: {ev0.edit_type}"
    assert ev1.edit_type == "reviewed", f"second event type: {ev1.edit_type}"
    assert ev0.segment_id == seg_id
    assert ev1.segment_id == seg_id
    # ISO-8601 strings are lexicographically sortable for UTC timestamps.
    assert ev0.edited_at <= ev1.edited_at, (
        f"events out of chronological order: {ev0.edited_at!r} vs {ev1.edited_at!r}"
    )


def test_patch_twice_history_does_not_overwrite(runs_root_with_loadable: Path) -> None:
    """Second PATCH must not REPLACE the first event — must APPEND."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME

    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id
    current_phase = ann.segments[0].phase
    from mimicanno.labelset import default_labels_path, load_label_set
    ls = load_label_set(Path(default_labels_path("manipulation")))
    phases = [l.id for l in ls.labels if l.id != current_phase]
    if len(phases) < 2:
        pytest.skip("labelset has fewer than 2 alternative phases")
    p1, p2 = phases[0], phases[1]

    client = _client(root)
    resp1 = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": p1}),
    )
    assert resp1.status_code == 200, resp1.text
    rh1 = resp1.json()["run_hash"]

    resp2 = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh1},
        content=json.dumps({"phase": p2}),
    )
    assert resp2.status_code == 200, resp2.text

    final_ann = read_annotation_result(root / name / "annotation.json")
    assert len(final_ann.history) == 2
    assert all(e.edit_type == "relabel" for e in final_ann.history)
    assert all(e.segment_id == seg_id for e in final_ann.history)
    assert final_ann.history[0].edited_at <= final_ann.history[1].edited_at
