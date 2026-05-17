"""Phase 5 D r2 B1 — PATCH must upgrade annotation.schema_version to current.

The frozen loadable_run fixture is at schema_version="0.2.0". Any of the four
PATCH routes (phase / boundary / labels / reviewed) must rewrite the
annotation.json with schema_version="0.3.0" (= ARTIFACT_SCHEMA_VERSIONS["annotation"]).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
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


def _other_phase(runs_root: Path, name: str) -> str:
    from mimicanno.labelset import default_labels_path, load_label_set
    ls = load_label_set(Path(default_labels_path("manipulation")))
    ann = read_annotation_result(runs_root / name / "annotation.json")
    current = ann.segments[0].phase
    for label in ls.labels:
        if label.id != current:
            return label.id
    raise RuntimeError("no alternative phase found")


def test_baseline_fixture_is_pre_bump(runs_root_with_loadable: Path) -> None:
    """Sanity check: the frozen fixture starts at 0.2.0 so we have a witness."""
    ann_path = runs_root_with_loadable / _LOADABLE_RUN_NAME / "annotation.json"
    raw = json.loads(ann_path.read_text())
    assert raw["schema_version"] == "0.2.0"
    assert ARTIFACT_SCHEMA_VERSIONS["annotation"] == "0.3.0"


def test_patch_phase_upgrades_schema_version(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id
    new_phase = _other_phase(root, name)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": new_phase}),
    )
    assert resp.status_code == 200, resp.text

    raw = json.loads((root / name / "annotation.json").read_text())
    assert raw["schema_version"] == ARTIFACT_SCHEMA_VERSIONS["annotation"]


def test_patch_reviewed_upgrades_schema_version(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    target = next(s for s in ann.segments if s.reviewed)

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{target.segment_id}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": False}),
    )
    assert resp.status_code == 200, resp.text

    raw = json.loads((root / name / "annotation.json").read_text())
    assert raw["schema_version"] == ARTIFACT_SCHEMA_VERSIONS["annotation"]


def test_patch_labels_upgrades_schema_version(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash
    ann = read_annotation_result(root / name / "annotation.json")
    seg_id = ann.segments[0].segment_id

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{seg_id}/labels",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"verb": "grasp", "object": "tape", "target": None, "failure_flags": []}),
    )
    assert resp.status_code == 200, resp.text

    raw = json.loads((root / name / "annotation.json").read_text())
    assert raw["schema_version"] == ARTIFACT_SCHEMA_VERSIONS["annotation"]


# Right segment of the inner seg0000/seg0001 boundary (consistent with
# test_routes_patch_boundary_history.py).
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"


def test_patch_boundary_upgrades_schema_version(runs_root_with_loadable: Path) -> None:
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"frame": 15}),
    )
    if resp.status_code != 200:
        pytest.fail(f"boundary PATCH failed unexpectedly: {resp.status_code} {resp.text}")

    raw = json.loads((root / name / "annotation.json").read_text())
    assert raw["schema_version"] == ARTIFACT_SCHEMA_VERSIONS["annotation"]
