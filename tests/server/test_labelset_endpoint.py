"""Phase 5 B r1 T5: GET /api/labelset endpoint (spec §3.1)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_runs_root: Path) -> TestClient:
    from mimicanno.server.app import create_app
    return TestClient(create_app(runs_root=tmp_runs_root, cors_origins=[]))


def test_labelset_200_shape(tmp_runs_root: Path) -> None:
    """200 + body {labels: [{id, requires_object}], labels_yaml_sha256}."""
    r = _client(tmp_runs_root).get("/api/labelset")
    assert r.status_code == 200
    body = r.json()
    assert "labels" in body
    assert "labels_yaml_sha256" in body
    assert isinstance(body["labels"], list)
    assert len(body["labels"]) > 0
    for entry in body["labels"]:
        assert set(entry.keys()) == {"id", "requires_object"}
        assert isinstance(entry["id"], str)
        assert isinstance(entry["requires_object"], bool)


def test_labelset_etag_matches_sha256(tmp_runs_root: Path) -> None:
    """ETag header == quoted labels_yaml_sha256 (spec §5.1 #17)."""
    r = _client(tmp_runs_root).get("/api/labelset")
    assert r.status_code == 200
    expected = f'"{r.json()["labels_yaml_sha256"]}"'
    assert r.headers.get("etag") == expected


def test_labelset_cache_control_public_max_age_300(tmp_runs_root: Path) -> None:
    """Cache-Control: public, max-age=300 (spec §3.1 — labelset is
    immutable across the server's lifetime, ETag busts on restart)."""
    r = _client(tmp_runs_root).get("/api/labelset")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=300"
