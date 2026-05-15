"""Phase 5 B r2 T5: PATCH /api/runs/{name}/boundaries/{boundary_id} tests.

Real SO101 ep0 annotation (5 segments, 151 frames) — post-T16-smoke state:
  seg0000 [0..24], seg0001 [25..54], seg0002 [55..92],
  seg0003 [93..98], seg0004 [99..150]

boundary_id = right segment's segment_id; valid inner boundaries are
seg0001..seg0004. seg0000 is the timeline start edge (→ 400 invalid_boundary).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.boundary_repo import derive_boundary_run_hash
from mimicanno.hashing import sha256_hex_of_str


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


def _patch_boundary(
    client: TestClient,
    name: str,
    boundary_id: str,
    *,
    body: object,
    if_match: str | None,
    content_type: str = "application/json",
) -> object:
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
        "PATCH", f"/api/runs/{name}/boundaries/{boundary_id}",
        headers=headers, content=data,
    )


# The inner boundary between seg0000 and seg0001 (right = seg0001).
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"


# ---------------------------------------------------------------------------
# #1 happy path — move boundary backward
# ---------------------------------------------------------------------------


def test_patch_boundary_backward_200(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """200 + new ETag; left segment shrinks, right segment grows."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre_manifest = read_manifest(run_dir / "manifest.json")
    fps = pre_manifest.fps
    # boundary currently at frame 25; move to 15 (backward)
    new_frame = 15

    r = _patch_boundary(
        _client(tmp_runs_root_loadable, reviewer="takaki"),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": new_frame}, if_match=pre_manifest.run_hash,
    )
    assert r.status_code == 200
    new_manifest_body = r.json()
    new_run_hash = new_manifest_body["run_hash"]
    assert new_run_hash != pre_manifest.run_hash
    assert r.headers.get("etag") == f'"{new_run_hash}"'

    ann = read_annotation_result(run_dir / "annotation.json")
    left = ann.segments[0]   # seg0000
    right = ann.segments[1]  # seg0001

    # left: end_frame = new_frame - 1 = 14
    assert left.end_frame == new_frame - 1
    assert abs(left.end_time - (new_frame - 1) / fps) < 1e-9
    assert left.end_boundary.sources == ["human_edit"]
    assert left.end_boundary.score == 1.0
    assert left.end_boundary.candidate_id is None
    assert "edited" in left.smoothing_ops
    assert left.reviewed is True
    assert left.reviewer_id == "takaki"

    # right: start_frame = new_frame = 15
    assert right.start_frame == new_frame
    assert abs(right.start_time - new_frame / fps) < 1e-9
    assert right.start_boundary.sources == ["human_edit"]
    assert "edited" in right.smoothing_ops
    assert right.reviewed is True
    assert right.reviewer_id == "takaki"


# ---------------------------------------------------------------------------
# #2 happy path — move boundary forward
# ---------------------------------------------------------------------------


