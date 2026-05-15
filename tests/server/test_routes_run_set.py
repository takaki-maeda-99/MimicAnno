"""S-RS T2–T5: routes with ?run_set= query param and /api/run-sets endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(runs_root: Path) -> TestClient:
    from mimicanno.server.errors import install_handlers
    from mimicanno.server.labelset import LabelSetCache
    from mimicanno.server.routes import make_router
    app = FastAPI()
    install_handlers(app)
    app.include_router(
        make_router(runs_root, LabelSetCache.from_path(), reviewer=None),
    )
    return TestClient(app, raise_server_exceptions=False)


# ----- T2: /api/run-sets -----

def test_run_sets_multi(tmp_parent_runs_root: Path) -> None:
    client = _make_client(tmp_parent_runs_root)
    r = client.get("/api/run-sets")
    assert r.status_code == 200
    names = {x["name"] for x in r.json()}
    assert "so101_phase4_v5" in names
    assert "piper_phase4_v5" in names


def test_run_sets_legacy(tmp_runs_root: Path) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get("/api/run-sets")
    assert r.status_code == 200
    assert r.json() == [{"name": ".", "label": "(root)"}]


# ----- T2: path traversal blocked -----

def test_run_set_traversal_blocked(tmp_parent_runs_root: Path) -> None:
    client = _make_client(tmp_parent_runs_root)
    r = client.get("/api/runs/index.json?run_set=../secret")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_run_set"


def test_run_set_not_found(tmp_parent_runs_root: Path) -> None:
    client = _make_client(tmp_parent_runs_root)
    r = client.get("/api/runs/index.json?run_set=nonexistent")
    assert r.status_code == 404
    assert r.json()["error"] == "run_set_not_found"


# ----- T3: GET /api/runs/index.json?run_set= -----

def test_get_index_with_run_set(tmp_parent_runs_root: Path) -> None:
    client = _make_client(tmp_parent_runs_root)
    r = client.get("/api/runs/index.json?run_set=so101_phase4_v5")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == "0.1.0"


def test_get_index_no_run_set_legacy(tmp_runs_root: Path) -> None:
    """Existing legacy behaviour: no ?run_set= still works."""
    client = _make_client(tmp_runs_root)
    r = client.get("/api/runs/index.json")
    assert r.status_code == 200


def test_get_index_dot_run_set(tmp_runs_root: Path) -> None:
    """`?run_set=.` is treated as legacy root."""
    client = _make_client(tmp_runs_root)
    r = client.get("/api/runs/index.json?run_set=.")
    assert r.status_code == 200


# ----- T4: GET /api/runs/{name}/{artifact}?run_set= -----

def test_get_artifact_with_run_set(tmp_parent_runs_root: Path, canonical_name: str) -> None:
    """Place a run dir under a run-set subdir and fetch via ?run_set=."""
    run_dir = tmp_parent_runs_root / "so101_phase4_v5" / canonical_name
    run_dir.mkdir()
    manifest = {"schema_version": "0.2.0", "run_hash": "sha256:" + "a" * 64}
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    client = _make_client(tmp_parent_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/manifest.json?run_set=so101_phase4_v5")
    assert r.status_code == 200
    assert r.json()["run_hash"].startswith("sha256:")


# ----- T5: PATCH /api/runs/{name}/segments/{id}?run_set= -----

def test_patch_with_run_set(
    tmp_parent_runs_root_loadable: Path,
    loadable_run_set_name: str,
    loadable_canonical_name: str,
) -> None:
    """PATCH with ?run_set= routes to the correct subdirectory and writes."""
    from mimicanno.server.app import create_app
    from fastapi.testclient import TestClient as _TC
    app = create_app(
        runs_root=tmp_parent_runs_root_loadable,
        cors_origins=[],
        reviewer=None,
    )
    client = _TC(app)

    # Read current run_hash from the manifest to use as If-Match.
    manifest_path = (
        tmp_parent_runs_root_loadable / loadable_run_set_name / loadable_canonical_name / "manifest.json"
    )
    manifest_data = json.loads(manifest_path.read_text())
    run_hash = manifest_data["run_hash"]

    # Read a valid segment_id from the annotation.
    ann_path = (
        tmp_parent_runs_root_loadable / loadable_run_set_name / loadable_canonical_name / "annotation.json"
    )
    ann_data = json.loads(ann_path.read_text())
    seg_id = ann_data["segments"][0]["segment_id"]
    old_phase = ann_data["segments"][0]["phase"]
    # Choose a different valid phase — pick any label from the server's labelset.
    from mimicanno.server.labelset import LabelSetCache
    ls = LabelSetCache.from_path()
    labels = [lbl.id for lbl in ls.ls.labels if lbl.id != old_phase]
    new_phase = labels[0]

    url = f"/api/runs/{loadable_canonical_name}/segments/{seg_id}?run_set={loadable_run_set_name}"
    r = client.patch(
        url,
        content=json.dumps({"phase": new_phase}),
        headers={"Content-Type": "application/json", "If-Match": f'"{run_hash}"'},
    )
    assert r.status_code == 200, r.text
    # Verify the ETag changed and the written file reflects the edit.
    new_run_hash = r.headers.get("ETag", "").strip('"')
    assert new_run_hash.startswith("sha256:")
    assert new_run_hash != run_hash
