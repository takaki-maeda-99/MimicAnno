# tests/unit/test_scavenger.py
import json
import os
import time
from pathlib import Path

from mimicanno.scavenger import (
    WriterMetadata,
    is_pid_alive,
    read_writer_metadata,
    scavenge_stale_dirs,
    write_writer_metadata,
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def test_write_and_read_writer_metadata(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.123"
    d.mkdir()
    md = WriterMetadata(
        pid=123, pid_start_time="2026-04-26T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    got = read_writer_metadata(d)
    assert got == md


def test_is_pid_alive_for_self():
    assert is_pid_alive(os.getpid())


def test_scavenge_skips_live_pid_within_age(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.{}".format(os.getpid())
    d.mkdir()
    md = WriterMetadata(
        pid=os.getpid(),
        pid_start_time=_pid_start_time_now(),
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600)
    assert d.exists()


def test_scavenge_removes_dir_with_dead_pid(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.999999"  # virtually-impossible-PID for this run
    d.mkdir()
    md = WriterMetadata(
        pid=999999, pid_start_time="1970-01-01T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp",
        claimed_at="1970-01-01T00:00:00.000Z",
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=1)
    assert not d.exists()


def test_scavenge_keeps_dir_with_dead_pid_under_age(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.999999"
    d.mkdir()
    md = WriterMetadata(
        pid=999999, pid_start_time="1970-01-01T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600)
    assert d.exists()  # under age threshold; deferred


def test_scavenge_handles_unparseable_metadata(tmp_path: Path):
    """Unparseable .writer.json + age threshold passed → deleted (the dir name
    has a PID we cannot trust without metadata, so the stale_age_sec gate is
    what protects live writers in this branch). With stale_age_sec=0 any age
    is treated as old → delete."""
    d = tmp_path / "ep0__abc.tmp.42"
    d.mkdir()
    (d / ".writer.json").write_text("{not json")
    scavenge_stale_dirs(tmp_path, stale_age_sec=0)
    assert not d.exists()


def test_scavenge_keeps_unparseable_metadata_with_huge_age(tmp_path: Path):
    """Same scenario, but a 1h age threshold protects against eager deletion."""
    d = tmp_path / "ep0__abc.tmp.43"
    d.mkdir()
    (d / ".writer.json").write_text("{not json")
    # We cannot infer claimed_at without metadata, so the implementation
    # decides "treat as old" — but it MUST also be dead. PID 43 is unlikely
    # to be alive in the test environment; if it IS alive, the test is moot.
    # Use a huge age threshold to keep the test robust regardless.
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600 * 24 * 365)
    # Strictly: the spec says (dead OR unparseable) AND old — with huge age
    # threshold we expect the dir kept. If the implementation chooses to
    # delete unparseable regardless of age, that's a spec deviation.
    assert d.exists()


def _pid_start_time_now() -> str:
    """Return the current process's start time formatted exactly like scavenger does."""
    from mimicanno.scavenger import current_pid_start_time
    return current_pid_start_time(os.getpid())
