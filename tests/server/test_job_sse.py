"""U-A1 B8 — SSE /api/jobs/{id}/stream tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.server.job_store import JobRecord, JobStore


def _make_client(tmp_path: Path) -> TestClient:
    import json as _json
    from mimicanno.server.app import create_app
    data_root = tmp_path / "data"
    (data_root / "SO101" / "meta").mkdir(parents=True)
    info = {"robot_type": "so101", "total_episodes": 2, "fps": 15,
            "data_path": "data/chunk-000/episode_{episode_index:06d}.parquet",
            "video_path": "videos/{video_key}/chunk-000/episode_{episode_index:06d}.mp4",
            "features": {"observation.images.front": {"dtype": "video"}}}
    (data_root / "SO101" / "meta" / "info.json").write_text(_json.dumps(info))
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    fastapi_app = create_app(
        runs_root=runs_root,
        cors_origins=[],
        jobs_dir=tmp_path / "jobs",
        data_root=data_root,
    )
    return TestClient(fastapi_app)


def _make_done_record(jobs_dir: Path, status: str = "done") -> JobRecord:
    rec = JobRecord(
        job_id="j_20260517_120000_abcd",
        status=status,
        kind="annotate",
        dataset="SO101",
        episode_indices=[0, 1],
        run_set="so101_test",
        variant="4B",
        gpu_index=0,
        robot_config="configs/robot/so101.yaml",
        pipeline_config="configs/pipeline/phase4.yaml",
        queued_at="2026-05-17T12:00:00Z",
        started_at="2026-05-17T12:00:01Z",
        finished_at="2026-05-17T12:01:00Z",
        progress_pct=100,
        run_canonicals=["episode_000000__abc123"],
    )
    store = JobStore(jobs_dir)
    store.save(rec)
    return rec


def test_sse_closed_job_sends_done_event(tmp_path: Path) -> None:
    """Closed (done) job → sends immediate done event + closes stream."""
    client = _make_client(tmp_path)
    rec = _make_done_record(tmp_path / "jobs", status="done")

    with client.stream("GET", f"/api/jobs/{rec.job_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        content = resp.read().decode("utf-8")

    # Should contain "event: done" line
    assert "event: done" in content
    assert "final_status" in content


def test_sse_closed_failed_job_sends_failed_event(tmp_path: Path) -> None:
    """Closed (failed) job → sends failed event."""
    client = _make_client(tmp_path)
    rec = _make_done_record(tmp_path / "jobs", status="failed")

    with client.stream("GET", f"/api/jobs/{rec.job_id}/stream") as resp:
        content = resp.read().decode("utf-8")

    assert "event: failed" in content


def test_sse_unknown_job_id_returns_404(tmp_path: Path) -> None:
    """Unknown job_id → 404."""
    client = _make_client(tmp_path)
    resp = client.get("/api/jobs/j_20260517_000000_zzzz/stream")
    assert resp.status_code == 404
