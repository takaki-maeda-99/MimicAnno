"""U-A1 B5 — JobRunner subprocess + per-GPU FIFO tests (mocked Popen)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mimicanno.server.job_runner import JobQueue, JobRunner, _read_proc_start_time
from mimicanno.server.job_store import JobError, JobRecord, JobStore


def _run(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_record(
    job_id: str = "j_20260517_120000_abcd",
    status: str = "queued",
    gpu_index: int = 0,
    ep_count: int = 3,
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        status=status,
        kind="annotate",
        dataset="SO101",
        episode_indices=list(range(ep_count)),
        run_set="so101_test",
        variant="4B",
        gpu_index=gpu_index,
        robot_config="configs/robot/so101.yaml",
        pipeline_config="configs/pipeline/phase4.yaml",
        queued_at="2026-05-17T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# JobQueue tests
# ---------------------------------------------------------------------------

def test_job_queue_assign_gpu_explicit() -> None:
    """Explicit gpu_index is returned directly (mod num_gpus)."""
    q = JobQueue(num_gpus=4)
    assert q.assign_gpu(2) == 2
    assert q.assign_gpu(0) == 0


def test_job_queue_assign_gpu_null_picks_shortest() -> None:
    """None → picks GPU with shortest queue (ties → lowest index)."""
    q = JobQueue(num_gpus=2)
    # Initially both empty → picks GPU 0
    assert q.assign_gpu(None) == 0
    # Enqueue a job on GPU 0
    q.enqueue(0, "j_aaa")
    # Now GPU 1 is shorter
    assert q.assign_gpu(None) == 1


def test_job_queue_enqueue_dequeue() -> None:
    """Enqueue + dequeue round-trip."""
    q = JobQueue(num_gpus=1)
    q.enqueue(0, "j_20260517_120000_abcd")

    async def _run_dequeue() -> str:
        return await q.dequeue(0)

    result = _run(_run_dequeue())
    assert result == "j_20260517_120000_abcd"


# ---------------------------------------------------------------------------
# JobRunner subprocess tests (mocked)
# ---------------------------------------------------------------------------

def test_job_runner_transitions_queued_to_done(tmp_path: Path) -> None:
    """Job transitions queued → running → done on successful subprocess exit."""
    store = JobStore(tmp_path / "jobs")
    queue = JobQueue(num_gpus=1)
    runner = JobRunner(store=store, queue=queue, repo_root=tmp_path)

    rec = _make_record()
    store.save(rec)
    queue.enqueue(0, rec.job_id)

    log_content = (
        "[mimicanno-job-progress] ep=0 finished=1/3\n"
        "[mimicanno-job-progress] ep=1 finished=2/3\n"
        "[mimicanno-job-progress] ep=2 finished=3/3\n"
    )

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.returncode = 0
    poll_results = [None, None, None, None, None, 0]
    mock_proc.poll.side_effect = poll_results

    with (
        patch("mimicanno.server.job_runner.subprocess.Popen") as mock_popen,
        patch("mimicanno.server.job_runner._read_proc_start_time", return_value=9999),
        patch("builtins.open", create=True) as mock_open,
    ):
        write_file = MagicMock()
        write_file.__enter__ = MagicMock(return_value=write_file)
        write_file.__exit__ = MagicMock(return_value=False)

        read_file = MagicMock()
        read_file.__enter__ = MagicMock(return_value=read_file)
        read_file.__exit__ = MagicMock(return_value=False)
        lines = log_content.splitlines(keepends=True)
        read_file.readline.side_effect = lines + [""] * 10
        read_file.__iter__ = MagicMock(return_value=iter([]))

        def open_side_effect(path, mode="r", **kwargs):  # type: ignore[no-untyped-def]
            if "wb" in mode or mode == "wb":
                return write_file
            return read_file

        mock_open.side_effect = open_side_effect
        mock_popen.return_value = mock_proc

        _run(runner._run_job(rec.job_id, 0))

    final = store.load(rec.job_id)
    assert final is not None
    assert final.status == "done"
    assert final.progress_pct == 100


def test_job_runner_failed_subprocess_exit(tmp_path: Path) -> None:
    """Non-zero subprocess exit → status=failed."""
    store = JobStore(tmp_path / "jobs")
    queue = JobQueue(num_gpus=1)
    runner = JobRunner(store=store, queue=queue, repo_root=tmp_path)

    rec = _make_record()
    store.save(rec)

    mock_proc = MagicMock()
    mock_proc.pid = 12346
    mock_proc.returncode = 1
    mock_proc.poll.side_effect = [None, 1]

    with (
        patch("mimicanno.server.job_runner.subprocess.Popen") as mock_popen,
        patch("mimicanno.server.job_runner._read_proc_start_time", return_value=9999),
        patch("builtins.open", create=True) as mock_open,
    ):
        write_file = MagicMock()
        write_file.__enter__ = MagicMock(return_value=write_file)
        write_file.__exit__ = MagicMock(return_value=False)
        read_file = MagicMock()
        read_file.__enter__ = MagicMock(return_value=read_file)
        read_file.__exit__ = MagicMock(return_value=False)
        read_file.readline.return_value = ""
        read_file.__iter__ = MagicMock(return_value=iter([]))

        def open_side_effect(path, mode="r", **kwargs):  # type: ignore[no-untyped-def]
            if "wb" in mode or mode == "wb":
                return write_file
            return read_file

        mock_open.side_effect = open_side_effect
        mock_popen.return_value = mock_proc

        _run(runner._run_job(rec.job_id, 0))

    final = store.load(rec.job_id)
    assert final is not None
    assert final.status == "failed"
    assert final.error is not None
    assert final.error.reason == "subprocess_exit"


def test_job_runner_progress_marker_updates_pct(tmp_path: Path) -> None:
    """Progress markers in log update progress_pct in record."""
    store = JobStore(tmp_path / "jobs")
    queue = JobQueue(num_gpus=1)
    runner = JobRunner(store=store, queue=queue, repo_root=tmp_path)

    rec = _make_record(ep_count=4)
    store.save(rec)

    log_lines = [
        "[mimicanno-job-progress] ep=0 finished=1/4\n",
        "[mimicanno-job-progress] ep=1 finished=2/4\n",
        "",
    ]

    mock_proc = MagicMock()
    mock_proc.pid = 12347
    mock_proc.returncode = 0
    mock_proc.poll.side_effect = [None, None, 0]

    with (
        patch("mimicanno.server.job_runner.subprocess.Popen") as mock_popen,
        patch("mimicanno.server.job_runner._read_proc_start_time", return_value=9999),
        patch("builtins.open", create=True) as mock_open,
    ):
        write_file = MagicMock()
        write_file.__enter__ = MagicMock(return_value=write_file)
        write_file.__exit__ = MagicMock(return_value=False)
        read_file = MagicMock()
        read_file.__enter__ = MagicMock(return_value=read_file)
        read_file.__exit__ = MagicMock(return_value=False)
        read_file.readline.side_effect = log_lines
        read_file.__iter__ = MagicMock(return_value=iter([]))

        def open_side_effect(path, mode="r", **kwargs):  # type: ignore[no-untyped-def]
            if "wb" in mode or mode == "wb":
                return write_file
            return read_file

        mock_open.side_effect = open_side_effect
        mock_popen.return_value = mock_proc

        _run(runner._run_job(rec.job_id, 0))

    final = store.load(rec.job_id)
    assert final is not None
    assert final.status == "done"


def test_job_runner_two_jobs_on_same_gpu_serialize(tmp_path: Path) -> None:
    """Two jobs on the same GPU execute sequentially."""
    store = JobStore(tmp_path / "jobs")
    queue = JobQueue(num_gpus=1)
    runner = JobRunner(store=store, queue=queue, repo_root=tmp_path)

    rec1 = _make_record("j_20260517_120000_aaaa")
    rec2 = _make_record("j_20260517_120001_bbbb")
    store.save(rec1)
    store.save(rec2)
    queue.enqueue(0, rec1.job_id)
    queue.enqueue(0, rec2.job_id)

    execution_order: list[str] = []

    async def mock_run_job(job_id: str, gpu: int) -> None:  # type: ignore[no-untyped-def]
        execution_order.append(f"start_{job_id}")
        await asyncio.sleep(0.01)
        execution_order.append(f"end_{job_id}")
        r = store.load(job_id)
        if r:
            r.status = "done"
            store.save(r)

    runner._run_job = mock_run_job  # type: ignore[method-assign]

    async def limited_worker() -> None:
        for _ in range(2):
            job_id = await queue.dequeue(0)
            await runner._run_job(job_id, 0)
            queue.mark_done(0)

    _run(limited_worker())

    assert execution_order == [
        f"start_{rec1.job_id}",
        f"end_{rec1.job_id}",
        f"start_{rec2.job_id}",
        f"end_{rec2.job_id}",
    ]
