"""Output destination + atomic publish for Phase 5 export (spec §7).

Three modes:

- ``"symlink"`` (default) — stage at ``OUT.tmp.<pid>/`` with a relative
  symlink to ``<source>/videos``; ``finalize`` does
  ``os.replace(staging, out)``.
- ``"copy"`` — same as symlink but ``videos/`` is recursively copied.
- ``"in_place"`` — write back into the source dataset directory itself; no
  staging dir. The caller is expected to have created an in-place backup via
  :func:`create_inplace_backup` *before* any write. ``finalize`` is a no-op.

Per spec §7.4 atomicity rules: each individual file write is already atomic
via the ``mimicanno.writers`` ``.tmp.<pid>`` + ``os.replace`` pattern. The
transaction boundary for symlink / copy mode is the final
``os.replace(OUT.tmp.<pid>, OUT)``; for in-place mode it is the per-file
rename loop completing successfully (with the backup directory as the
recovery point).
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from mimicanno.errors import ErrorCode, MimicAnnoError

OutputMode = Literal["symlink", "copy", "in_place"]

_DEFAULT_META_EXCLUSIONS: frozenset[str] = frozenset(
    {"subtasks.parquet", "mimicanno_segments.parquet", "info.json", "episodes"}
)


def _staging_path(out: Path) -> Path:
    """Return the per-pid staging path next to ``out``."""
    return out.parent / f"{out.name}.tmp.{os.getpid()}"


def prepare_layout(
    mode: OutputMode,
    source: Path,
    out: Path | None,
) -> Path:
    """Create (or identify) the output staging directory.

    Returns the path that subsequent sink writers should land files into.

    For ``"symlink"`` and ``"copy"`` modes this is ``out.tmp.<pid>/`` next to
    ``out``; the directory is created with empty ``data/`` and ``meta/``
    subdirectories and a ``videos`` entry pointing at the source's videos
    (relative symlink for ``"symlink"``, recursive copy for ``"copy"``).

    For ``"in_place"`` mode this is ``source`` itself (no staging dir);
    ``out`` is ignored.

    Parameters
    ----------
    mode:
        One of ``"symlink"``, ``"copy"``, ``"in_place"``.
    source:
        Path to the input LeRobot v3 dataset.
    out:
        Destination dataset path. Required for symlink / copy; must be
        ``None`` for in_place.

    Notes
    -----
    Caller (the Phase E orchestrator) is responsible for the
    "out already exists" check before invoking this function — ``finalize``'s
    ``os.replace`` will overwrite an existing directory, which is the
    intended ``--force`` semantics.
    """
    if mode == "in_place":
        return source
    if mode not in ("symlink", "copy"):
        raise ValueError(f"unknown output mode: {mode!r}")
    if out is None:
        raise ValueError(f"mode={mode!r} requires `out`")

    staging = _staging_path(out)
    # Clean any leftover staging from a prior crashed run with the same pid.
    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or staging.is_file():
            staging.unlink()
        else:
            shutil.rmtree(staging)

    staging.mkdir(parents=True)
    (staging / "data").mkdir()
    (staging / "meta").mkdir()

    src_videos = source / "videos"
    if mode == "symlink":
        rel = os.path.relpath(src_videos, start=staging)
        os.symlink(rel, staging / "videos")
    else:  # mode == "copy"
        if src_videos.exists():
            shutil.copytree(src_videos, staging / "videos")
        else:
            (staging / "videos").mkdir()

    return staging


def finalize(
    mode: OutputMode,
    source: Path,
    out: Path | None,
    staging: Path,
    success: bool,
) -> None:
    """Commit (or abort) the output transaction.

    On ``success=True``:

    - ``"symlink"`` / ``"copy"`` — ``os.replace(staging, out)`` (POSIX-atomic
      directory rename when staging and out share a filesystem).
    - ``"in_place"`` — no-op; per-file renames already committed.

    On ``success=False``:

    - ``"symlink"`` / ``"copy"`` — staging is left in place for inspection;
      caller may inspect or remove it manually.
    - ``"in_place"`` — no-op; the in-place backup directory created by
      :func:`create_inplace_backup` is the rollback path and is left
      untouched.
    """
    if mode == "in_place":
        return
    if mode not in ("symlink", "copy"):
        raise ValueError(f"unknown output mode: {mode!r}")
    if out is None:
        raise ValueError(f"mode={mode!r} requires `out`")
    if not success:
        return
    # Atomic publish (spec §7.4): a concurrent reader (e.g. a SARM training
    # job that opened the dataset before re-export) must always see EITHER
    # the old tree or the new tree, never a missing-OUT window. Naive
    # `rmtree(out); os.replace(staging, out)` opens a window of arbitrary
    # length (rmtree of N files takes O(N)). The rename-aside-then-replace
    # dance keeps OUT continuously present:
    #
    #   1. rename existing OUT to a sibling stash (atomic);
    #   2. os.replace(staging, OUT) — atomic; OUT is now the new tree;
    #   3. rmtree the stash on a best-effort basis.
    #
    # `os.replace` rejects a non-empty target directory on POSIX, so the
    # stash rename is essential — without step 1 the replace would fail.
    if out.exists() or out.is_symlink():
        if out.is_symlink() or out.is_file():
            out.unlink()
            os.replace(staging, out)
        else:
            stash = out.parent / f"{out.name}.old.{os.getpid()}"
            # Defensive: if a previous crashed run left a same-pid stash, drop it.
            if stash.exists():
                shutil.rmtree(stash)
            os.replace(out, stash)            # OUT-was → stash (atomic)
            try:
                os.replace(staging, out)      # staging → OUT     (atomic)
            except OSError:
                # Restore the old tree if the publish failed.
                os.replace(stash, out)
                raise
            shutil.rmtree(stash, ignore_errors=True)
    else:
        os.replace(staging, out)


def copy_meta_verbatim(
    source: Path,
    out: Path,
    exclusions: set[str] | frozenset[str] | None = None,
) -> None:
    """Copy every file under ``source/meta/`` to ``out/meta/`` byte-for-byte.

    Files (or directories) whose name relative to ``source/meta/`` matches an
    entry in ``exclusions`` are skipped. The default exclusion set covers the
    files Phase 5 sinks regenerate themselves: ``info.json``,
    ``subtasks.parquet``, ``mimicanno_segments.parquet``, and the entire
    ``episodes/`` subtree (handled by the per-chunk episodes-metadata writer).

    Parameters
    ----------
    source:
        Source dataset root.
    out:
        Destination dataset root (or staging dir for symlink/copy modes).
    exclusions:
        Names (relative to ``source/meta/``) to skip. ``None`` uses the
        default set. A directory name matches the entire subtree.
    """
    excl = frozenset(exclusions) if exclusions is not None else _DEFAULT_META_EXCLUSIONS
    src_meta = source / "meta"
    if not src_meta.is_dir():
        return
    dst_meta = out / "meta"
    dst_meta.mkdir(parents=True, exist_ok=True)

    for entry in src_meta.iterdir():
        if entry.name in excl:
            continue
        rel = entry.relative_to(src_meta)
        target = dst_meta / rel
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True, copy_function=shutil.copy2)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, target)


def create_inplace_backup(
    source: Path,
    files_to_back_up: list[Path],
) -> Path:
    """Create a backup directory under ``source`` containing verbatim copies.

    Backup directory path is ``<source>/.mimicanno-backup-<ISO8601>/`` where
    ISO8601 is second-precision UTC ending in ``Z``. If a directory with that
    timestamp already exists (rare race), microsecond suffix is appended.

    For each file in ``files_to_back_up``:

    - If it exists: copied to ``backup_dir / f.relative_to(source)`` with
      ``shutil.copy2`` (preserves mtime / mode), creating intermediate
      directories.
    - If it does not exist: silently skipped (a brand-new file the export
      will create has nothing to back up).

    Backup creation is **all-or-nothing**: if any copy fails, the partial
    backup directory is removed and ``EXPORT_INPLACE_BACKUP_FAILED`` is
    raised so the in-place export aborts cleanly.

    Returns the backup directory path.
    """
    iso = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = source / f".mimicanno-backup-{iso}"
    if backup_dir.exists():
        # Race-protect: append microsecond suffix.
        microsec = datetime.now(tz=UTC).strftime("%f")
        backup_dir = source / f".mimicanno-backup-{iso}_{microsec}"

    try:
        backup_dir.mkdir()
    except OSError as e:
        raise MimicAnnoError(
            ErrorCode.EXPORT_INPLACE_BACKUP_FAILED,
            f"could not create in-place backup dir: {e}",
            {"backup_dir": str(backup_dir)},
        ) from e

    try:
        for f in files_to_back_up:
            if not f.exists():
                continue
            rel = f.relative_to(source)
            target = backup_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    except (OSError, ValueError) as e:
        # Roll back the partial backup dir, then raise.
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise MimicAnnoError(
            ErrorCode.EXPORT_INPLACE_BACKUP_FAILED,
            f"failed to back up file during in-place export: {e}",
            {"backup_dir": str(backup_dir)},
        ) from e

    return backup_dir
