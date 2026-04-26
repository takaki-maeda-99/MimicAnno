# mimicanno/scavenger.py
"""Scavenger contract for *.tmp.<pid> and *.bak.<pid> dirs (spec §4.4)."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

WRITER_METADATA_FILENAME = ".writer.json"
_PID_DIR_RE = re.compile(r"^(?P<canonical>.+)\.(?P<kind>tmp|bak)\.(?P<pid>\d+)$")


@dataclass(frozen=True, slots=True)
class WriterMetadata:
    pid: int
    pid_start_time: str  # ISO-8601 UTC
    canonical_name: str
    kind: str  # "tmp" or "bak"
    claimed_at: str  # ISO-8601 UTC


def write_writer_metadata(dir_path: Path, md: WriterMetadata) -> None:
    (dir_path / WRITER_METADATA_FILENAME).write_text(
        json.dumps(asdict(md), sort_keys=True),
    )


def read_writer_metadata(dir_path: Path) -> WriterMetadata | None:
    p = dir_path / WRITER_METADATA_FILENAME
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return WriterMetadata(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but isn't ours
    return True


def current_pid_start_time(pid: int) -> str:
    """Return a stable ISO-8601 string for the start time of ``pid``.

    Uses ``/proc/<pid>/stat`` on Linux; falls back to a sentinel on other
    platforms. The exact value is not load-bearing — it just has to match
    *itself* across consecutive reads while the process is alive.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 22 (1-indexed) is starttime in clock ticks since boot.
        # We don't try to convert to wall-clock here; we just return a stable hash.
        starttime_ticks = stat.split()[21]
        return f"linux-jiffies-{starttime_ticks}"
    except (FileNotFoundError, OSError, IndexError):
        return "unknown-pid-start"


def scavenge_stale_dirs(
    runs_root: Path,
    *,
    stale_age_sec: float,
) -> list[Path]:
    """Remove `*.tmp.<pid>/` and `*.bak.<pid>/` whose writer is dead AND old.

    Returns the list of directories actually removed. Logging is delegated to
    the caller (the publish-transaction orchestrator).

    Age determination:
    - If ``.writer.json`` is parseable, use ``claimed_at``.
    - Otherwise fall back to the directory's mtime (best-effort proxy for
      "when this stale state appeared on disk"). This ensures unparseable
      metadata still age-gates per the spec, instead of being deleted on sight.
    """
    if not runs_root.exists():
        return []
    now = dt.datetime.now(tz=dt.UTC)
    removed: list[Path] = []
    for entry in runs_root.iterdir():
        m = _PID_DIR_RE.match(entry.name)
        if not m or not entry.is_dir():
            continue
        md = read_writer_metadata(entry)
        claimed: dt.datetime | None
        if md is not None:
            try:
                claimed = dt.datetime.fromisoformat(
                    md.claimed_at.replace("Z", "+00:00"),
                )
            except ValueError:
                claimed = None
        else:
            claimed = None
        if claimed is None:
            # Fallback: directory mtime as a stand-in for claimed_at.
            mtime = dt.datetime.fromtimestamp(entry.stat().st_mtime, tz=dt.UTC)
            age_sec = (now - mtime).total_seconds()
        else:
            age_sec = (now - claimed).total_seconds()
        is_old = age_sec >= stale_age_sec
        pid = int(m.group("pid"))
        is_dead = (
            md is None or not is_pid_alive(pid) or md.pid_start_time != current_pid_start_time(pid)
        )
        if is_dead and is_old:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
    return removed
