"""U-A1 B10 — CORS allow_methods includes POST and DELETE."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_client_with_cors(tmp_path: Path) -> TestClient:
    data_root = tmp_path / "data"
    (data_root / "SO101" / "meta").mkdir(parents=True)
    info = {"robot_type": "so101", "total_episodes": 1, "fps": 15,
            "data_path": "data/chunk-000/episode_{episode_index:06d}.parquet",
            "video_path": "videos/{video_key}/chunk-000/episode_{episode_index:06d}.mp4",
            "features": {"observation.images.front": {"dtype": "video"}}}
    (data_root / "SO101" / "meta" / "info.json").write_text(json.dumps(info))
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')

    from mimicanno.server.app import create_app
    fastapi_app = create_app(
        runs_root=runs_root,
        cors_origins=["http://localhost:5173"],
        jobs_dir=tmp_path / "jobs",
        data_root=data_root,
    )
    return TestClient(fastapi_app)


def test_cors_preflight_post_jobs_returns_allow_post(tmp_path: Path) -> None:
    """OPTIONS preflight for POST /api/jobs includes POST in allowed methods."""
    client = _make_client_with_cors(tmp_path)
    resp = client.options(
        "/api/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # 200 or 204 is valid CORS preflight response
    assert resp.status_code in (200, 204)
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods


def test_cors_preflight_delete_jobs_returns_allow_delete(tmp_path: Path) -> None:
    """OPTIONS preflight for DELETE /api/jobs/{id} includes DELETE in allowed methods."""
    client = _make_client_with_cors(tmp_path)
    resp = client.options(
        "/api/jobs/j_20260517_120000_abcd",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert resp.status_code in (200, 204)
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "DELETE" in allow_methods
