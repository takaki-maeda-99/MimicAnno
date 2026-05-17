"""U-A1 — Subprocess job runner + per-GPU FIFO queue (spec §5).

Design:
- ``JobQueue`` manages per-GPU asyncio.Queue objects.
- ``JobRunner`` runs as a background asyncio task, pulling from queues and
  spawning ``scripts/batch_annotate_4B.py`` via subprocess.
- Progress markers in stdout: ``[mimicanno-job-progress] ep=<idx> finished=<k>/<total>``
- Job state updates go through JobStore.
- SIGTERM on cancel.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mimicanno.server.job_store import JobError, JobRecord, JobStore

_LOG = logging.getLogger("mimicanno.server")

_PROGRESS_RE = re.compile(
    r"\[mimicanno-job-progress\] ep=(\d+) finished=(\d+)/(\d+)"
)

# How often to read new lines from log (seconds)
_TAIL_POLL_SEC = 0.5

# Keepalive / SSE heartbeat interval
SSE_KEEPALIVE_SEC = 15


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_proc_start_time(pid: int) -> int | None:
    """Read /proc/<pid>/stat field 22 (starttime in clock ticks).

    Returns None if the process doesn't exist or /proc is not available.
    """
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return None
        content = stat_path.read_text(encoding="ascii")
        # Field 22 is the start_time; fields are space-separated but comm (2)
        # can contain spaces and is wrapped in parens.
        # Find the last ')' to skip the comm field.
        rparen = content.rfind(")")
        if rparen < 0:
            return None
        rest = content[rparen + 2:]  # skip ') '
        fields = rest.split()
        # Field 22 is index 20 in 0-indexed rest (after removing fields 1+2)
        # Fields after comm: state(3), ppid(4), ..., starttime(22)
        # Index in rest: 22 - 3 = 19
        if len(fields) >= 20:
            return int(fields[19])
    except Exception:
        pass
    return None


def _is_process_alive(pid: int, proc_start_time: int) -> bool:
    """Return True iff /proc/<pid>/stat field 22 matches proc_start_time."""
    current = _read_proc_start_time(pid)
    return current is not None and current == proc_start_time


class JobQueue:
    """Per-GPU FIFO queues. gpu_index=None → assign shortest queue."""

    def __init__(self, num_gpus: int = 1) -> None:
        self._num_gpus = max(1, num_gpus)
        self._queues: dict[int, asyncio.Queue[str]] = {
            i: asyncio.Queue() for i in range(self._num_gpus)
        }
        # Active job per GPU (None = idle)
        self._active: dict[int, str | None] = {i: None for i in range(self._num_gpus)}

    def assign_gpu(self, gpu_index: int | None) -> int:
        """Assign a GPU index. None → shortest queue (ties → lowest index)."""
        if gpu_index is not None:
            return gpu_index % self._num_gpus
        # Find GPU with smallest queue size (count in queue + 1 if active)
        best_gpu = 0
        best_len = float("inf")
        for i in range(self._num_gpus):
            q_len = self._queues[i].qsize() + (1 if self._active[i] is not None else 0)
            if q_len < best_len:
                best_len = q_len
                best_gpu = i
        return best_gpu

    def enqueue(self, gpu_index: int, job_id: str) -> None:
        self._queues[gpu_index].put_nowait(job_id)

    async def dequeue(self, gpu_index: int) -> str:
        job_id = await self._queues[gpu_index].get()
        self._active[gpu_index] = job_id
        return job_id

    def mark_done(self, gpu_index: int) -> None:
        self._active[gpu_index] = None

    def num_gpus(self) -> int:
        return self._num_gpus


class JobRunner:
    """Manages subprocess execution for annotate jobs."""

    def __init__(
        self,
        store: JobStore,
        queue: JobQueue,
        repo_root: Path,
    ) -> None:
        self._store = store
        self._queue = queue
        self._repo_root = repo_root
        # pid → asyncio.subprocess.Process for cancel support
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        # SSE subscriber queues: job_id → list of asyncio.Queue
        self._sse_subs: dict[str, list[asyncio.Queue[dict[str, object] | None]]] = {}

    def subscribe_sse(
        self, job_id: str
    ) -> asyncio.Queue[dict[str, object] | None]:
        q: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._sse_subs.setdefault(job_id, []).append(q)
        return q

    def unsubscribe_sse(
        self, job_id: str, q: asyncio.Queue[dict[str, object] | None]
    ) -> None:
        subs = self._sse_subs.get(job_id, [])
        try:
            subs.remove(q)
        except ValueError:
            pass

    def _publish_sse(self, job_id: str, event: dict[str, object]) -> None:
        for q in self._sse_subs.get(job_id, []):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _publish_sse_done(self, job_id: str) -> None:
        """Signal end of stream to all subscribers."""
        for q in self._sse_subs.get(job_id, []):
            try:
                q.put_nowait(None)  # sentinel
            except asyncio.QueueFull:
                pass

    async def cancel_job(self, job_id: str) -> bool:
        """Send SIGTERM to the running process. Returns True if found."""
        proc = self._procs.get(job_id)
        if proc is not None and proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            rec = self._store.load(job_id)
            if rec is not None:
                rec.status = "cancelled"
                rec.finished_at = _now_iso()
                self._store.save(rec)
            self._publish_sse_done(job_id)
            return True
        return False

    def _build_command(self, record: JobRecord) -> list[str]:
        """Build the subprocess command for a job."""
        # Use scripts/batch_annotate_4B.py for 4B variant
        # The script is invoked with the repo python / uv run
        script = self._repo_root / "scripts" / "batch_annotate_4B.py"
        # For now, we invoke via uv run python <script>
        # Pass dataset, gpu, and episode range via env vars + args
        # The actual script accepts --dataset and --gpu flags.
        # We pass episode range via MIMICANNO_EP_START/END env vars
        # (which batch_annotate_4B.py reads if present).
        return [
            sys.executable, str(script),
            "--dataset", record.dataset,
            "--gpu", str(record.gpu_index),
        ]

    async def _run_job(self, job_id: str, gpu_index: int) -> None:
        record = self._store.load(job_id)
        if record is None:
            _LOG.warning("job %s not found in store; skipping", job_id)
            return

        # Update to running
        record.status = "running"
        record.started_at = _now_iso()
        self._store.save(record)
        self._publish_sse(job_id, {"type": "status", "status": "running"})

        log_path = self._store.log_path(job_id)
        total = len(record.episode_indices)

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(record.gpu_index)
        # Pass episode indices info to the script via env vars
        if record.episode_indices:
            env["MIMICANNO_EP_INDICES"] = ",".join(str(i) for i in record.episode_indices)
        env["BATCH_RUNS_ROOT"] = str(self._repo_root / "runs" / record.run_set)

        cmd = self._build_command(record)
        _LOG.info("starting job %s: %s", job_id, " ".join(cmd))

        try:
            with log_path.open("wb") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=str(self._repo_root),
                )
            self._procs[job_id] = proc

            # Update record with PID
            record.pid = proc.pid
            proc_start_time = _read_proc_start_time(proc.pid)
            record.proc_start_time = proc_start_time
            self._store.save(record)

            # Tail log file while subprocess runs
            finished_k = 0
            with log_path.open("r", encoding="utf-8", errors="replace") as log_r:
                while proc.poll() is None:
                    line = log_r.readline()
                    if not line:
                        await asyncio.sleep(_TAIL_POLL_SEC)
                        continue
                    line_stripped = line.rstrip("\n")
                    # Parse progress marker
                    m = _PROGRESS_RE.search(line_stripped)
                    if m:
                        ep_idx = int(m.group(1))
                        finished_k = int(m.group(2))
                        pct = int(finished_k * 100 / total) if total > 0 else 0
                        record.progress_pct = pct
                        record.current_episode_idx = ep_idx
                        self._store.save(record)
                        self._publish_sse(job_id, {
                            "type": "progress",
                            "progress_pct": pct,
                            "current_episode_idx": ep_idx,
                        })
                    else:
                        self._publish_sse(job_id, {
                            "type": "log",
                            "line": line_stripped,
                        })

                # Read any remaining lines
                for line in log_r:
                    line_stripped = line.rstrip("\n")
                    m = _PROGRESS_RE.search(line_stripped)
                    if m:
                        ep_idx = int(m.group(1))
                        finished_k = int(m.group(2))
                        pct = int(finished_k * 100 / total) if total > 0 else 0
                        record.progress_pct = pct
                        record.current_episode_idx = ep_idx
                    else:
                        self._publish_sse(job_id, {"type": "log", "line": line_stripped})

            returncode = proc.returncode
            if returncode == 0:
                record.status = "done"
                record.progress_pct = 100
            else:
                record.status = "failed"
                record.error = JobError(
                    reason="subprocess_exit",
                    detail=f"exit code {returncode}",
                )
        except Exception as exc:
            _LOG.exception("job %s raised exception", job_id)
            record.status = "failed"
            record.error = JobError(reason="internal_error", detail=str(exc))
        finally:
            record.finished_at = _now_iso()
            self._store.save(record)
            self._procs.pop(job_id, None)
            self._publish_sse(job_id, {
                "type": "done" if record.status == "done" else "failed",
                "final_status": record.status,
                "run_canonicals": record.run_canonicals,
            })
            self._publish_sse_done(job_id)

    async def run_gpu_worker(self, gpu_index: int) -> None:
        """Infinite loop pulling jobs from the GPU queue and running them."""
        while True:
            job_id = await self._queue.dequeue(gpu_index)
            # Check if cancelled before starting
            rec = self._store.load(job_id)
            if rec is None or rec.status == "cancelled":
                self._queue.mark_done(gpu_index)
                continue
            try:
                await self._run_job(job_id, gpu_index)
            except Exception:
                _LOG.exception("unhandled error in GPU %d worker for job %s", gpu_index, job_id)
            finally:
                self._queue.mark_done(gpu_index)

    async def start_workers(self) -> None:
        """Launch background worker tasks for all GPUs."""
        for i in range(self._queue.num_gpus()):
            asyncio.create_task(self.run_gpu_worker(i), name=f"gpu_worker_{i}")


def reclassify_stale_running_jobs(store: JobStore) -> None:
    """On server startup, reclassify running jobs with dead PID as failed.

    Checks /proc/<pid>/stat field 22 against the recorded proc_start_time.
    """
    records = store.list_all(status_filter=["running"])
    for rec in records:
        if rec.pid is None:
            # No PID recorded → can't verify; mark failed
            rec.status = "failed"
            rec.error = JobError(reason="server_restart", detail="pid not recorded")
            rec.finished_at = _now_iso()
            store.save(rec)
            continue
        if not _is_process_alive(rec.pid, rec.proc_start_time or 0):
            rec.status = "failed"
            rec.error = JobError(reason="server_restart")
            rec.finished_at = _now_iso()
            store.save(rec)
            _LOG.info("reclassified job %s as failed (server_restart)", rec.job_id)
