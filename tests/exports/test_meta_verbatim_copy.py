"""Tests for ``copy_meta_verbatim`` (Phase 5 Task 18, spec §4.5)."""

from __future__ import annotations

import os
from pathlib import Path

from mimicanno.exports.output_layout import copy_meta_verbatim


def _populate_meta(source: Path) -> None:
    meta = source / "meta"
    meta.mkdir(parents=True)
    # Files Phase 5 sinks regenerate (must be excluded by default).
    (meta / "info.json").write_text('{"v": 1}')
    (meta / "subtasks.parquet").write_bytes(b"new-subtasks")
    (meta / "mimicanno_segments.parquet").write_bytes(b"new-segments")
    # Episodes subdirectory: also excluded by default.
    (meta / "episodes" / "chunk-000").mkdir(parents=True)
    (meta / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(b"per-chunk")
    # Files that must be copied verbatim.
    (meta / "tasks.parquet").write_bytes(b"task-bytes")
    (meta / "stats.parquet").write_bytes(b"stats-bytes")
    (meta / "modality.json").write_text('{"k": "v"}')
    # Nested non-excluded subdir to exercise recursive copy.
    (meta / "extras").mkdir()
    (meta / "extras" / "note.txt").write_text("hello")


def test_copy_meta_verbatim_copies_non_excluded(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _populate_meta(source)
    out.mkdir()

    copy_meta_verbatim(source, out)

    assert (out / "meta" / "tasks.parquet").read_bytes() == b"task-bytes"
    assert (out / "meta" / "stats.parquet").read_bytes() == b"stats-bytes"
    assert (out / "meta" / "modality.json").read_text() == '{"k": "v"}'
    assert (out / "meta" / "extras" / "note.txt").read_text() == "hello"


def test_copy_meta_verbatim_excludes_default_set(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _populate_meta(source)
    out.mkdir()

    copy_meta_verbatim(source, out)

    assert not (out / "meta" / "info.json").exists()
    assert not (out / "meta" / "subtasks.parquet").exists()
    assert not (out / "meta" / "mimicanno_segments.parquet").exists()
    assert not (out / "meta" / "episodes").exists()


def test_copy_meta_verbatim_preserves_mtime(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _populate_meta(source)
    out.mkdir()

    src_file = source / "meta" / "tasks.parquet"
    # Set a recognisable mtime in the past.
    os.utime(src_file, (1_700_000_000, 1_700_000_000))

    copy_meta_verbatim(source, out)

    dst_file = out / "meta" / "tasks.parquet"
    assert dst_file.stat().st_mtime == 1_700_000_000


def test_copy_meta_verbatim_custom_exclusions(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _populate_meta(source)
    out.mkdir()

    # Custom: only exclude "stats.parquet".
    copy_meta_verbatim(source, out, exclusions={"stats.parquet"})

    assert (out / "meta" / "tasks.parquet").is_file()
    assert (out / "meta" / "info.json").is_file()  # default exclusion overridden
    assert (out / "meta" / "subtasks.parquet").is_file()
    assert (out / "meta" / "episodes" / "chunk-000" / "file-000.parquet").is_file()
    assert not (out / "meta" / "stats.parquet").exists()


def test_copy_meta_verbatim_no_meta_dir_is_noop(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    source.mkdir()
    out.mkdir()
    # No meta/ subdir on source.
    copy_meta_verbatim(source, out)
    # out/meta/ should not exist (we don't create empty dirs unprompted).
    assert not (out / "meta").exists()


def test_copy_meta_verbatim_creates_out_meta_if_absent(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _populate_meta(source)
    out.mkdir()
    # out/meta/ does not exist yet.
    copy_meta_verbatim(source, out)
    assert (out / "meta").is_dir()
