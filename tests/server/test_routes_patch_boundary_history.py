"""Phase 5 D — server-side history emit for PATCH /boundaries/{id} (B r2).

Verifies that a successful boundary PATCH appends a single EditEvent with
edit_type="boundary" (and the optional client_edit_duration_ms) to
annotation.history.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.app import create_app
from tests.server.conftest import _REAL_SO101_RUN, _build_loadable_fixture


def _client(runs_root: Path) -> TestClient:
    app = create_app(runs_root=runs_root, cors_origins=[])
    return TestClient(app)


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    if not _REAL_SO101_RUN.is_dir():
        pytest.skip(f"loadable fixture missing: {_REAL_SO101_RUN}")
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


# Right segment of the inner seg0000/seg0001 boundary.
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"


def test_patch_boundary_with_duration_emits_history(
    runs_root_with_loadable: Path,
) -> None:
    """PATCH /boundaries with client_edit_duration_ms=2200 →
    history += EditEvent(edit_type="boundary", client_edit_duration_ms=2200)."""
    root = runs_root_with_loadable
    name = _REAL_SO101_RUN.name
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"frame": 15, "client_edit_duration_ms": 2200}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    ev = ann.history[0]
    assert ev.edit_type == "boundary"
    assert ev.segment_id == _BOUNDARY_ID_0_1
    assert ev.client_edit_duration_ms == 2200


def test_patch_boundary_without_duration_emits_history(
    runs_root_with_loadable: Path,
) -> None:
    """PATCH /boundaries with no duration → history entry has None."""
    root = runs_root_with_loadable
    name = _REAL_SO101_RUN.name
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"frame": 15}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    ev = ann.history[0]
    assert ev.edit_type == "boundary"
    assert ev.client_edit_duration_ms is None
