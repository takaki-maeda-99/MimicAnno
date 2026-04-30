"""Tests for ``mimicanno.exports.output_layout`` (Phase 5 Task 17).

Covers spec §7.1 (symlink), §7.2 (copy), §7.3 (in-place), §7.4 (atomicity).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from mimicanno.exports.output_layout import finalize, prepare_layout


def _make_source_dataset(source: Path) -> None:
    """Create a synthetic source dataset with `videos/`, `meta/`, `data/`."""
    (source / "videos" / "cam0" / "chunk-000").mkdir(parents=True)
    (source / "videos" / "cam0" / "chunk-000" / "episode_000000.mp4").write_bytes(b"video-bytes")
    (source / "meta").mkdir()
    (source / "meta" / "info.json").write_text("{}")
    (source / "data" / "chunk-000").mkdir(parents=True)
    (source / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"parquet-bytes")


# ---------------------------------------------------------------------------
# symlink mode
# ---------------------------------------------------------------------------


def test_prepare_layout_symlink_creates_staging_with_relative_videos_symlink(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    staging = prepare_layout("symlink", source, out)

    # Staging must be `out.tmp.<pid>` next to (not inside) `out`.
    assert staging.parent == out.parent
    assert staging.name == f"{out.name}.tmp.{os.getpid()}"
    assert staging.is_dir()

    videos_link = staging / "videos"
    assert videos_link.is_symlink()
    target = os.readlink(videos_link)
    # Symlink must be relative.
    assert not os.path.isabs(target)
    # And point at source/videos.
    resolved = (videos_link.parent / target).resolve()
    assert resolved == (source / "videos").resolve()

    # data/ and meta/ must exist as empty directories ready for sink writers.
    assert (staging / "data").is_dir()
    assert (staging / "meta").is_dir()


def test_finalize_symlink_success_replaces_out(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    staging = prepare_layout("symlink", source, out)
    # Simulate sink writers landing files in staging.
    (staging / "data" / "chunk-000").mkdir(parents=True)
    (staging / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"new")

    finalize("symlink", source, out, staging, success=True)

    assert not staging.exists()
    assert out.is_dir()
    assert (out / "videos").is_symlink()
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").read_bytes() == b"new"


def test_finalize_symlink_success_overwrites_existing_out(tmp_path: Path) -> None:
    """`finalize` os.replace overwrites an existing OUT (--force semantics)."""
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    # Pre-existing OUT directory.
    out.mkdir()
    (out / "stale.txt").write_text("stale")

    staging = prepare_layout("symlink", source, out)
    finalize("symlink", source, out, staging, success=True)

    assert out.is_dir()
    # Old contents replaced.
    assert not (out / "stale.txt").exists()
    assert (out / "videos").is_symlink()


def test_finalize_replaces_existing_out_atomically_no_missing_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §7.4: replacing an existing OUT must never leave a window where
    OUT does not exist (a concurrent reader — e.g. SARM training reading the
    dataset — must see either the old or the new tree, never FileNotFoundError).

    We expose the window deterministically by patching `shutil.rmtree` with
    a slowed-down version (sleeps 100ms before returning). A reader thread
    polls `out.is_dir()` continuously through finalize. If finalize used a
    naive `rmtree(out); os.replace(staging, out)` sequence, every poll
    during the 100ms sleep would observe `is_dir()=False`. The atomic
    finalize keeps OUT present by renaming it aside before publishing.
    """
    import threading
    import time as _time

    import mimicanno.exports.output_layout as ol_module

    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    out.mkdir()
    (out / "OLD.marker").write_text("old")

    real_rmtree = shutil.rmtree

    def slow_rmtree(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Sleep AFTER deletion so the test window matches the real bug —
        # the gap between rmtree returning and os.replace running.
        result = real_rmtree(*args, **kwargs)
        _time.sleep(0.1)
        return result

    monkeypatch.setattr(ol_module.shutil, "rmtree", slow_rmtree)

    staging = prepare_layout("symlink", source, out)

    out_present_observations: list[bool] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            out_present_observations.append(out.is_dir())
            _time.sleep(0.001)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        finalize("symlink", source, out, staging, success=True)
    finally:
        stop.set()
        t.join(timeout=2.0)

    assert out.is_dir()
    assert (out / "videos").is_symlink()
    assert not (out / "OLD.marker").exists()
    missing = out_present_observations.count(False)
    assert missing == 0, (
        f"OUT went missing during finalize "
        f"({missing} of {len(out_present_observations)} polls saw FileNotFound). "
        "Atomic publish requires a rename-aside-then-replace dance, not "
        "rmtree-then-replace."
    )


def test_finalize_symlink_failure_keeps_staging(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    staging = prepare_layout("symlink", source, out)
    finalize("symlink", source, out, staging, success=False)

    # On failure, staging is preserved for inspection; OUT is not created.
    assert staging.is_dir()
    assert not out.exists()


# ---------------------------------------------------------------------------
# copy mode
# ---------------------------------------------------------------------------


def test_prepare_layout_copy_recursively_copies_videos(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    staging = prepare_layout("copy", source, out)

    videos_dir = staging / "videos"
    assert videos_dir.is_dir()
    assert not videos_dir.is_symlink()
    assert (videos_dir / "cam0" / "chunk-000" / "episode_000000.mp4").read_bytes() == b"video-bytes"

    assert (staging / "data").is_dir()
    assert (staging / "meta").is_dir()


def test_finalize_copy_success_replaces_out(tmp_path: Path) -> None:
    source = tmp_path / "src"
    out = tmp_path / "out"
    _make_source_dataset(source)

    staging = prepare_layout("copy", source, out)
    finalize("copy", source, out, staging, success=True)

    assert not staging.exists()
    assert out.is_dir()
    assert (out / "videos" / "cam0" / "chunk-000" / "episode_000000.mp4").is_file()


# ---------------------------------------------------------------------------
# in_place mode
# ---------------------------------------------------------------------------


def test_prepare_layout_in_place_returns_source_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _make_source_dataset(source)

    staging = prepare_layout("in_place", source, out=None)

    # in_place returns source itself; no staging dir, no extra siblings.
    assert staging == source
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["src"]


def test_finalize_in_place_is_noop(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _make_source_dataset(source)

    staging = prepare_layout("in_place", source, out=None)
    # success=True: per-file renames already committed, finalize must not move anything.
    finalize("in_place", source, out=None, staging=staging, success=True)
    assert source.is_dir()
    assert (source / "videos" / "cam0" / "chunk-000" / "episode_000000.mp4").is_file()

    # success=False: backup dir is preserved by the orchestrator separately;
    # finalize itself is also a no-op.
    finalize("in_place", source, out=None, staging=staging, success=False)
    assert source.is_dir()


# ---------------------------------------------------------------------------
# input validation
# ---------------------------------------------------------------------------


def test_prepare_layout_unknown_mode_raises(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _make_source_dataset(source)
    with pytest.raises(ValueError):
        prepare_layout("nope", source, tmp_path / "out")  # type: ignore[arg-type]


def test_prepare_layout_symlink_requires_out(tmp_path: Path) -> None:
    source = tmp_path / "src"
    _make_source_dataset(source)
    with pytest.raises(ValueError):
        prepare_layout("symlink", source, out=None)
