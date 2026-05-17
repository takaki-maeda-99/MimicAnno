"""Tests for H264VideoWriter — ffmpeg-piped libx264 mp4 writer."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
    pytest.skip("ffmpeg/ffprobe not in PATH", allow_module_level=True)


def _probe(path: Path) -> dict:
    """Return ffprobe stream info dict for the first video stream."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt,width,height",
            "-of", "default=nw=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.strip().splitlines())


def test_writes_h264_yuv420p(tmp_path: Path) -> None:
    from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

    out = tmp_path / "out.mp4"
    w = H264VideoWriter(out, width=16, height=16, fps=30.0)
    try:
        for _ in range(3):
            w.write(np.zeros((16, 16, 3), dtype=np.uint8))
    finally:
        w.release()

    assert out.exists() and out.stat().st_size > 0
    info = _probe(out)
    assert info["codec_name"] == "h264"
    assert info["pix_fmt"] == "yuv420p"
    assert info["width"] == "16"
    assert info["height"] == "16"
