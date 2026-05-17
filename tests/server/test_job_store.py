"""U-A1 B3 — JobRecord + JobStore tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.server.job_store import JobError, JobRecord, JobStore


def _make_record(job_id: str = "j_20260517_120000_abcd") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status="queued",
        kind="annotate",
        dataset="SO101",
        episode_indices=[0, 1, 2],
        run_set="so101_test",
        variant="4B",
        gpu_index=0,
        robot_config="configs/robot/so101.yaml",
        pipeline_config="configs/pipeline/phase4.yaml",
        queued_at="2026-05-17T12:00:00Z",
    )


def test_job_store_save_and_load(tmp_path: Path) -> None:
    """Write + read round-trip preserves all fields."""
    store = JobStore(tmp_path / "jobs")
    rec = _make_record()
    store.save(rec)
    loaded = store.load(rec.job_id)
    assert loaded is not None
    assert loaded.job_id == rec.job_id
    assert loaded.status == "queued"
    assert loaded.dataset == "SO101"
    assert loaded.episode_indices == [0, 1, 2]
    assert loaded.run_set == "so101_test"


def test_job_store_list_all_no_filter(tmp_path: Path) -> None:
    """list_all with no filter returns all records."""
    store = JobStore(tmp_path / "jobs")
    store.save(_make_record("j_20260517_120000_aaa1"))
    r2 = _make_record("j_20260517_120001_aaa2")
    r2.status = "done"
    store.save(r2)
    records = store.list_all()
    assert len(records) == 2


def test_job_store_list_all_with_status_filter(tmp_path: Path) -> None:
    """list_all with status filter returns only matching records."""
    store = JobStore(tmp_path / "jobs")
    store.save(_make_record("j_20260517_120000_aaa1"))
    r2 = _make_record("j_20260517_120001_aaa2")
    r2.status = "done"
    store.save(r2)
    running_only = store.list_all(status_filter=["running"])
    assert running_only == []
    done_only = store.list_all(status_filter=["done"])
    assert len(done_only) == 1
    assert done_only[0].job_id == "j_20260517_120001_aaa2"


def test_job_store_atomic_write(tmp_path: Path) -> None:
    """Atomic write: no .tmp files left behind."""
    store = JobStore(tmp_path / "jobs")
    rec = _make_record()
    store.save(rec)
    tmp_files = list((tmp_path / "jobs").glob("*.tmp.*"))
    assert tmp_files == []
    json_files = list((tmp_path / "jobs").glob("*.json"))
    assert len(json_files) == 1


def test_job_store_log_tail(tmp_path: Path) -> None:
    """read_log_tail returns last 200 lines from log file."""
    store = JobStore(tmp_path / "jobs")
    job_id = "j_20260517_120000_abcd"
    # Write 250 lines
    lines = [f"line {i}" for i in range(250)]
    store.append_log(job_id, "\n".join(lines) + "\n")
    tail = store.read_log_tail(job_id)
    assert len(tail) == 200
    assert tail[0] == "line 50"  # first of last 200
    assert tail[-1] == "line 249"


def test_job_store_load_nonexistent(tmp_path: Path) -> None:
    """Loading a nonexistent job returns None."""
    store = JobStore(tmp_path / "jobs")
    assert store.load("j_20260517_120000_zzzz") is None


def test_job_store_error_serialization(tmp_path: Path) -> None:
    """JobError round-trips through save/load."""
    store = JobStore(tmp_path / "jobs")
    rec = _make_record()
    rec.status = "failed"
    rec.error = JobError(reason="server_restart")
    store.save(rec)
    loaded = store.load(rec.job_id)
    assert loaded is not None
    assert loaded.error is not None
    assert loaded.error.reason == "server_restart"
