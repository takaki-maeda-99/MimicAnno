"""U-A3 — tests for mimicanno.server.vlm_dumps reader (master §2.4 rev3).

Covers tree walk, attempt selection/failed logic, malformed JSON,
resolve_episode_id, and HTTP route behaviour.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.server.vlm_dumps import (
    VlmCall,
    read_vlm_dumps,
    resolve_episode_id,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_planner(
    ep_dir: Path,
    call_idx: int,
    response: str | None,
    prompt: str = "planner-prompt",
) -> None:
    """Create _planner/call_<NNN>/ with optional response.txt."""
    call_dir = ep_dir / "_planner" / f"call_{call_idx:03d}"
    call_dir.mkdir(parents=True)
    (call_dir / "prompt.txt").write_text(prompt)
    if response is not None:
        (call_dir / "response.txt").write_text(response)
    # frame.png not written; reader builds url from path, not file presence


def _write_labeler(
    ep_dir: Path,
    seg_name: str,
    attempt: int,
    response: str | None,
    prompt: str = "seg-prompt",
    request_json: str | None = None,
    keyframes: int = 0,
) -> Path:
    """Create s_NNN/attempt_M/ with optional response.txt + request.json."""
    attempt_dir = ep_dir / seg_name / f"attempt_{attempt}"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "prompt.txt").write_text(prompt)
    if response is not None:
        (attempt_dir / "response.txt").write_text(response)
    if request_json is not None:
        (attempt_dir / "request.json").write_text(request_json)
    for i in range(keyframes):
        (attempt_dir / f"keyframe_{i:03d}.png").write_bytes(b"PNG")
    return attempt_dir


@pytest.fixture
def run_set_root(tmp_path: Path) -> Path:
    return tmp_path / "runs" / "rs1"


# ---------------------------------------------------------------------------
# read_vlm_dumps — basic cases
# ---------------------------------------------------------------------------


def test_read_empty_ep_dir_returns_empty_list(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    assert read_vlm_dumps(run_set_root, "episode_000000") == []


def test_read_missing_vlm_dumps_dir_returns_empty_list(
    run_set_root: Path,
) -> None:
    run_set_root.mkdir(parents=True)
    assert read_vlm_dumps(run_set_root, "episode_000000") == []


# ---------------------------------------------------------------------------
# Planner call tests
# ---------------------------------------------------------------------------


def test_planner_kind_and_call_id(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, json.dumps({"objects": ["tape"]}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 1
    c = calls[0]
    assert c.kind == "planner"
    # call_id must NOT have "_planner/" prefix (rev3 fix)
    assert c.call_id == "call_000"


def test_planner_frame_url_constructed(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, json.dumps({}))

    calls = read_vlm_dumps(run_set_root, "episode_000000", run_set="rs1")
    assert calls[0].frame_url == (
        "/runs/rs1/_vlm_dumps/episode_000000/_planner/call_000/frame.png"
    )


def test_planner_parsed_on_valid_json(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    payload = {"objects": ["tape", "bottle"], "targets": [], "tools": []}
    _write_planner(ep_dir, 0, json.dumps(payload))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].parsed == payload


def test_planner_parsed_null_on_malformed_json(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, "not-json")

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].parsed is None
    assert calls[0].failed is False  # planner never marked failed


def test_planner_sorted_by_call_id(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 2, json.dumps({"seq": 2}))
    _write_planner(ep_dir, 0, json.dumps({"seq": 0}))
    _write_planner(ep_dir, 1, json.dumps({"seq": 1}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    seqs = [c.parsed["seq"] for c in calls]
    assert seqs == [0, 1, 2]


# ---------------------------------------------------------------------------
# Labeler call tests
# ---------------------------------------------------------------------------


def test_labeler_kind_and_call_id(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({"phase": "approach_object"}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 1
    c = calls[0]
    assert c.kind == "labeler"
    # call_id uses double-underscore separator (rev3 fix)
    assert c.call_id == "s_001__attempt_1"


def test_labeler_segment_ordinal_derived_from_dir_name(
    run_set_root: Path,
) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_042", 1, json.dumps({}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].segment_ordinal == 42


def test_labeler_request_json_read(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    req = {"frames": [1, 2, 3], "context": "something"}
    _write_labeler(
        ep_dir, "s_001", 1, json.dumps({}), request_json=json.dumps(req)
    )

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].request_json == req


def test_labeler_missing_request_json_is_null(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].request_json is None


def test_labeler_keyframe_urls_constructed(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({}), keyframes=3)

    calls = read_vlm_dumps(run_set_root, "episode_000000", run_set="rs1")
    c = calls[0]
    assert c.keyframe_urls == [
        "/runs/rs1/_vlm_dumps/episode_000000/s_001/attempt_1/keyframe_000.png",
        "/runs/rs1/_vlm_dumps/episode_000000/s_001/attempt_1/keyframe_001.png",
        "/runs/rs1/_vlm_dumps/episode_000000/s_001/attempt_1/keyframe_002.png",
    ]


def test_labeler_no_keyframes_gives_empty_list(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].keyframe_urls == []


def test_labeler_sorted_by_ordinal_then_attempt(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    # s_002 attempt_1 and attempt_2; s_001 attempt_1
    _write_labeler(ep_dir, "s_002", 1, json.dumps({"ord": 2, "att": 1}))
    _write_labeler(ep_dir, "s_002", 2, json.dumps({"ord": 2, "att": 2}))
    _write_labeler(ep_dir, "s_001", 1, json.dumps({"ord": 1, "att": 1}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    # s_001 attempt_1 first (ordinal 1), then s_002 attempt_1, s_002 attempt_2
    assert calls[0].segment_ordinal == 1
    assert calls[0].attempt == 1
    assert calls[1].segment_ordinal == 2
    assert calls[1].attempt == 1
    assert calls[2].segment_ordinal == 2
    assert calls[2].attempt == 2


# ---------------------------------------------------------------------------
# Failed flag logic
# ---------------------------------------------------------------------------


def test_failed_true_on_non_final_attempt(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({"phase": "attempt1"}))
    _write_labeler(ep_dir, "s_001", 2, json.dumps({"phase": "attempt2"}))
    _write_labeler(ep_dir, "s_001", 3, json.dumps({"phase": "attempt3"}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    # All non-final attempts are failed; 3 attempts total
    assert len(calls) == 3
    by_attempt = {c.attempt: c for c in calls}
    assert by_attempt[1].failed is True
    assert by_attempt[2].failed is True
    assert by_attempt[3].failed is False  # final attempt with valid JSON


def test_failed_true_on_malformed_final_response(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, "not-json")

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].failed is True
    assert calls[0].parsed is None


def test_failed_true_on_missing_response_file(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, response=None)

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].failed is True
    assert calls[0].raw_output == ""
    assert calls[0].parsed is None


# ---------------------------------------------------------------------------
# Mixed planner + labeler ordering
# ---------------------------------------------------------------------------


def test_planner_before_labeler_in_output(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({}))
    _write_planner(ep_dir, 0, json.dumps({}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert calls[0].kind == "planner"
    assert calls[1].kind == "labeler"


# ---------------------------------------------------------------------------
# VlmCall field contract (rev3)
# ---------------------------------------------------------------------------


def test_vlmcall_rev3_fields() -> None:
    """VlmCall must accept all rev3 fields and no old rev2-only fields."""
    c = VlmCall(
        call_id="call_000",
        kind="planner",
        attempt=None,
        prompt="p",
        raw_output="r",
        parsed=None,
        failed=False,
        frame_url="/runs/rs1/_vlm_dumps/ep/_planner/call_000/frame.png",
        segment_ordinal=None,
        request_json=None,
        keyframe_urls=[],
    )
    assert c.call_id == "call_000"
    assert c.kind == "planner"
    assert c.attempt is None
    assert c.frame_url is not None
    assert c.keyframe_urls == []


def test_vlmcall_labeler_fields() -> None:
    c = VlmCall(
        call_id="s_001__attempt_1",
        kind="labeler",
        attempt=1,
        prompt="p",
        raw_output="{}",
        parsed={},
        failed=False,
        frame_url=None,
        segment_ordinal=1,
        request_json={"frames": [0]},
        keyframe_urls=["/runs/rs1/_vlm_dumps/ep/s_001/attempt_1/keyframe_000.png"],
    )
    assert c.kind == "labeler"
    assert c.segment_ordinal == 1
    assert c.attempt == 1
    assert len(c.keyframe_urls) == 1


# ---------------------------------------------------------------------------
# resolve_episode_id
# ---------------------------------------------------------------------------


def _write_index(run_set_root: Path, entries: list[dict[str, str]]) -> None:
    run_set_root.mkdir(parents=True, exist_ok=True)
    (run_set_root / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": entries,
    }))


def test_resolve_episode_id_happy(run_set_root: Path) -> None:
    _write_index(run_set_root, [
        {"manifest_url": "episode_000000__abc/manifest.json",
         "episode_id": "episode_000000"},
        {"manifest_url": "episode_000001__def/manifest.json",
         "episode_id": "episode_000001"},
    ])
    assert resolve_episode_id(
        run_set_root, "episode_000000__abc",
    ) == "episode_000000"
    assert resolve_episode_id(
        run_set_root, "episode_000001__def",
    ) == "episode_000001"


def test_resolve_episode_id_miss(run_set_root: Path) -> None:
    _write_index(run_set_root, [
        {"manifest_url": "episode_000000__abc/manifest.json",
         "episode_id": "episode_000000"},
    ])
    assert resolve_episode_id(run_set_root, "nope__deadbeef") is None


def test_resolve_episode_id_no_index_returns_none(run_set_root: Path) -> None:
    run_set_root.mkdir(parents=True)
    assert resolve_episode_id(run_set_root, "episode_000000__abc") is None


# ---------------------------------------------------------------------------
# HTTP route — GET /api/runs/{canonical}/vlm_dumps.json
# ---------------------------------------------------------------------------


from fastapi.testclient import TestClient  # noqa: E402


def _make_client(runs_root: Path) -> TestClient:
    from mimicanno.server.app import create_app
    return TestClient(create_app(runs_root=runs_root, cors_origins=[]))


def _setup_run_set(
    runs_root: Path,
    run_set: str,
    canonical: str,
    episode_id: str,
) -> Path:
    rs_root = runs_root / run_set
    rs_root.mkdir(parents=True)
    (rs_root / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": [
            {"manifest_url": f"{canonical}/manifest.json",
             "episode_id": episode_id},
        ],
    }))
    (rs_root / canonical).mkdir()
    return rs_root


def test_route_400_when_run_set_missing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    client = _make_client(runs_root)
    r = client.get("/api/runs/episode_000000__abc/vlm_dumps.json")
    assert r.status_code == 400
    assert r.json()["error"] == "run_set_required"


def test_route_404_when_canonical_not_in_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    _setup_run_set(runs_root, "rs1", "episode_000000__abc", "episode_000000")
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/unknown__deadbeef/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 404
    assert r.json()["error"] == "canonical_not_found"


def test_route_404_when_run_set_missing_dir(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=nope",
    )
    assert r.status_code == 404
    assert r.json()["error"] == "run_set_not_found"


def test_route_200_empty_calls_when_no_dump_dir(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    _setup_run_set(runs_root, "rs1", "episode_000000__abc", "episode_000000")
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "canonical": "episode_000000__abc",
        "run_set": "rs1",
        "episode_id": "episode_000000",
        "calls": [],
    }


def test_route_200_planner_shape(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    rs = _setup_run_set(
        runs_root, "rs1", "episode_000000__abc", "episode_000000"
    )
    ep_dir = rs / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, json.dumps({"objects": ["tape"]}))

    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["calls"]) == 1
    planner = body["calls"][0]
    assert planner["kind"] == "planner"
    # Rev3: call_id must NOT have "_planner/" prefix
    assert planner["call_id"] == "call_000"
    assert planner["parsed"] == {"objects": ["tape"]}
    assert planner["failed"] is False
    assert planner["frame_url"] is not None
    assert planner["segment_ordinal"] is None
    assert planner["request_json"] is None
    assert planner["keyframe_urls"] == []
    # Rev2 fields must NOT be present
    assert "phase" not in planner
    assert "segment_id" not in planner
    assert "ms" not in planner
    assert "model_variant" not in planner


def test_route_200_labeler_shape(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    rs = _setup_run_set(
        runs_root, "rs1", "episode_000000__abc", "episode_000000"
    )
    ep_dir = rs / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(
        ep_dir, "s_001", 1,
        json.dumps({"phase": "approach_object", "vlm_confidence": 0.9}),
        request_json=json.dumps({"frames": [0, 1]}),
        keyframes=2,
    )

    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["calls"]) == 1
    seg = body["calls"][0]
    assert seg["kind"] == "labeler"
    # Rev3: call_id uses double underscore
    assert seg["call_id"] == "s_001__attempt_1"
    assert seg["segment_ordinal"] == 1
    assert seg["attempt"] == 1
    assert seg["failed"] is False
    assert seg["frame_url"] is None
    assert seg["request_json"] == {"frames": [0, 1]}
    assert len(seg["keyframe_urls"]) == 2
    # Rev2 fields must NOT be present
    assert "phase" not in seg
    assert "segment_id" not in seg
    assert "ms" not in seg
    assert "model_variant" not in seg


def test_route_200_failed_attempt_present(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    rs = _setup_run_set(
        runs_root, "rs1", "episode_000000__abc", "episode_000000"
    )
    ep_dir = rs / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_labeler(ep_dir, "s_001", 1, json.dumps({"phase": "first"}))
    _write_labeler(ep_dir, "s_001", 2, json.dumps({"phase": "second"}))

    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    calls = r.json()["calls"]
    assert len(calls) == 2
    # Both attempts present; first is failed
    by_attempt = {c["attempt"]: c for c in calls}
    assert by_attempt[1]["failed"] is True
    assert by_attempt[2]["failed"] is False


def test_route_registered_before_catch_all(tmp_path: Path) -> None:
    """vlm_dumps.json must be served by its own handler, not the catch-all."""
    runs_root = tmp_path / "runs"
    _setup_run_set(runs_root, "rs1", "episode_000000__abc", "episode_000000")
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("episode_id") == "episode_000000"
    assert body.get("canonical") == "episode_000000__abc"
    assert body.get("run_set") == "rs1"
    assert "calls" in body


def test_route_rejects_parent_traversal(tmp_path: Path) -> None:
    """run_set='..' must 400, not silently read parent-of-runs index."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (tmp_path / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": [{"manifest_url": "secret/manifest.json",
                  "episode_id": "secret"}],
    }))
    client = _make_client(runs_root)
    r = client.get("/api/runs/secret/vlm_dumps.json?run_set=..")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_run_set"
