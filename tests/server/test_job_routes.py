"""U-A1 B4+B7 — POST /api/jobs + GET/DELETE job routes tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.server.job_store import JobRecord, JobStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_dataset(data_root: Path, name: str, ep_count: int = 5) -> None:
    ds = data_root / name
    (ds / "meta").mkdir(parents=True)
    info = {
        "robot_type": "so101",
        "total_episodes": ep_count,
        "fps": 15,
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": {"observation.images.front": {"dtype": "video"}},
    }
    (ds / "meta" / "info.json").write_text(json.dumps(info))


def _make_robot_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("robot: so101\n")


def _make_client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    """Return (client, data_root, runs_root) with a basic SO101 dataset + robot config."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101")
    robot_cfg = tmp_path / "configs" / "robot" / "so101.yaml"
    _make_robot_config(robot_cfg)

    from mimicanno.server.app import create_app
    fastapi_app = create_app(
        runs_root=runs_root,
        cors_origins=[],
        jobs_dir=tmp_path / "jobs",
        data_root=data_root,
        repo_root=tmp_path,
    )
    return TestClient(fastapi_app), data_root, runs_root


def _valid_body(tmp_path: Path, extra: dict | None = None) -> dict:
    body: dict = {
        "kind": "annotate",
        "dataset": "SO101",
        "run_set": "so101_test_run",
        "robot_config": "configs/robot/so101.yaml",
        "pipeline_config": "configs/pipeline/phase4.yaml",
        "variant": "4B",
    }
    if extra:
        body.update(extra)
    return body


# ---------------------------------------------------------------------------
# B4 — POST /api/jobs
# ---------------------------------------------------------------------------

def test_post_job_valid_returns_202(tmp_path: Path) -> None:
    """Valid body → 202 with job_id and status queued."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    assert data["job_id"].startswith("j_")


def test_post_job_episode_indices_null_uses_all(tmp_path: Path) -> None:
    """episode_indices=null → all episodes resolved from info.json."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    body["episode_indices"] = None
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    # Verify job record has all 5 episodes
    store = JobStore(tmp_path / "jobs")
    rec = store.load(job_id)
    assert rec is not None
    assert rec.episode_indices == list(range(5))


def test_post_job_gpu_null_assigns_gpu_0(tmp_path: Path) -> None:
    """gpu_index null → server assigns GPU 0 (first/shortest queue)."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    body["gpu_index"] = None
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    store = JobStore(tmp_path / "jobs")
    rec = store.load(job_id)
    assert rec is not None
    assert rec.gpu_index == 0


def test_post_job_409_conflict_run_set_has_episodes(tmp_path: Path) -> None:
    """409 when run_set already has overlapping episodes."""
    client, data_root, runs_root = _make_client(tmp_path)
    # Pre-create run_set index with episode_000000
    rs_dir = runs_root / "so101_test_run"
    rs_dir.mkdir()
    index = {
        "schema_version": "0.1.0",
        "runs": [{
            "episode_id": "episode_000000",
            "canonical_name": "episode_000000__abc123",
            "run_hash": "sha256:" + "a" * 64,
            "generated_at": "2026-05-17T10:00:00Z",
        }],
    }
    (rs_dir / "index.json").write_text(json.dumps(index))
    body = _valid_body(tmp_path, {"episode_indices": [0, 1]})
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 409


def test_post_job_400_dataset_not_found(tmp_path: Path) -> None:
    """400 when dataset doesn't exist."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    body["dataset"] = "NONEXISTENT"
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 400


def test_post_job_400_robot_config_missing(tmp_path: Path) -> None:
    """400 when robot_config file doesn't exist."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    body["robot_config"] = "configs/robot/does_not_exist.yaml"
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 400


def test_post_job_missing_required_fields(tmp_path: Path) -> None:
    """Missing dataset field → 400 (our validation) or 415 if no content-type."""
    client, data_root, runs_root = _make_client(tmp_path)
    resp = client.post(
        "/api/jobs",
        content=json.dumps({"run_set": "x", "robot_config": "y", "pipeline_config": "z"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_post_job_invalid_variant(tmp_path: Path) -> None:
    """Invalid variant → 400."""
    client, data_root, runs_root = _make_client(tmp_path)
    body = _valid_body(tmp_path)
    body["variant"] = "invalid"
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# B7 — GET /api/jobs, GET /api/jobs/{id}, GET /api/jobs/{id}/log, DELETE
# ---------------------------------------------------------------------------

def test_get_jobs_returns_all(tmp_path: Path) -> None:
    """GET /api/jobs returns all jobs."""
    client, data_root, runs_root = _make_client(tmp_path)
    # Submit two jobs
    client.post("/api/jobs", json=_valid_body(tmp_path))
    body2 = _valid_body(tmp_path)
    body2["run_set"] = "so101_run2"
    client.post("/api/jobs", json=body2)
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2


def test_get_jobs_status_filter(tmp_path: Path) -> None:
    """GET /api/jobs?status=queued filters correctly."""
    client, data_root, runs_root = _make_client(tmp_path)
    client.post("/api/jobs", json=_valid_body(tmp_path))
    resp = client.get("/api/jobs?status=queued")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "queued"

    resp2 = client.get("/api/jobs?status=running")
    assert resp2.json() == []


def test_get_job_by_id(tmp_path: Path) -> None:
    """GET /api/jobs/{id} returns full detail with log_tail."""
    client, data_root, runs_root = _make_client(tmp_path)
    post_resp = client.post("/api/jobs", json=_valid_body(tmp_path))
    job_id = post_resp.json()["job_id"]
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "queued"
    assert "log_tail" in data
    assert "log_url" in data
    assert data["log_url"] == f"/api/jobs/{job_id}/log"


def test_get_job_log_returns_text(tmp_path: Path) -> None:
    """GET /api/jobs/{id}/log returns text/plain."""
    client, data_root, runs_root = _make_client(tmp_path)
    post_resp = client.post("/api/jobs", json=_valid_body(tmp_path))
    job_id = post_resp.json()["job_id"]
    resp = client.get(f"/api/jobs/{job_id}/log")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_get_job_404_unknown_id(tmp_path: Path) -> None:
    """GET /api/jobs/unknown → 404."""
    client, data_root, runs_root = _make_client(tmp_path)
    resp = client.get("/api/jobs/j_20260517_000000_zzzz")
    assert resp.status_code == 404


def test_delete_job_queued_removes_record(tmp_path: Path) -> None:
    """DELETE /api/jobs/{id} for queued job → 204 and record deleted."""
    client, data_root, runs_root = _make_client(tmp_path)
    post_resp = client.post("/api/jobs", json=_valid_body(tmp_path))
    job_id = post_resp.json()["job_id"]
    resp = client.delete(f"/api/jobs/{job_id}")
    assert resp.status_code == 204
    # Verify record gone
    get_resp = client.get(f"/api/jobs/{job_id}")
    assert get_resp.status_code == 404


def test_delete_job_404_unknown_id(tmp_path: Path) -> None:
    """DELETE on nonexistent job → 404."""
    client, data_root, runs_root = _make_client(tmp_path)
    resp = client.delete("/api/jobs/j_20260517_000000_zzzz")
    assert resp.status_code == 404
