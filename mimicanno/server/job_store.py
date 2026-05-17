"""U-A1 — Job record dataclass + file persistence (spec §5).

Job records live at ``<jobs_dir>/<job_id>.json``.
Log files live at ``<jobs_dir>/<job_id>.log``.
Writes use atomic tmp-rename to avoid torn reads.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Status values per master spec §2.3
JobStatus = str  # "queued" | "running" | "done" | "failed" | "cancelled"

_VALID_STATUSES = frozenset({"queued", "running", "done", "failed", "cancelled"})

# Job ID pattern: j_YYYYMMDD_HHMMSS_4hex
_JOB_ID_RE = re.compile(r"^j_\d{8}_\d{6}_[a-f0-9]{4}$")

_LOG_TAIL_LINES = 200


@dataclass
class JobError:
    reason: str
    detail: str | None = None


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus  # queued | running | done | failed | cancelled
    kind: str  # "annotate"
    dataset: str
    episode_indices: list[int]  # resolved list (null → all filled in at submit time)
    run_set: str
    variant: str  # "4B" | "26B"
    gpu_index: int  # resolved (never null in record)
    robot_config: str
    pipeline_config: str
    # Timestamps (ISO 8601 string or None)
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    # Progress
    progress_pct: int | None = None
    current_episode_idx: int | None = None
    # Results
    run_canonicals: list[str] = field(default_factory=list)
    # Error
    error: JobError | None = None
    # Process info (for restart reclassification)
    pid: int | None = None
    proc_start_time: int | None = None  # /proc/<pid>/stat field 22

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serialize error sub-object
        if self.error is not None:
            d["error"] = asdict(self.error)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobRecord":
        error_data = d.pop("error", None)
        error: JobError | None = None
        if error_data is not None:
            error = JobError(**error_data)
        obj = cls(**d)
        obj.error = error
        return obj


class JobStore:
    """Filesystem-backed store for job records."""

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir
        jobs_dir.mkdir(parents=True, exist_ok=True)

    # ---------- write ----------

    def save(self, record: JobRecord) -> None:
        """Atomically write <job_id>.json."""
        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2)
        target = self.jobs_dir / f"{record.job_id}.json"
        tmp = target.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)

    def append_log(self, job_id: str, text: str) -> None:
        """Append text to <job_id>.log (non-atomic — log is append-only)."""
        log_path = self.jobs_dir / f"{job_id}.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(text)

    def delete(self, job_id: str) -> None:
        """Delete .json and .log for job_id (best-effort)."""
        for suffix in (".json", ".log"):
            p = self.jobs_dir / f"{job_id}{suffix}"
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- read ----------

    def load(self, job_id: str) -> JobRecord | None:
        """Load a job record by ID; returns None if not found."""
        path = self.jobs_dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return JobRecord.from_dict(data)
        except Exception:
            return None

    def list_all(self, status_filter: list[str] | None = None) -> list[JobRecord]:
        """Return all job records, optionally filtered by status."""
        records: list[JobRecord] = []
        for p in sorted(self.jobs_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = JobRecord.from_dict(data)
                if status_filter is None or rec.status in status_filter:
                    records.append(rec)
            except Exception:
                pass
        # Sort by queued_at descending (newest first)
        records.sort(key=lambda r: r.queued_at or "", reverse=True)
        return records

    def read_log_tail(self, job_id: str) -> list[str]:
        """Return last _LOG_TAIL_LINES lines of <job_id>.log."""
        log_path = self.jobs_dir / f"{job_id}.log"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-_LOG_TAIL_LINES:]
        except OSError:
            return []

    def read_log_full(self, job_id: str) -> str:
        """Return full contents of <job_id>.log."""
        log_path = self.jobs_dir / f"{job_id}.log"
        if not log_path.exists():
            return ""
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def log_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.log"