def test_patch_boundary_forward_200(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """200; left segment grows, right segment shrinks."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre_manifest = read_manifest(run_dir / "manifest.json")
    new_frame = 30  # boundary at 25 → 30 (forward)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": new_frame}, if_match=pre_manifest.run_hash,
    )
    assert r.status_code == 200
    ann = read_annotation_result(run_dir / "annotation.json")
    assert ann.segments[0].end_frame == new_frame - 1
    assert ann.segments[1].start_frame == new_frame


# ---------------------------------------------------------------------------
# #3 stale If-Match → 412
# ---------------------------------------------------------------------------


def test_patch_boundary_stale_etag_412(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 15}, if_match="sha256:" + "0" * 64,
    )
    assert r.status_code == 412
    assert r.json()["error"] == "etag_mismatch"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #4 If-Match absent → 428
# ---------------------------------------------------------------------------


def test_patch_boundary_no_if_match_428(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 15}, if_match=None,
    )
    assert r.status_code == 428
    assert r.json()["error"] == "etag_required"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #5 Content-Type matrix → 415 / 200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("content_type,expected", [
    ("text/plain", 415),
    ("", 415),
    ("application/x-www-form-urlencoded", 415),
    ("Application/JSON", 200),                   # RFC 7231 case-insensitive
    ("application/json; charset=utf-8", 200),    # parameters allowed
])
def test_patch_boundary_content_type_matrix(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    content_type: str, expected: int,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    client = _client(tmp_runs_root_loadable)
    headers: dict[str, str] = {"If-Match": rh}
    if content_type:
        headers["Content-Type"] = content_type
    r = client.request(
        "PATCH", f"/api/runs/{loadable_canonical_name}/boundaries/{_BOUNDARY_ID_0_1}",
        headers=headers, content=json.dumps({"frame": 15}),
    )
    assert r.status_code == expected, f"ct={content_type!r}: got {r.status_code}"
    if expected == 415:
        assert r.json()["error"] == "unsupported_media"
        _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #6 invalid_body matrix → 400
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body_kind", [
    "missing_frame", "extra_keys", "non_int_float", "non_int_string",
    "empty_string", "non_json",
])
def test_patch_boundary_invalid_body_matrix(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    body_kind: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    base_headers = {"Content-Type": "application/json", "If-Match": rh}
    url = f"/api/runs/{loadable_canonical_name}/boundaries/{_BOUNDARY_ID_0_1}"

    if body_kind == "missing_frame":
        r = client.request("PATCH", url, headers=base_headers, content=json.dumps({}))
    elif body_kind == "extra_keys":
        r = client.request("PATCH", url, headers=base_headers,
                           content=json.dumps({"frame": 15, "extra": "nope"}))
    elif body_kind == "non_int_float":
        r = client.request("PATCH", url, headers=base_headers,
                           content=json.dumps({"frame": 15.5}))
    elif body_kind == "non_int_string":
        r = client.request("PATCH", url, headers=base_headers,
                           content=json.dumps({"frame": "15"}))
    elif body_kind == "empty_string":
        r = client.request("PATCH", url, headers=base_headers, content="")
    else:  # non_json
        r = client.request("PATCH", url, headers=base_headers, content="{not valid json")

    assert r.status_code == 400, f"{body_kind}: got {r.status_code}"
    assert r.json()["error"] == "invalid_body"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #7 invalid_boundary: timeline start edge (seg0000 has no left neighbour)
# ---------------------------------------------------------------------------


def test_patch_boundary_timeline_edge_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg0_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg0_id,
        body={"frame": 5}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_boundary"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #8 invalid_boundary: nonexistent segment_id
# ---------------------------------------------------------------------------


def test_patch_boundary_not_found_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, "episode_000000__seg9999",
        body={"frame": 5}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_boundary"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #9 invalid_frame: new_frame <= left.start_frame (left would vanish)
# ---------------------------------------------------------------------------


def test_patch_boundary_left_vanishes_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """seg0000.start_frame=0; new_frame=0 ≤ 0 → left would have 0 frames."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 0}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #10 invalid_frame: new_frame > right.end_frame (right would vanish)
# ---------------------------------------------------------------------------


def test_patch_boundary_right_vanishes_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """seg0001.end_frame=54; new_frame=55 > 54 → right would have 0 frames."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 55}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #11 invalid_frame: no-op (new_frame == current boundary)
# ---------------------------------------------------------------------------


def test_patch_boundary_noop_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """new_frame=25 equals current right.start_frame → no-op rejected."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 25}, if_match=rh,  # 25 is current boundary
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #12 invalid_frame: out of episode range
# ---------------------------------------------------------------------------


def test_patch_boundary_out_of_range_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """new_frame=-1 < 0 → out of episode range."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": -1}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #13 MIN_SEGMENT_FRAMES=1 boundary cases
# ---------------------------------------------------------------------------


def test_patch_boundary_min_one_frame_left_ok(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """new_frame = left.start_frame + 1 = 1 → left keeps exactly 1 frame."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 1}, if_match=rh,
    )
    assert r.status_code == 200
    ann = read_annotation_result(run_dir / "annotation.json")
    assert ann.segments[0].end_frame == 0   # 1 frame: [0..0]
    assert ann.segments[1].start_frame == 1


