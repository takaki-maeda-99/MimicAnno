"""Unit tests for resolve_sam3_checkpoint (spec §8 + 2026-05-04 sha cache)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mimicanno.errors import SAM3CheckpointNotFound
from mimicanno.preflight import resolve_sam3_checkpoint


@pytest.fixture(autouse=True)
def _isolate_sam3_sha_cache(tmp_path_factory, monkeypatch):
    """Redirect the sha cache to a tmp dir so tests don't pollute the user's
    real ~/.cache and don't see each other's cached entries."""
    cache_dir = tmp_path_factory.mktemp("sam3-sha-cache")
    monkeypatch.setenv("MIMICANNO_SAM3_SHA_CACHE_DIR", str(cache_dir))
    yield cache_dir


def test_resolve_sam3_checkpoint_returns_sha256(tmp_path: Path) -> None:
    """Verify sha256 computation for a valid checkpoint file."""
    checkpoint_file = tmp_path / "weights.pt"
    test_content = b"hello\n"
    checkpoint_file.write_bytes(test_content)

    expected_sha = hashlib.sha256(test_content).hexdigest()
    result = resolve_sam3_checkpoint(checkpoint_file)

    assert result == f"sha256:{expected_sha}"


def test_missing_path_raises_file_not_found(tmp_path: Path) -> None:
    """Verify SAM3CheckpointNotFound is raised for a missing file."""
    missing_path = tmp_path / "nonexistent.pt"

    with pytest.raises(SAM3CheckpointNotFound) as exc_info:
        resolve_sam3_checkpoint(missing_path)

    assert exc_info.value.context["reason"] == "file not found"


def test_directory_raises_not_a_regular_file(tmp_path: Path) -> None:
    """Verify SAM3CheckpointNotFound is raised when path is a directory."""
    with pytest.raises(SAM3CheckpointNotFound) as exc_info:
        resolve_sam3_checkpoint(tmp_path)

    assert exc_info.value.context["reason"] == "not a regular file"


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod test")
@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_unreadable_file_raises_permission_denied(tmp_path: Path) -> None:
    """Verify SAM3CheckpointNotFound is raised when file is unreadable."""
    checkpoint_file = tmp_path / "weights.pt"
    checkpoint_file.write_bytes(b"test content")

    try:
        checkpoint_file.chmod(0o000)

        with pytest.raises(SAM3CheckpointNotFound) as exc_info:
            resolve_sam3_checkpoint(checkpoint_file)

        assert exc_info.value.context["reason"] == "permission denied"
    finally:
        # Restore permissions for cleanup
        checkpoint_file.chmod(0o600)


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only symlink test")
def test_broken_symlink_treated_as_file_not_found(tmp_path: Path) -> None:
    """Verify broken symlinks are treated as 'file not found'."""
    target_file = tmp_path / "target.pt"
    target_file.write_bytes(b"original content")

    symlink_file = tmp_path / "link.pt"
    symlink_file.symlink_to(target_file)

    # Delete the target to break the symlink
    target_file.unlink()

    with pytest.raises(SAM3CheckpointNotFound) as exc_info:
        resolve_sam3_checkpoint(symlink_file)

    assert exc_info.value.context["reason"] == "file not found"


# ---------------------------------------------------------------------------
# Sha cache tests (2026-05-04 SAM3 backend swap, plan Task 2)
# ---------------------------------------------------------------------------


def test_cache_cold_then_warm_skips_recompute(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """Two calls on the same file → sha256_file invoked only on the cold call."""
    f = tmp_path / "w.pt"
    f.write_bytes(b"abc")

    with patch("mimicanno.preflight.sha256_file", wraps=__import__(
        "mimicanno.hashing", fromlist=["sha256_file"]
    ).sha256_file) as spy:
        first = resolve_sam3_checkpoint(f)
        second = resolve_sam3_checkpoint(f)

    assert first == second
    assert spy.call_count == 1, "warm call should hit the cache"

    cache_files = list(_isolate_sam3_sha_cache.iterdir())
    assert len(cache_files) == 1, f"expected exactly 1 cache entry, got {cache_files}"


def test_cache_invalidates_on_mtime_change(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """Touching the file (mtime change) causes a cache miss → recompute."""
    f = tmp_path / "w.pt"
    f.write_bytes(b"abc")

    with patch("mimicanno.preflight.sha256_file", wraps=__import__(
        "mimicanno.hashing", fromlist=["sha256_file"]
    ).sha256_file) as spy:
        resolve_sam3_checkpoint(f)
        # Bump mtime by 1s without changing content. This should produce a new
        # cache key and trigger recompute.
        st = f.stat()
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        resolve_sam3_checkpoint(f)

    assert spy.call_count == 2

    cache_files = list(_isolate_sam3_sha_cache.iterdir())
    assert len(cache_files) == 2, "old + new cache entries should both exist"


def test_cache_invalidates_on_size_change(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """Different content → different size → cache miss + new sha."""
    f = tmp_path / "w.pt"
    f.write_bytes(b"abc")

    first = resolve_sam3_checkpoint(f)
    f.write_bytes(b"abcd")  # different size, different content
    second = resolve_sam3_checkpoint(f)

    assert first != second
    cache_files = list(_isolate_sam3_sha_cache.iterdir())
    # Two distinct keys (size differs) — both cached.
    assert len(cache_files) == 2


def test_corrupt_cache_content_falls_back_to_recompute(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """A junk cache file (not 64-hex) is ignored; recompute + overwrite."""
    f = tmp_path / "w.pt"
    f.write_bytes(b"hello")

    # Pre-populate a cache entry with the matching key but bogus content.
    st = f.stat()
    fake_cache = _isolate_sam3_sha_cache / f"{st.st_mtime_ns}_{st.st_size}.txt"
    fake_cache.write_text("not-a-sha\n")

    expected = hashlib.sha256(b"hello").hexdigest()
    assert resolve_sam3_checkpoint(f) == f"sha256:{expected}"
    # The corrupt file should now be overwritten with the correct sha.
    assert fake_cache.read_text(encoding="ascii").strip() == expected


def test_cache_dir_creation_failure_is_silent(
    tmp_path: Path, monkeypatch,
) -> None:
    """If the cache dir cannot be created, sha is still returned (warn-only)."""
    # Point the cache at a path under a regular file — mkdir(parents=True) will
    # fail because intermediate component is a file.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    monkeypatch.setenv("MIMICANNO_SAM3_SHA_CACHE_DIR", str(blocker / "child" / "sha-cache"))

    f = tmp_path / "w.pt"
    f.write_bytes(b"abc")

    expected = hashlib.sha256(b"abc").hexdigest()
    assert resolve_sam3_checkpoint(f) == f"sha256:{expected}"


def test_cache_uses_path_agnostic_key(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """Two paths with identical (mtime, size) share the same cache entry.

    This is intentional: the cache key is content-summary-based, not
    path-based, so moving the same weights file does not invalidate.
    """
    a = tmp_path / "a.pt"
    b = tmp_path / "b.pt"
    a.write_bytes(b"identical")
    # Copy bytes AND mtime so (mtime_ns, size) match.
    b.write_bytes(a.read_bytes())
    st = a.stat()
    os.utime(b, ns=(st.st_atime_ns, st.st_mtime_ns))

    with patch("mimicanno.preflight.sha256_file", wraps=__import__(
        "mimicanno.hashing", fromlist=["sha256_file"]
    ).sha256_file) as spy:
        resolve_sam3_checkpoint(a)
        resolve_sam3_checkpoint(b)

    assert spy.call_count == 1, (
        "second call (different path, same key) should reuse cache"
    )


def test_cache_value_format_is_lowercase_hex(
    tmp_path: Path, _isolate_sam3_sha_cache: Path,
) -> None:
    """Cache file content is exactly 64 lowercase hex chars (no `sha256:` prefix)."""
    f = tmp_path / "w.pt"
    f.write_bytes(b"x")

    resolve_sam3_checkpoint(f)
    files = list(_isolate_sam3_sha_cache.iterdir())
    assert len(files) == 1
    body = files[0].read_text(encoding="ascii").strip()
    assert len(body) == 64
    assert all(c in "0123456789abcdef" for c in body)
