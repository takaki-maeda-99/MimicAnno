"""Tests for /api/hands/ routes (hands_routes.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_HANDS = PROJECT_ROOT / "tests" / "server" / "fixtures" / "hands"


def _make_app(hands_root=FIXTURE_HANDS, repo_root=PROJECT_ROOT):
    from mimicanno.server.app import create_app
    from mimicanno.server.runs_repo import RunsRepository

    # Use the existing fixture runs_root from conftest to keep create_app happy
    runs_root = PROJECT_ROOT / "tests" / "server" / "fixtures" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    # Minimal index so runs_root is valid
    idx = runs_root / "index.json"
    if not idx.exists():
        idx.write_text('{"schema_version":"0.1.0","runs":[]}')

    return create_app(
        runs_root=runs_root,
        cors_origins=[],
        hands_root=hands_root,
        repo_root=repo_root,
    )


@pytest.fixture
def client():
    app = _make_app()
    return TestClient(app)


@pytest.fixture
def client_no_hands():
    app = _make_app(hands_root=None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# index.json

def test_index_returns_episodes(client):
    r = client.get("/api/hands/index.json")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == "0.1.0"
    ids = [e["episode_id"] for e in data["episodes"]]
    assert "GX010085" in ids


def test_index_signals_ready_true(client):
    r = client.get("/api/hands/index.json")
    ep = next(e for e in r.json()["episodes"] if e["episode_id"] == "GX010085")
    assert ep["signals_ready"] is True


def test_index_no_hands_root(client_no_hands):
    r = client_no_hands.get("/api/hands/index.json")
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# meta.json

def test_meta_ok(client):
    r = client.get("/api/hands/GX010085/meta.json")
    assert r.status_code == 200
    data = r.json()
    assert data["video_fps"] == 30.0


def test_meta_no_hands_root(client_no_hands):
    r = client_no_hands.get("/api/hands/GX010085/meta.json")
    assert r.status_code == 503


def test_meta_not_found(client):
    r = client.get("/api/hands/DOES_NOT_EXIST/meta.json")
    assert r.status_code == 404


def test_meta_path_traversal(client):
    r = client.get("/api/hands/../meta.json")
    assert r.status_code in (400, 404)  # router may 404 on path mismatch


# ---------------------------------------------------------------------------
# signals.json

def test_signals_ok(client):
    r = client.get("/api/hands/GX010085/signals.json")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 2


def test_signals_no_hands_root(client_no_hands):
    r = client_no_hands.get("/api/hands/GX010085/signals.json")
    assert r.status_code == 503


def test_signals_not_found(client):
    r = client.get("/api/hands/DOES_NOT_EXIST/signals.json")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# video

def test_video_ok(client):
    r = client.get("/api/hands/GX010085/video")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")


def test_video_range_request(client):
    r = client.get("/api/hands/GX010085/video", headers={"Range": "bytes=0-99"})
    assert r.status_code in (200, 206)


def test_video_no_hands_root(client_no_hands):
    r = client_no_hands.get("/api/hands/GX010085/video")
    assert r.status_code == 503


def test_video_missing_source_key(tmp_path, client):
    """meta.json without video_source → 400."""
    # Write a temp episode with no video_source
    ep_dir = FIXTURE_HANDS / "_test_no_source"
    ep_dir.mkdir(exist_ok=True)
    (ep_dir / "meta.json").write_text('{"video_fps": 30.0}')
    try:
        app = _make_app()
        tc = TestClient(app)
        r = tc.get("/api/hands/_test_no_source/video")
        assert r.status_code == 400
        assert "video_source" in r.json()["error"]
    finally:
        import shutil
        shutil.rmtree(ep_dir, ignore_errors=True)


def test_video_source_outside_repo(tmp_path):
    """video_source pointing outside repo_root → 400."""
    ep_dir = tmp_path / "hands" / "ep0"
    ep_dir.mkdir(parents=True)
    (ep_dir / "meta.json").write_text(
        json.dumps({"video_source": "/etc/passwd", "video_fps": 30.0})
    )
    app = _make_app(hands_root=tmp_path / "hands", repo_root=tmp_path)
    tc = TestClient(app)
    r = tc.get("/api/hands/ep0/video")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# episode path validation

def test_episode_double_dot(client):
    r = client.get("/api/hands/..%2Fetc/signals.json")
    assert r.status_code in (400, 404, 422)


def test_episode_empty_string_signals(client):
    # FastAPI won't match empty path segment to {episode}
    r = client.get("/api/hands//signals.json")
    assert r.status_code in (400, 404, 307, 422)
