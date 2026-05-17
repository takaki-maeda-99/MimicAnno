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


def test_odd_resolution_rounded(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

    out = tmp_path / "odd.mp4"
    with caplog.at_level("WARNING", logger="mimicanno.hand_pipeline.h264_writer"):
        w = H264VideoWriter(out, width=15, height=15, fps=30.0)
        try:
            for _ in range(3):
                w.write(np.zeros((15, 15, 3), dtype=np.uint8))
        finally:
            w.release()

    info = _probe(out)
    assert info["width"] == "14"
    assert info["height"] == "14"
    assert any("rounded 15x15 -> 14x14" in r.getMessage() for r in caplog.records)


def test_frame_shape_mismatch_raises(tmp_path: Path) -> None:
    from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

    w = H264VideoWriter(tmp_path / "x.mp4", width=32, height=32, fps=30.0)
    try:
        with pytest.raises(ValueError, match=r"expected \(32,32,3\) uint8"):
            w.write(np.zeros((16, 16, 3), dtype=np.uint8))
    finally:
        w.release()


def test_frame_dtype_mismatch_raises(tmp_path: Path) -> None:
    from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

    w = H264VideoWriter(tmp_path / "x.mp4", width=16, height=16, fps=30.0)
    try:
        with pytest.raises(ValueError, match=r"uint8"):
            w.write(np.zeros((16, 16, 3), dtype=np.float32))
    finally:
        w.release()


def test_missing_ffmpeg_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mimicanno.hand_pipeline.h264_writer as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="ffmpeg not found"):
        mod.H264VideoWriter(tmp_path / "x.mp4", width=16, height=16, fps=30.0)


def test_release_idempotent(tmp_path: Path) -> None:
    from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

    w = H264VideoWriter(tmp_path / "x.mp4", width=16, height=16, fps=30.0)
    w.write(np.zeros((16, 16, 3), dtype=np.uint8))
    w.release()
    w.release()  # must not raise


def test_subprocess_failure_unlinks_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ffmpeg exits non-zero, partial mp4 is unlinked and RuntimeError raised."""
    import mimicanno.hand_pipeline.h264_writer as mod

    real_popen = subprocess.Popen
    out = tmp_path / "fail.mp4"

    def fake_popen(cmd, **kwargs):
        # Replace ffmpeg with `false` (always exits 1). Keep stdin/stderr pipes.
        return real_popen(["false"], stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    monkeypatch.setattr(mod.subprocess, "Popen", fake_popen)
    # Touch the output path so we can verify unlink.
    out.write_bytes(b"partial")
    w = mod.H264VideoWriter(out, width=16, height=16, fps=30.0)
    with pytest.raises(RuntimeError, match="ffmpeg exited with rc="):
        w.release()
    assert not out.exists()
