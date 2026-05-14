"""Phase 5 B r1 T8: PATCH /api/runs/{name}/segments/{segment_id} tests.

Spec §5.1 #1-#11 + 4 HTTP extras (#12-#15). Spec §5.1 #12/#14/#15/#17
are covered by earlier T-tasks at the edit_repo level; #13/#16/#18 are
delegated to T10/T10b/T11.
"""
from __future__ import annotations

import json
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


def _patch(client: TestClient, name: str, segment_id: str, *, body: object, if_match: str | None, content_type: str = "application/json"):
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
        "PATCH", f"/api/runs/{name}/segments/{segment_id}",
        headers=headers, content=data,
    )


# ----- #1 happy path -----


def test_patch_happy_path(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.1 #1: 200 + new ETag + body new manifest; on-disk state
    reflects the relabel + ops/reviewed/reviewer."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    pre_manifest = read_manifest(run_dir / "manifest.json")
    seg0 = read_annotation_result(run_dir / "annotation.json").segments[0]
    new_phase = "idle" if seg0.phase != "idle" else "approach_object"

    r = _patch(
        _client(tmp_runs_root_loadable, reviewer="takaki"),
        loadable_canonical_name, seg0.segment_id,
        body={"phase": new_phase}, if_match=pre_manifest.run_hash,
    )
    assert r.status_code == 200
    new_manifest_body = r.json()
    new_run_hash = new_manifest_body["run_hash"]
    assert new_run_hash != pre_manifest.run_hash
    assert r.headers.get("etag") == f'"{new_run_hash}"'

    # Disk reflects the edit
    post_seg = read_annotation_result(run_dir / "annotation.json").segments[0]
    assert post_seg.phase == new_phase
    assert post_seg.smoothing_ops[-1] == "edited"
    assert post_seg.reviewed is True
    assert post_seg.reviewer_id == "takaki"


# ----- #2 If-Match correct -----


def test_patch_etag_correct_succeeds(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.1 #2: explicit assertion that the correct If-Match path
    returns 200 (overlaps #1 by design — matrix completeness)."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=rh,
    )
    assert r.status_code == 200


# ----- #3 stale If-Match → 412 -----


def test_patch_etag_stale_412(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match="sha256:" + "0" * 64,
    )
    assert r.status_code == 412
    assert r.json()["error"] == "etag_mismatch"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #4 If-Match absent → 428 -----


def test_patch_if_match_absent_428(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=None,
    )
    assert r.status_code == 428
    assert r.json()["error"] == "etag_required"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #5 invalid_body: missing phase -----


def test_patch_invalid_body_missing_phase(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_body"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #6 invalid_body matrix (parametrize) -----


@pytest.mark.parametrize("body_kind", ["extra_keys", "non_str_phase", "empty_string", "non_json"])
def test_patch_invalid_body_matrix(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    body_kind: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)

    if body_kind == "extra_keys":
        r = client.request(
            "PATCH", f"/api/runs/{loadable_canonical_name}/segments/{seg_id}",
            headers={"Content-Type": "application/json", "If-Match": rh},
            content=json.dumps({"phase": "idle", "extra": "nope"}),
        )
    elif body_kind == "non_str_phase":
        r = client.request(
            "PATCH", f"/api/runs/{loadable_canonical_name}/segments/{seg_id}",
            headers={"Content-Type": "application/json", "If-Match": rh},
            content=json.dumps({"phase": 42}),
        )
    elif body_kind == "empty_string":
        r = client.request(
            "PATCH", f"/api/runs/{loadable_canonical_name}/segments/{seg_id}",
            headers={"Content-Type": "application/json", "If-Match": rh},
            content="",
        )
    else:  # non_json
        r = client.request(
            "PATCH", f"/api/runs/{loadable_canonical_name}/segments/{seg_id}",
            headers={"Content-Type": "application/json", "If-Match": rh},
            content="{not valid json",
        )

    assert r.status_code == 400, f"{body_kind}: got {r.status_code} body={r.text}"
    assert r.json()["error"] == "invalid_body"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #7 invalid_label -----


def test_patch_invalid_label_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "not_a_real_phase"}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_label"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #8 invalid_segment -----


def test_patch_invalid_segment_400(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, "does_not_exist__seg9999",
        body={"phase": "idle"}, if_match=rh,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_segment"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #9 run_not_found -----


def test_patch_run_not_found_404(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    r = _patch(
        _client(tmp_runs_root_loadable),
        "episode_999999__nope", "any_seg",
        body={"phase": "idle"}, if_match="sha256:" + "0" * 64,
    )
    assert r.status_code == 404
    assert r.json()["error"] == "run_not_found"
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #10 Content-Type 415 (parametrize) -----


@pytest.mark.parametrize("content_type,expected", [
    ("text/plain", 415),
    ("", 415),
    ("application/x-www-form-urlencoded", 415),
    ("Application/JSON", 200),       # case-insensitive (RFC 7231)
    ("application/json; charset=utf-8", 200),  # parameters allowed
])
def test_patch_content_type_matrix(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    content_type: str, expected: int,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    snap = _snapshot(run_dir, tmp_runs_root_loadable)

    client = _client(tmp_runs_root_loadable)
    headers = {"If-Match": rh}
    if content_type:
        headers["Content-Type"] = content_type
    r = client.request(
        "PATCH", f"/api/runs/{loadable_canonical_name}/segments/{seg_id}",
        headers=headers, content=json.dumps({"phase": "idle"}),
    )
    assert r.status_code == expected, f"ct={content_type!r}: got {r.status_code}"
    if expected == 415:
        assert r.json()["error"] == "unsupported_media"
        _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #11 405 on PATCH against artifact paths -----


def test_patch_on_artifact_path_405(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.1 #11: PATCH against /manifest.json hits the GET/HEAD
    artifact route → 405 with Allow header preserved through the
    envelope handler."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    snap = _snapshot(run_dir, tmp_runs_root_loadable)
    client = _client(tmp_runs_root_loadable)
    r = client.request(
        "PATCH", f"/api/runs/{loadable_canonical_name}/manifest.json",
        headers={"Content-Type": "application/json"},
        content=json.dumps({"phase": "idle"}),
    )
    assert r.status_code == 405
    assert r.json()["error"].startswith("http_")
    allow = r.headers.get("allow", "")
    assert "GET" in allow and "HEAD" in allow
    _assert_unchanged(run_dir, tmp_runs_root_loadable, snap)


# ----- #12 ETag header matches run_hash -----


def test_patch_response_etag_header_matches_run_hash(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=rh,
    )
    assert r.status_code == 200
    body_run_hash = r.json()["run_hash"]
    assert r.headers.get("etag") == f'"{body_run_hash}"'


# ----- #13 Cache-Control: no-cache -----


def test_patch_response_cache_control_no_cache(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=rh,
    )
    assert r.headers.get("cache-control") == "no-cache"


# ----- #14 If-Match with RFC 7232 quotes -----


def test_patch_if_match_with_quotes_works(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """RFC 7232 strong ETag form: If-Match: "sha256:...". The route
    strips quotes before forwarding to edit_repo."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    r = _patch(
        _client(tmp_runs_root_loadable),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=f'"{rh}"',  # quoted
    )
    assert r.status_code == 200


# ----- #15 reviewer from create_app kwarg → segment.reviewer_id -----


def test_patch_reviewer_from_create_app(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
) -> None:
    """Spec §5.1 #15-style integration: create_app(reviewer="alice")
    flows through to segment.reviewer_id after PATCH."""
    run_dir = tmp_runs_root_loadable / loadable_canonical_name
    rh = read_manifest(run_dir / "manifest.json").run_hash
    seg_id = read_annotation_result(run_dir / "annotation.json").segments[0].segment_id
    r = _patch(
        _client(tmp_runs_root_loadable, reviewer="alice"),
        loadable_canonical_name, seg_id,
        body={"phase": "idle"}, if_match=rh,
    )
    assert r.status_code == 200
    seg = read_annotation_result(run_dir / "annotation.json").segments[0]
    assert seg.reviewer_id == "alice"
