"""Phase 5 B r2 T7: boundary drag integration tests (spec §5.2).

Two cases exercised end-to-end via TestClient against a fully-loaded
runs/ tree:

  Case 1 — drag cycle: PATCH(frame=15) 200 → GET manifest → PATCH(frame=25,
           new ETag) 200 → verify final annotation state.

  Case 2 — stale-ETag chain: PATCH(frame=15) 200 → PATCH again with OLD ETag
           412 → verify disk unchanged after 412.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest


def _client(tmp_runs_root_loadable: Path, reviewer: str | None = None) -> TestClient:
    from mimicanno.server.app import create_app
    return TestClient(
        create_app(
            runs_root=tmp_runs_root_loadable,
            cors_origins=[],
            reviewer=reviewer,
        ),
    )


_BOUNDARY_ID = "episode_000000__seg0001"  # right seg, boundary at frame 20


def _patch(client: TestClient, name: str, boundary_id: str, frame: int, etag: str) -> object:
    import json
    return client.request(
        "PATCH", f"/api/runs/{name}/boundaries/{boundary_id}",
        headers={"Content-Type": "application/json", "If-Match": etag},
        content=json.dumps({"frame": frame}),
    )


# ---------------------------------------------------------------------------
# Case 1: drag → re-GET → drag forward with new ETag
# ---------------------------------------------------------------------------


def test_boundary_drag_cycle(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.2 case 1: two sequential boundary drags both succeed when
    each uses the ETag from the preceding state."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    client = _client(tmp_runs_root_loadable, reviewer="alice")
    name = loadable_canonical_name

    # First drag: move boundary from 20 → 15 (backward)
    rh0 = read_manifest(run_dir / "manifest.json").run_hash
    r1 = _patch(client, name, _BOUNDARY_ID, 15, rh0)
    assert r1.status_code == 200
    rh1 = r1.json()["run_hash"]
    assert rh1 != rh0

    # GET manifest via server route to obtain current ETag
    resp = client.get(f"/api/runs/{name}/manifest.json")
    assert resp.status_code == 200
    assert resp.json()["run_hash"] == rh1

    # Second drag: move boundary from 15 → 25 (forward from current position)
    # Current state: seg0000=[0..14], seg0001=[15..49]. Boundary is at 15.
    # new_frame=25 is valid (25 > 0=seg0000.start_frame, 25 ≤ 49=seg0001.end_frame)
    r2 = _patch(client, name, _BOUNDARY_ID, 25, rh1)
    assert r2.status_code == 200
    rh2 = r2.json()["run_hash"]
    assert rh2 != rh1

    # Final disk state
    ann = read_annotation_result(run_dir / "annotation.json")
    left = ann.segments[0]   # seg0000
    right = ann.segments[1]  # seg0001
    assert left.end_frame == 24
    assert right.start_frame == 25
    assert left.reviewer_id == "alice"
    assert right.reviewer_id == "alice"
    assert ann.run_hash == rh2


# ---------------------------------------------------------------------------
# Case 2: drag → 412 on old ETag
# ---------------------------------------------------------------------------


def test_boundary_drag_stale_etag_chain(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.2 case 2: after a successful drag, retrying with the OLD ETag
    returns 412 and leaves disk unchanged."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    client = _client(tmp_runs_root_loadable)
    name = loadable_canonical_name

    rh_initial = read_manifest(run_dir / "manifest.json").run_hash

    # First drag succeeds
    r1 = _patch(client, name, _BOUNDARY_ID, 15, rh_initial)
    assert r1.status_code == 200

    # Snapshot disk after first drag
    snap = (
        (run_dir / "annotation.json").read_bytes(),
        (run_dir / "manifest.json").read_bytes(),
        (tmp_runs_root_loadable / "index.json").read_bytes(),
    )

    # Second drag with stale ETag → 412
    r2 = _patch(client, name, _BOUNDARY_ID, 25, rh_initial)
    assert r2.status_code == 412
    assert r2.json()["error"] == "etag_mismatch"

    # Disk unchanged after the rejected PATCH
    assert (run_dir / "annotation.json").read_bytes() == snap[0]
    assert (run_dir / "manifest.json").read_bytes() == snap[1]
    assert (tmp_runs_root_loadable / "index.json").read_bytes() == snap[2]
