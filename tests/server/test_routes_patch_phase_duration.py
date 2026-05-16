"""Phase 5 D — T12: duration flowing through PATCH /segments/{id} route.

Tests that client_edit_duration_ms is accepted, stored in history, and
validated (negative / float rejected).
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


def _seg0_id(runs_root: Path, canonical_name: str) -> str:
    ann = read_annotation_result(runs_root / canonical_name / "annotation.json")
    return ann.segments[0].segment_id


def _seg0_phase(runs_root: Path, canonical_name: str) -> str:
    ann = read_annotation_result(runs_root / canonical_name / "annotation.json")
    return ann.segments[0].phase


def _get_other_phase(runs_root: Path, canonical_name: str) -> str:
    """Return a valid phase that differs from seg0's current phase."""
    from mimicanno.labelset import default_labels_path, load_label_set
    ls = load_label_set(Path(default_labels_path("manipulation")))
    current = _seg0_phase(runs_root, canonical_name)
    for label in ls.labels:
        if label.id != current:
            return label.id
    raise RuntimeError("no alternative phase found")


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


def test_patch_phase_with_duration_200(runs_root_with_loadable: Path) -> None:
    """PATCH with client_edit_duration_ms=1500 → 200 + history has that value."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    seg_id = _seg0_id(root, name)
    new_phase = _get_other_phase(root, name)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase, "client_edit_duration_ms": 1500}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    ev = ann.history[0]
    assert ev.edit_type == "relabel"
    assert ev.segment_id == seg_id
    assert ev.client_edit_duration_ms == 1500


def test_patch_phase_without_duration_200(runs_root_with_loadable: Path) -> None:
    """PATCH without client_edit_duration_ms → 200 + history entry with None."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    seg_id = _seg0_id(root, name)
    new_phase = _get_other_phase(root, name)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    assert ann.history[0].client_edit_duration_ms is None


def test_patch_phase_negative_duration_400(runs_root_with_loadable: Path) -> None:
    """PATCH with client_edit_duration_ms=-1 → 400 invalid_body."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    seg_id = _seg0_id(root, name)
    new_phase = _get_other_phase(root, name)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase, "client_edit_duration_ms": -1}),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error") == "invalid_body"


def test_patch_phase_float_duration_400(runs_root_with_loadable: Path) -> None:
    """PATCH with client_edit_duration_ms=1.5 → 400 invalid_body."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    seg_id = _seg0_id(root, name)
    new_phase = _get_other_phase(root, name)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase, "client_edit_duration_ms": 1.5}),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error") == "invalid_body"
