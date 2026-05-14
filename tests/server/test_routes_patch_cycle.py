"""Phase 5 B r1 T10: HTTP-layer PATCH cycle integration (spec §5.2).

TestClient-based, in-process. Subprocess race goes to T11.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest


def _client(runs_root: Path, reviewer: str | None = None) -> TestClient:
    from mimicanno.server.app import create_app
    return TestClient(
        create_app(runs_root=runs_root, cors_origins=[], reviewer=reviewer),
    )


def test_patch_cycle_re_get_etag_consistency(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.2 #1: PATCH succeeds; a follow-up GET on manifest.json
    returns the SAME run_hash and ETag the PATCH response advertised."""
    name = loadable_canonical_name
    client = _client(tmp_runs_root_loadable, reviewer="bob")

    # Initial GET
    r1 = client.get(f"/api/runs/{name}/manifest.json")
    assert r1.status_code == 200
    initial_etag = r1.headers["etag"]
    initial_rh = r1.json()["run_hash"]
    assert initial_etag == f'"{initial_rh}"'

    # Pick the first segment
    seg_id = client.get(f"/api/runs/{name}/annotation.json").json()["segments"][0]["segment_id"]

    # PATCH
    r_patch = client.request(
        "PATCH", f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": initial_etag},
        content=json.dumps({"phase": "idle"}),
    )
    assert r_patch.status_code == 200
    new_etag = r_patch.headers["etag"]
    new_rh = r_patch.json()["run_hash"]
    assert new_etag == f'"{new_rh}"'
    assert new_rh != initial_rh

    # GET 2: persisted manifest matches the PATCH response
    r2 = client.get(f"/api/runs/{name}/manifest.json")
    assert r2.status_code == 200
    assert r2.headers["etag"] == new_etag
    assert r2.json()["run_hash"] == new_rh


def test_patch_cycle_stale_etag_412_after_success(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.2 #2: PATCH 1 succeeds; PATCH 2 with the OLD If-Match
    returns 412 etag_mismatch — the client must re-fetch before
    re-editing."""
    name = loadable_canonical_name
    client = _client(tmp_runs_root_loadable, reviewer=None)

    initial_rh = read_manifest(tmp_runs_root_loadable / name / "manifest.json").run_hash
    seg_id = read_annotation_result(
        tmp_runs_root_loadable / name / "annotation.json",
    ).segments[0].segment_id

    # PATCH 1
    r1 = client.request(
        "PATCH", f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": f'"{initial_rh}"'},
        content=json.dumps({"phase": "idle"}),
    )
    assert r1.status_code == 200

    # PATCH 2 with the stale If-Match
    r2 = client.request(
        "PATCH", f"/api/runs/{name}/segments/{seg_id}",
        headers={"Content-Type": "application/json", "If-Match": f'"{initial_rh}"'},
        content=json.dumps({"phase": "approach_object"}),
    )
    assert r2.status_code == 412
    assert r2.json()["error"] == "etag_mismatch"


def test_patch_cycle_chained_different_segment_preserves_prior_mark(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.2 + §7 risk: PATCH segment 0 then segment 1. After both,
    BOTH segments must carry "edited" in smoothing_ops. The chained
    read-modify-write must NOT regenerate annotation in a way that drops
    seg0's prior edit mark when editing seg1.

    Distinct from T6j (single PATCH + non-target byte-identical) — T10
    exercises the chained path where the annotation read at PATCH-2 time
    is already non-pristine (has seg0's edit).
    """
    name = loadable_canonical_name
    client = _client(tmp_runs_root_loadable, reviewer="alice")

    ann_initial = client.get(f"/api/runs/{name}/annotation.json").json()
    assert len(ann_initial["segments"]) >= 2, "fixture needs ≥2 segments"
    seg0_id = ann_initial["segments"][0]["segment_id"]
    seg1_id = ann_initial["segments"][1]["segment_id"]

    initial_rh = client.get(f"/api/runs/{name}/manifest.json").json()["run_hash"]

    # PATCH segment 0
    r1 = client.request(
        "PATCH", f"/api/runs/{name}/segments/{seg0_id}",
        headers={"Content-Type": "application/json",
                 "If-Match": f'"{initial_rh}"'},
        content=json.dumps({"phase": "idle"}),
    )
    assert r1.status_code == 200
    rh_after_seg0 = r1.json()["run_hash"]

    # PATCH segment 1 with the new ETag
    r2 = client.request(
        "PATCH", f"/api/runs/{name}/segments/{seg1_id}",
        headers={"Content-Type": "application/json",
                 "If-Match": f'"{rh_after_seg0}"'},
        content=json.dumps({"phase": "grasp_object"}),
    )
    assert r2.status_code == 200

    # Both segments carry "edited"
    ann_post = client.get(f"/api/runs/{name}/annotation.json").json()
    seg0_post = next(s for s in ann_post["segments"] if s["segment_id"] == seg0_id)
    seg1_post = next(s for s in ann_post["segments"] if s["segment_id"] == seg1_id)
    assert seg0_post["smoothing_ops"][-1] == "edited"
    assert seg1_post["smoothing_ops"][-1] == "edited"

    # Crucially: seg0's prior edit mark survives seg1's PATCH.
    # Without this, multi-edit sessions silently lose audit trail.
    assert "edited" in seg0_post["smoothing_ops"], (
        "chained PATCH on seg1 dropped seg0's prior 'edited' mark — "
        "would silently break the audit trail (spec §7 risk)"
    )
    # And the phase change from PATCH-1 stayed.
    assert seg0_post["phase"] == "idle"
