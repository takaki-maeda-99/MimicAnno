"""Tests for ``create_inplace_backup`` (Phase 5 Task 19, spec §7.3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.output_layout import create_inplace_backup

_BACKUP_DIR_RE = re.compile(r"^\.mimicanno-backup-\d{8}T\d{6}Z(_\d{6})?$")


def _make_dataset(source: Path) -> None:
    """Create files matching the in-place backup target list (spec §7.3)."""
    (source / "data" / "chunk-000").mkdir(parents=True)
    (source / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(
        b"original-ep0"
    )
    (source / "data" / "chunk-000" / "episode_000001.parquet").write_bytes(
        b"original-ep1"
    )
    (source / "meta").mkdir()
    (source / "meta" / "info.json").write_text('{"v": 1}')
    (source / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (source / "meta" / "episodes" / "chunk-000" / "file-000.parquet").write_bytes(
        b"original-meta"
    )


def test_create_inplace_backup_creates_iso_dir(tmp_path: Path) -> None:
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [source / "meta" / "info.json"]

    backup_dir = create_inplace_backup(source, files)

    assert backup_dir.parent == source
    assert _BACKUP_DIR_RE.match(backup_dir.name), backup_dir.name
    assert backup_dir.is_dir()


def test_create_inplace_backup_copies_existing_files_verbatim(tmp_path: Path) -> None:
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [
        source / "data" / "chunk-000" / "episode_000000.parquet",
        source / "data" / "chunk-000" / "episode_000001.parquet",
        source / "meta" / "info.json",
        source / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
    ]

    backup_dir = create_inplace_backup(source, files)

    assert (
        backup_dir / "data" / "chunk-000" / "episode_000000.parquet"
    ).read_bytes() == b"original-ep0"
    assert (
        backup_dir / "data" / "chunk-000" / "episode_000001.parquet"
    ).read_bytes() == b"original-ep1"
    assert (backup_dir / "meta" / "info.json").read_text() == '{"v": 1}'
    assert (
        backup_dir / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    ).read_bytes() == b"original-meta"


def test_create_inplace_backup_skips_missing_files(tmp_path: Path) -> None:
    """Spec §7.3 amended rule: files-to-be-created have nothing to back up."""
    source = tmp_path / "ds"
    _make_dataset(source)

    files = [
        source / "meta" / "info.json",  # exists
        source / "meta" / "subtasks.parquet",  # does NOT exist (new file)
        source / "meta" / "mimicanno_segments.parquet",  # does NOT exist
    ]

    backup_dir = create_inplace_backup(source, files)

    assert (backup_dir / "meta" / "info.json").is_file()
    assert not (backup_dir / "meta" / "subtasks.parquet").exists()
    assert not (backup_dir / "meta" / "mimicanno_segments.parquet").exists()


def test_create_inplace_backup_does_not_modify_source(tmp_path: Path) -> None:
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [source / "meta" / "info.json"]

    create_inplace_backup(source, files)

    # Source files untouched.
    assert (source / "meta" / "info.json").read_text() == '{"v": 1}'
    assert (
        source / "data" / "chunk-000" / "episode_000000.parquet"
    ).read_bytes() == b"original-ep0"


def test_create_inplace_backup_fails_atomically_on_copy_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If any copy fails, the partial backup dir must be removed entirely."""
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [
        source / "meta" / "info.json",
        source / "data" / "chunk-000" / "episode_000000.parquet",
    ]

    import mimicanno.exports.output_layout as mod

    real_copy2 = mod.shutil.copy2
    call_count = {"n": 0}

    def flaky_copy2(src: str | Path, dst: str | Path, *args: object, **kw: object) -> object:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise OSError("simulated disk failure")
        return real_copy2(src, dst, *args, **kw)

    monkeypatch.setattr(mod.shutil, "copy2", flaky_copy2)

    with pytest.raises(MimicAnnoError) as exc_info:
        create_inplace_backup(source, files)

    assert exc_info.value.code == ErrorCode.EXPORT_INPLACE_BACKUP_FAILED
    # Partial backup dir must NOT remain.
    leftover = [p for p in source.iterdir() if p.name.startswith(".mimicanno-backup-")]
    assert leftover == []


def test_create_inplace_backup_second_call_creates_distinct_dir(
    tmp_path: Path,
) -> None:
    """Two consecutive calls must not collide (spec §7.3 'second invocation')."""
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [source / "meta" / "info.json"]

    first = create_inplace_backup(source, files)
    second = create_inplace_backup(source, files)

    assert first != second
    assert first.is_dir()
    assert second.is_dir()
    # Both backup dirs preserved.
    assert (first / "meta" / "info.json").is_file()
    assert (second / "meta" / "info.json").is_file()


def test_create_inplace_backup_returns_backup_dir(tmp_path: Path) -> None:
    source = tmp_path / "ds"
    _make_dataset(source)
    files = [source / "meta" / "info.json"]

    backup_dir = create_inplace_backup(source, files)

    # Caller uses the returned path for the post-export error message.
    assert isinstance(backup_dir, Path)
    assert backup_dir.is_dir()
    assert backup_dir.parent == source
