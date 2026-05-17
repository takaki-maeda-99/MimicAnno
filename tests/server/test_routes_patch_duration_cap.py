"""Phase 5 D r2 B4 — server-side upper bound (600,000ms = 10 min) on
client_edit_duration_ms. Values above the cap are rejected with 400 invalid_body.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.app import create_app
from tests.server.conftest import _LOADABLE_RUN_NAME, _build_loadable_fixture

# Spec §2.4: 10 minutes is the upper bound.
DURATION_CAP_MS = 600_000

# Boundary ID derivation matches sibling test fixture pattern:
# tests/server/test_routes_patch_boundary_history.py:34
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"


def _client(runs_root: Path) -> TestClient:
    app = create_app(runs_root=runs_root, cors_origins=[])
    return TestClient(app)


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


def _other_phase(runs_root: Path, name: str) -> str:
    from mimicanno.labelset import default_labels_path, load_label_set
    ls = load_label_set(Path(default_labels_path("manipulation")))
    ann = read_annotation_result(runs_root / name / "annotation.json")
    current = ann.segments[0].phase
    return next(l.id for l in ls.labels if l.id != current)


# --- Phase route ---

def test_phase_at_cap_accepted(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id
    new_phase = _other_phase(root, name)

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase, "client_edit_duration_ms": DURATION_CAP_MS}),
    )
    assert resp.status_code == 200, resp.text


def test_phase_above_cap_rejected(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id
    new_phase = _other_phase(root, name)

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase, "client_edit_duration_ms": DURATION_CAP_MS + 1}),
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["error"] == "invalid_body"
    assert "client_edit_duration_ms" in body["message"]


# --- Reviewed route ---

def test_reviewed_at_cap_accepted(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    target = next(s for s in ann.segments if s.reviewed)

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{target.segment_id}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": False, "client_edit_duration_ms": DURATION_CAP_MS}),
    )
    assert resp.status_code == 200, resp.text


def test_reviewed_above_cap_rejected(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    target = next(s for s in ann.segments if s.reviewed)

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{target.segment_id}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": False, "client_edit_duration_ms": DURATION_CAP_MS + 1}),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_body"


# --- Labels route ---

def test_labels_at_cap_accepted(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{seg_id}/labels",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({
            "verb": "grasp", "object": "tape", "target": None, "failure_flags": [],
            "client_edit_duration_ms": DURATION_CAP_MS,
        }),
    )
    assert resp.status_code == 200, resp.text


def test_labels_above_cap_rejected(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id

    resp = _client(root).patch(
        f"/api/runs/{name}/segments/{seg_id}/labels",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({
            "verb": "grasp", "object": "tape", "target": None, "failure_flags": [],
            "client_edit_duration_ms": DURATION_CAP_MS + 1,
        }),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_body"


# --- Boundary route ---

def test_boundary_at_cap_accepted(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    resp = _client(root).patch(
        f"/api/runs/{name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"frame": 15, "client_edit_duration_ms": DURATION_CAP_MS}),
    )
    assert resp.status_code == 200, resp.text


def test_boundary_above_cap_rejected(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    resp = _client(root).patch(
        f"/api/runs/{name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"frame": 15, "client_edit_duration_ms": DURATION_CAP_MS + 1}),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "invalid_body"
