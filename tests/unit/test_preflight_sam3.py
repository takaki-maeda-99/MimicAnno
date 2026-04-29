"""Unit tests for resolve_sam3_checkpoint (spec §8)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from mimicanno.errors import SAM3CheckpointNotFound
from mimicanno.preflight import resolve_sam3_checkpoint


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
