"""Tests for scripts/transcode_viz_to_h264.py."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
    pytest.skip("ffmpeg/ffprobe not in PATH", allow_module_level=True)


SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "transcode_viz_to_h264.py"
)


def _probe_codec(path: Path) -> str:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return out


def _make_mpeg4_mp4(path: Path) -> None:
    """Write a tiny mpeg4 part 2 mp4 using cv2.VideoWriter — the same encoder
    the original viz scripts used.  Skipped if cv2 unavailable.
    """
    import cv2
    w = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (16, 16),
    )
    assert w.isOpened()
    for _ in range(3):
        w.write(np.zeros((16, 16, 3), dtype=np.uint8))
    w.release()


def _make_h264_mp4(path: Path) -> None:
    """Write a tiny h264 mp4 using ffmpeg directly (no cv2)."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=16x16:r=30:d=0.1",
            "-frames:v", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
    )


def test_dry_run_lists_only_mpeg4(tmp_path: Path) -> None:
    mp4v = tmp_path / "viz_depth.mp4"
    h264 = tmp_path / "viz" / "erp.mp4"
    h264.parent.mkdir()
    _make_mpeg4_mp4(mp4v)
    _make_h264_mp4(h264)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--dry-run"],
        capture_output=True, text=True, check=True,
    )
    assert str(mp4v) in result.stdout
    assert str(h264) not in result.stdout
    # Files unchanged
    assert _probe_codec(mp4v) == "mpeg4"
    assert _probe_codec(h264) == "h264"


def test_real_transcode_replaces_with_h264(tmp_path: Path) -> None:
    mp4v = tmp_path / "viz_depth.mp4"
    _make_mpeg4_mp4(mp4v)
    assert _probe_codec(mp4v) == "mpeg4"

    subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )

    backup = tmp_path / "viz_depth.mpeg4.bak"
    assert backup.exists()
    assert _probe_codec(backup) == "mpeg4"
    assert mp4v.exists()
    assert _probe_codec(mp4v) == "h264"


def test_skip_when_already_h264(tmp_path: Path) -> None:
    h264 = tmp_path / "viz_depth.mp4"
    _make_h264_mp4(h264)
    orig_mtime = h264.stat().st_mtime

    subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True, text=True, check=True,
    )

    assert h264.exists()
    assert not (tmp_path / "viz_depth.mpeg4.bak").exists()
    # mtime unchanged → file was not rewritten
    assert h264.stat().st_mtime == orig_mtime
