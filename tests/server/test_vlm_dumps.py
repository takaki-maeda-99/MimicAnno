"""U-A3 — tests for `mimicanno.server.vlm_dumps` reader.

Covers tree walk, attempt selection, malformed JSON, and
`resolve_episode_id` index lookup. Route tests live below in this file
once S2 lands.
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


def _write_planner(ep_dir: Path, call_idx: int, response: str | None,
                   prompt: str = "planner-prompt") -> None:
    call_dir = ep_dir / "_planner" / f"call_{call_idx:03d}"
    call_dir.mkdir(parents=True)
    (call_dir / "prompt.txt").write_text(prompt)
    if response is not None:
        (call_dir / "response.txt").write_text(response)
    # frame.png omitted in tests; reader does not need it


def _write_segment(ep_dir: Path, seg_id: str, attempt: int,
                   response: str | None,
                   prompt: str = "seg-prompt") -> None:
    seg_dir = ep_dir / seg_id / f"attempt_{attempt}"
    seg_dir.mkdir(parents=True)
    (seg_dir / "prompt.txt").write_text(prompt)
    if response is not None:
        (seg_dir / "response.txt").write_text(response)


@pytest.fixture
def run_set_root(tmp_path: Path) -> Path:
    return tmp_path / "runs" / "rs1"


# ---------------------------------------------------------------------------
# read_vlm_dumps
# ---------------------------------------------------------------------------


def test_read_empty_returns_empty_list(run_set_root: Path) -> None:
    (run_set_root / "_vlm_dumps").mkdir(parents=True)
    assert read_vlm_dumps(run_set_root, "episode_000000") == []


def test_read_missing_dir_returns_empty_list(run_set_root: Path) -> None:
    run_set_root.mkdir(parents=True)
    # no _vlm_dumps/ at all
    assert read_vlm_dumps(run_set_root, "episode_000000") == []


def test_happy_path_planner_plus_two_segments(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, json.dumps(
        {"objects": ["tape", "bottle"], "targets": [], "tools": []},
    ))
    _write_segment(ep_dir, "s_001", 1, json.dumps(
        {"phase": "approach_object", "verb": None, "object": "tape",
         "target": None, "vlm_confidence": 0.9, "evidence": "..."},
    ))
    _write_segment(ep_dir, "s_002", 1, json.dumps(
        {"phase": "grasp_object", "verb": "grasp", "object": "tape",
         "target": None, "vlm_confidence": 0.8, "evidence": "..."},
    ))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 3

    # Planner first, then segments sorted by segment_id
    assert calls[0].kind == "planner"
    assert calls[0].call_id == "_planner/call_000"
    assert calls[0].segment_id is None
    assert calls[0].phase is None
    assert calls[0].parsed == {
        "objects": ["tape", "bottle"], "targets": [], "tools": [],
    }
    assert calls[0].failed is False

    assert calls[1].kind == "segment"
    assert calls[1].call_id == "s_001/attempt_1"
    assert calls[1].segment_id == "s_001"
    assert calls[1].phase == "approach_object"
    assert calls[1].failed is False

    assert calls[2].kind == "segment"
    assert calls[2].segment_id == "s_002"
    assert calls[2].phase == "grasp_object"


def test_highest_attempt_wins(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_segment(ep_dir, "s_001", 1, json.dumps({"phase": "approach_object"}))
    _write_segment(ep_dir, "s_001", 2, json.dumps({"phase": "grasp_object"}))
    _write_segment(ep_dir, "s_001", 3, json.dumps({"phase": "lift_object"}))

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 1
    assert calls[0].call_id == "s_001/attempt_3"
    assert calls[0].phase == "lift_object"


def test_malformed_segment_response_marks_failed(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_segment(ep_dir, "s_001", 1, "not-json-at-all")

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 1
    assert calls[0].kind == "segment"
    assert calls[0].parsed is None
    assert calls[0].failed is True
    assert calls[0].phase is None
    assert calls[0].raw_output == "not-json-at-all"


def test_missing_segment_response_marks_failed(run_set_root: Path) -> None:
    ep_dir = run_set_root / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_segment(ep_dir, "s_001", 1, response=None)

    calls = read_vlm_dumps(run_set_root, "episode_000000")
    assert len(calls) == 1
    assert calls[0].failed is True
    assert calls[0].raw_output == ""
    assert calls[0].parsed is None


def test_call_is_dataclass_with_expected_fields() -> None:
    c = VlmCall(
        call_id="x", kind="planner", phase=None, segment_id=None,
        prompt="p", raw_output="r", parsed=None, failed=False,
        ms=None, model_variant=None,
    )
    assert c.ms is None and c.model_variant is None


# ---------------------------------------------------------------------------
# resolve_episode_id
# ---------------------------------------------------------------------------


def _write_index(run_set_root: Path, entries: list[dict[str, str]]) -> None:
    run_set_root.mkdir(parents=True, exist_ok=True)
    (run_set_root / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0", "runs": entries,
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


def _setup_run_set(runs_root: Path, run_set: str, canonical: str,
                   episode_id: str) -> Path:
    rs_root = runs_root / run_set
    rs_root.mkdir(parents=True)
    (rs_root / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": [
            {"manifest_url": f"{canonical}/manifest.json",
             "episode_id": episode_id},
        ],
    }))
    # Stub run dir so a future canonical existence check could be added
    (rs_root / canonical).mkdir()
    return rs_root


def test_route_400_when_run_set_missing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    client = _make_client(runs_root)
    r = client.get("/api/runs/episode_000000__abc/vlm_dumps.json")
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "run_set_required"


def test_route_404_when_canonical_not_in_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    rs = _setup_run_set(runs_root, "rs1", "episode_000000__abc",
                        "episode_000000")
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/unknown__deadbeef/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 404
    assert r.json()["error"] == "canonical_not_found"
    _ = rs  # silence unused


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
    _setup_run_set(runs_root, "rs1", "episode_000000__abc",
                   "episode_000000")
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


def test_route_200_happy_path_with_dumps(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    rs = _setup_run_set(runs_root, "rs1", "episode_000000__abc",
                        "episode_000000")
    ep_dir = rs / "_vlm_dumps" / "episode_000000"
    ep_dir.mkdir(parents=True)
    _write_planner(ep_dir, 0, json.dumps({"objects": ["tape"]}))
    _write_segment(ep_dir, "s_001", 1, json.dumps(
        {"phase": "approach_object", "vlm_confidence": 0.9},
    ))

    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["canonical"] == "episode_000000__abc"
    assert body["run_set"] == "rs1"
    assert body["episode_id"] == "episode_000000"
    assert len(body["calls"]) == 2
    planner = body["calls"][0]
    assert planner["kind"] == "planner"
    assert planner["call_id"] == "_planner/call_000"
    assert planner["parsed"] == {"objects": ["tape"]}
    seg = body["calls"][1]
    assert seg["kind"] == "segment"
    assert seg["segment_id"] == "s_001"
    assert seg["phase"] == "approach_object"
    assert seg["failed"] is False
    assert seg["ms"] is None
    assert seg["model_variant"] is None


def test_route_registered_before_catch_all(tmp_path: Path) -> None:
    """Registration-order regression: vlm_dumps.json must not be served by
    the /api/runs/{name}/{artifact} catch-all (which would return raw
    file bytes or 404 ``artifact_not_found``, NOT the vlm_dumps shape)."""
    runs_root = tmp_path / "runs"
    _setup_run_set(runs_root, "rs1", "episode_000000__abc",
                   "episode_000000")
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/episode_000000__abc/vlm_dumps.json?run_set=rs1",
    )
    assert r.status_code == 200
    body = r.json()
    # episode_id key is unique to the vlm_dumps handler — the catch-all
    # has no concept of it. canonical+run_set echo would also work; we
    # assert both for defence-in-depth.
    assert body.get("episode_id") == "episode_000000"
    assert body.get("canonical") == "episode_000000__abc"
    assert body.get("run_set") == "rs1"
    assert "calls" in body


def test_route_rejects_parent_traversal(tmp_path: Path) -> None:
    """run_set='..' must 400, not silently read parent-of-runs index."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # Plant a decoy index.json one level above runs_root.
    (tmp_path / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": [{"manifest_url": "secret/manifest.json",
                  "episode_id": "secret"}],
    }))
    client = _make_client(runs_root)
    r = client.get(
        "/api/runs/secret/vlm_dumps.json?run_set=..",
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_run_set"
