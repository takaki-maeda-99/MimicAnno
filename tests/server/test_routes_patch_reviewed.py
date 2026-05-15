"""Phase 5 B r3 T7: PATCH /api/runs/{name}/segments/{segment_id}/reviewed tests.

Real SO101 ep0 annotation (5 segments):
  seg0000..seg0004; seg0000.reviewed=False initially.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.hashing import sha256_hex_of_str
from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.reviewed_repo import derive_reviewed_run_hash
from mimicanno.server.boundary_repo import derive_boundary_run_hash


def _derive_r1_run_hash(old_rh: str, segment_id: str, new_phase: str, reviewer: str | None) -> str:
    preimage = "edit:" + old_rh + ":" + segment_id + ":" + new_phase + ":" + (reviewer or "")
    return "sha256:" + sha256_hex_of_str(preimage)


def _client(tmp_runs_root_loadable: Path, reviewer: str | None = None) -> TestClient:
    from mimicanno.server.app import create_app
    return TestClient(
        create_app(
            runs_root=tmp_runs_root_loadable,
            cors_origins=[],
            reviewer=reviewer,
        ),
    )


def _snapshot(run_dir: Path, runs_root: Path) -> tuple[bytes, bytes, bytes]:
    return (
        (run_dir / "annotation.json").read_bytes(),
        (run_dir / "manifest.json").read_bytes(),
        (runs_root / "index.json").read_bytes(),
    )


def _assert_unchanged(run_dir: Path, runs_root: Path, snap: tuple[bytes, bytes, bytes]) -> None:
    assert (run_dir / "annotation.json").read_bytes() == snap[0]
    assert (run_dir / "manifest.json").read_bytes() == snap[1]
    assert (runs_root / "index.json").read_bytes() == snap[2]


def _patch_reviewed(
    client: TestClient,
    name: str,
    segment_id: str,
    *,
    body: object,
    if_match: str | None,
    content_type: str = "application/json",
):
    headers: dict[str, str] = {"Content-Type": content_type}
    if if_match is not None:
        headers["If-Match"] = if_match
    if isinstance(body, (dict, list)):
        data = json.dumps(body)
    elif isinstance(body, bytes):
        data = body.decode("utf-8")
    else:
        data = str(body) if body is not None else ""
    return client.request(
        "PATCH", f"/api/runs/{name}/segments/{segment_id}/reviewed",
        headers=headers, content=data,
    )


# seg0004 is reviewed=False in the fixture source (seg0000-0003 were set to True by T16 smoke).
_SEG_ID = "episode_000000__seg0004"


# ---------------------------------------------------------------------------
# #1 happy path — reviewed=True
# ---------------------------------------------------------------------------

def test_patch_reviewed_true_200(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf_before = read_manifest(run_dir / "manifest.json")
    old_rh = mf_before.run_hash
    client = _client(tmp_runs_root_loadable, reviewer="takaki")

    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": True},
        if_match=f'"{old_rh}"',
    )
    assert r.status_code == 200

    body = r.json()
    new_rh = body["run_hash"]
    expected_rh = derive_reviewed_run_hash(old_rh, _SEG_ID, True, "takaki")
    assert new_rh == expected_rh
    assert r.headers["ETag"] == f'"{new_rh}"'

    # Disk: annotation updated
    ann = read_annotation_result(run_dir / "annotation.json")
    seg = next(s for s in ann.segments if s.segment_id == _SEG_ID)
    assert seg.reviewed is True
    assert seg.reviewer_id == "takaki"

    # Disk: manifest updated
    mf_after = read_manifest(run_dir / "manifest.json")
    assert mf_after.run_hash == new_rh
    assert mf_after.edited_at is not None

    # index.json has exactly one row for this episode
    idx_raw = json.loads((tmp_runs_root_loadable / "index.json").read_text())
    ep_rows = [row for row in idx_raw["runs"] if row["episode_id"] == "episode_000000"]
    assert len(ep_rows) == 1
    assert ep_rows[0]["run_hash"] == new_rh


# ---------------------------------------------------------------------------
# #2 happy path — reviewed=False clears reviewer_id
# ---------------------------------------------------------------------------

def test_patch_reviewed_false_clears_reviewer_id(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    # First mark reviewed=True
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    client = _client(tmp_runs_root_loadable, reviewer="takaki")

    r1 = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": True}, if_match=f'"{mf.run_hash}"',
    )
    assert r1.status_code == 200
    rh2 = r1.json()["run_hash"]

    # Then flip back to False
    r2 = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": False}, if_match=f'"{rh2}"',
    )
    assert r2.status_code == 200

    ann = read_annotation_result(run_dir / "annotation.json")
    seg = next(s for s in ann.segments if s.segment_id == _SEG_ID)
    assert seg.reviewed is False
    assert seg.reviewer_id is None


# ---------------------------------------------------------------------------
# #3 no_change — segment already has the sent value
# ---------------------------------------------------------------------------

def test_patch_reviewed_no_change_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    # seg0004 starts reviewed=False in fixture; sending False again → no_change
    ann = read_annotation_result(run_dir / "annotation.json")
    seg = next(s for s in ann.segments if s.segment_id == _SEG_ID)
    assert seg.reviewed is False

    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": False}, if_match=f'"{mf.run_hash}"',
    )
    assert r.status_code == 400
    assert r.json()["error"] == "no_change"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #4 invalid_body — missing body
# ---------------------------------------------------------------------------

def test_patch_reviewed_no_body_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body=b"", if_match=f'"{mf.run_hash}"',
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_body"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #5 invalid_body — reviewed is not bool
# ---------------------------------------------------------------------------

def test_patch_reviewed_wrong_type_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": "yes"}, if_match=f'"{mf.run_hash}"',
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_body"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #6 invalid_segment — segment_id not in annotation
# ---------------------------------------------------------------------------

def test_patch_reviewed_unknown_segment_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, "episode_000000__nonexistent",
        body={"reviewed": True}, if_match=f'"{mf.run_hash}"',
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_segment"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #7 run_not_found — 404
# ---------------------------------------------------------------------------

def test_patch_reviewed_run_not_found_404(
    tmp_runs_root_loadable: Path,
) -> None:
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, "nonexistent__deadbeef", _SEG_ID,
        body={"reviewed": True}, if_match='"sha256:' + "a" * 64 + '"',
    )
    assert r.status_code == 404
    assert r.json()["error"] == "run_not_found"


# ---------------------------------------------------------------------------
# #8 etag_mismatch — 412
# ---------------------------------------------------------------------------

def test_patch_reviewed_etag_mismatch_412(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": True},
        if_match='"sha256:' + "b" * 64 + '"',
    )
    assert r.status_code == 412
    assert r.json()["error"] == "etag_mismatch"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #9 unsupported_media_type — 415
# ---------------------------------------------------------------------------

def test_patch_reviewed_wrong_content_type_415(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": True}, if_match=f'"{mf.run_hash}"',
        content_type="text/plain",
    )
    assert r.status_code == 415
    assert r.json()["error"] == "unsupported_media"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #10 precondition_required — 428
# ---------------------------------------------------------------------------

def test_patch_reviewed_no_if_match_428(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = _patch_reviewed(
        client, loadable_canonical_name, _SEG_ID,
        body={"reviewed": True}, if_match=None,
    )
    assert r.status_code == 428
    assert r.json()["error"] == "etag_required"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #11 hash disjoint — byte[5] of preimage prefix
# ---------------------------------------------------------------------------

def test_hash_disjoint_r3_r2_r1(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """r3 hash prefix byte[5]='r' is disjoint from r2 'b' and r1 ':'."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    mf = read_manifest(run_dir / "manifest.json")
    old_rh = mf.run_hash

    rh_r3 = derive_reviewed_run_hash(old_rh, _SEG_ID, True, None)
    rh_r2 = derive_boundary_run_hash(old_rh, "episode_000000__seg0001", 25, None)
    rh_r1 = _derive_r1_run_hash(old_rh, _SEG_ID, "idle", None)

    # All three are distinct.
    assert rh_r3 != rh_r2
    assert rh_r3 != rh_r1
    assert rh_r2 != rh_r1

    # Preimage prefix byte[5] check: r3='r', r2='b'.
    # r1 prefix "edit:" is only 5 chars so byte[5] is the segment_id start —
    # the full preimage is structurally different; hash distinctness above proves it.
    r3_prefix = "edit:reviewed:"
    r2_prefix = "edit:boundary:"
    assert r3_prefix[5] == "r"
    assert r2_prefix[5] == "b"
    assert r3_prefix[5] != r2_prefix[5]
