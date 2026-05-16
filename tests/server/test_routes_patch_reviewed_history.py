"""Phase 5 D — server-side history emit for PATCH /segments/{id}/reviewed (B r3).

Verifies that a successful reviewed PATCH appends a single EditEvent with
edit_type="reviewed" (and the optional client_edit_duration_ms) to
annotation.history.
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


# seg0004 in the fixture has reviewed=False initially (T16 smoke only flipped
# seg0000..seg0003).
_SEG_ID = "episode_000000__seg0004"


def test_patch_reviewed_with_duration_emits_history(
    runs_root_with_loadable: Path,
) -> None:
    """PATCH /reviewed with client_edit_duration_ms=900 →
    history += EditEvent(edit_type="reviewed", client_edit_duration_ms=900)."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{_SEG_ID}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": True, "client_edit_duration_ms": 900}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    ev = ann.history[0]
    assert ev.edit_type == "reviewed"
    assert ev.segment_id == _SEG_ID
    assert ev.client_edit_duration_ms == 900


def test_patch_reviewed_without_duration_emits_history(
    runs_root_with_loadable: Path,
) -> None:
    """PATCH /reviewed without client_edit_duration_ms → history entry has None."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{_SEG_ID}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": True}),
    )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1
    ev = ann.history[0]
    assert ev.edit_type == "reviewed"
    assert ev.client_edit_duration_ms is None


def test_patch_reviewed_unknown_key_400(
    runs_root_with_loadable: Path,
) -> None:
    """PATCH /reviewed with an unknown key (e.g. duration typo) → 400 invalid_body.

    Parity with phase/boundary/labels routes — typos must not silently drop.
    """
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{_SEG_ID}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({
            "reviewed": True,
            "client_edit_duration_seconds": 5000,  # typo — should be _ms
        }),
    )
    assert resp.status_code == 400, f"got {resp.status_code}: {resp.text}"
    assert resp.json()["error"] == "invalid_body"