def test_patch_boundary_min_one_frame_right_ok(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """new_frame = right.end_frame = 54 → right keeps exactly 1 frame."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash

    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": 54}, if_match=rh,
    )
    assert r.status_code == 200
    ann = read_annotation_result(run_dir / "annotation.json")
    assert ann.segments[0].end_frame == 53
    assert ann.segments[1].start_frame == 54


# ---------------------------------------------------------------------------
# #14 run_hash disjoint from r1 (segment relabel) space
# ---------------------------------------------------------------------------


def test_patch_boundary_run_hash_disjoint_from_r1(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """r2 hash preimage starts with 'edit:boundary:'; r1 starts with 'edit:'.
    The resulting hashes must differ for the same old_run_hash."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre_manifest = read_manifest(run_dir / "manifest.json")
    old_rh = pre_manifest.run_hash
    new_frame = 15
    reviewer = None

    # Compute r2 hash independently
    r2_hash = derive_boundary_run_hash(old_rh, _BOUNDARY_ID_0_1, new_frame, reviewer)

    # Compute what r1 would produce for a hypothetical segment edit with same params
    r1_preimage = "edit:" + old_rh + ":" + _BOUNDARY_ID_0_1 + ":approach_object:"
    r1_hash = "sha256:" + sha256_hex_of_str(r1_preimage)

    assert r2_hash != r1_hash
    assert r2_hash.startswith("sha256:")

    # Confirm the server returns the expected r2 hash
    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, _BOUNDARY_ID_0_1,
        body={"frame": new_frame}, if_match=old_rh,
    )
    assert r.status_code == 200
    assert r.json()["run_hash"] == r2_hash


# ---------------------------------------------------------------------------
# #15 GET /boundaries/<id> → 405 with Allow: PATCH
# ---------------------------------------------------------------------------


def test_get_boundary_405(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """GET against the boundary URL must 405 (only PATCH is registered)."""
    client = _client(tmp_runs_root_loadable)
    r = client.get(
        f"/api/runs/{loadable_canonical_name}/boundaries/{_BOUNDARY_ID_0_1}",
    )
    assert r.status_code == 405
    allow = r.headers.get("allow", "")
    assert "PATCH" in allow


# ---------------------------------------------------------------------------
# #16 run_not_found → 404
# ---------------------------------------------------------------------------


def test_patch_boundary_run_not_found_404(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch_boundary(
        _client(tmp_runs_root_loadable),
        "episode_999999__nope", _BOUNDARY_ID_0_1,
        body={"frame": 15}, if_match="sha256:" + "0" * 64,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "run_not_found"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ---------------------------------------------------------------------------
# #17 concurrent PATCH race → exactly one 200 and one 412
# ---------------------------------------------------------------------------


def test_patch_boundary_concurrent_race(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Two concurrent boundary PATCHes with the same If-Match: exactly one
    wins (200) and one loses (412 etag_mismatch)."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash

    results: list[int] = []

    def do_patch(frame: int) -> None:
        client = _client(tmp_runs_root_loadable)
        r = _patch_boundary(
            client, loadable_canonical_name, _BOUNDARY_ID_0_1,
            body={"frame": frame}, if_match=rh,
        )
        results.append(r.status_code)

    t1 = threading.Thread(target=do_patch, args=(15,))   # backward from 25
    t2 = threading.Thread(target=do_patch, args=(30,))   # forward from 25
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) == [200, 412]


# ---------------------------------------------------------------------------
# T9 hash disjoint: r2 vs r1 vs auto-pipeline (spec §3.5)
# ---------------------------------------------------------------------------


def test_hash_disjoint_r2_r1_auto(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §3.5: r2 preimage byte[5]='b', r1 byte[5]='s', auto has no
    'edit:' prefix — all three hashes are distinct for the same base hash."""
    from mimicanno.config import compose_run_hash

    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    manifest = read_manifest(run_dir / "manifest.json")
    old_rh = manifest.run_hash

    # r2: "edit:boundary:" + ...
    r2_hash = derive_boundary_run_hash(old_rh, _BOUNDARY_ID_0_1, 15, None)

    # r1: "edit:" + old_rh + ":" + seg_id + ":" + phase + ":"
    r1_hash = "sha256:" + sha256_hex_of_str(
        "edit:" + old_rh + ":" + _BOUNDARY_ID_0_1 + ":approach_object:"
    )

    # auto-pipeline: SHA-256 of config_hash_bytes + input_hash_bytes (no "edit:" prefix)
    auto_hash = compose_run_hash(manifest.config_hash, manifest.input_hash)

    assert r2_hash != r1_hash, "r2 and r1 hashes must differ"
    assert r2_hash != auto_hash, "r2 and auto-pipeline hashes must differ"
    assert r1_hash != auto_hash, "r1 and auto-pipeline hashes must differ"

    # Verify byte[5] of the preimage distinguishes the two edit namespaces
    r2_preimage = "edit:boundary:" + old_rh
    r1_preimage = "edit:" + old_rh
    assert r2_preimage[5] == "b"
    assert r1_preimage[5] == "s"
