"""U-A1 B9 — Server restart reclassification tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mimicanno.server.job_runner import reclassify_stale_running_jobs
from mimicanno.server.job_store import JobRecord, JobStore


def _make_running_record(
    jobs_dir: Path,
    job_id: str = "j_20260517_120000_abcd",
    pid: int = 99999,
    proc_start_time: int = 12345,
) -> JobRecord:
    rec = JobRecord(
        job_id=job_id,
        status="running",
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
        pid=pid,
        proc_start_time=proc_start_time,
    )
    store = JobStore(jobs_dir)
    store.save(rec)
    return rec


def test_reclassify_dead_pid_marks_failed(tmp_path: Path) -> None:
    """Running job with dead PID → reclassified as failed with server_restart reason."""
    jobs_dir = tmp_path / "jobs"
    rec = _make_running_record(jobs_dir, pid=99999, proc_start_time=12345)

    # Mock _is_process_alive to return False (PID dead)
    with patch("mimicanno.server.job_runner._is_process_alive", return_value=False):
        reclassify_stale_running_jobs(JobStore(jobs_dir))

    store = JobStore(jobs_dir)
    loaded = store.load(rec.job_id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.error is not None
    assert loaded.error.reason == "server_restart"
    assert loaded.finished_at is not None


def test_reclassify_live_pid_unchanged(tmp_path: Path) -> None:
    """Running job with live PID matching proc_start_time → unchanged."""
    jobs_dir = tmp_path / "jobs"
    rec = _make_running_record(jobs_dir, pid=99999, proc_start_time=12345)

    # Mock _is_process_alive to return True (PID alive)
    with patch("mimicanno.server.job_runner._is_process_alive", return_value=True):
        reclassify_stale_running_jobs(JobStore(jobs_dir))

    store = JobStore(jobs_dir)
    loaded = store.load(rec.job_id)
    assert loaded is not None
    assert loaded.status == "running"
    assert loaded.error is None
