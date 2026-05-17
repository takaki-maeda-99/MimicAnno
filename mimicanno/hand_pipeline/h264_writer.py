"""ffmpeg-piped libx264 video writer.

Replaces ``cv2.VideoWriter`` with mp4v (MPEG-4 part 2) which is not
playable in modern browsers.  Pipes BGR uint8 frames to ``ffmpeg`` over
stdin and produces h264 + yuv420p mp4 with ``+faststart`` for progressive
streaming.

API mirrors ``cv2.VideoWriter``: ``.write(bgr)`` and ``.release()`` so
existing call sites can swap in with minimal changes.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

_LOG = logging.getLogger(__name__)


class H264VideoWriter:
    """Stream BGR uint8 frames to a libx264 mp4 via ffmpeg subprocess."""

    def __init__(
        self,
        path: str | Path,
        width: int,
        height: int,
        fps: float,
        crf: int = 23,
        preset: str = "medium",
    ) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg not found in PATH; install via "
                "'apt install ffmpeg' or 'conda install -c conda-forge ffmpeg'"
            )
        self._path = Path(path)
        self._w_orig = int(width)
        self._h_orig = int(height)
        self._w_eff = self._w_orig & ~1
        self._h_eff = self._h_orig & ~1
        if self._w_eff != self._w_orig or self._h_eff != self._h_orig:
            _LOG.warning(
                "H264VideoWriter: rounded %dx%d -> %dx%d for yuv420p",
                self._w_orig, self._h_orig, self._w_eff, self._h_eff,
            )
        self._closed = False
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self._w_eff}x{self._h_eff}",
            "-r", f"{fps:.6f}",
            "-i", "-",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", str(int(crf)),
            "-preset", str(preset),
            "-movflags", "+faststart",
            str(self._path),
        ]
        self._proc: Optional[subprocess.Popen] = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, bgr: np.ndarray) -> None:
        if self._closed or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("write() after release()")
        if bgr.dtype != np.uint8 or bgr.shape != (self._h_orig, self._w_orig, 3):
            raise ValueError(
                f"expected ({self._h_orig},{self._w_orig},3) uint8, "
                f"got {bgr.shape} {bgr.dtype}"
            )
        # Crop right/bottom 1px when odd-snapped — contiguous to avoid copy.
        if self._w_eff != self._w_orig or self._h_eff != self._h_orig:
            bgr = bgr[: self._h_eff, : self._w_eff, :]
        self._proc.stdin.write(np.ascontiguousarray(bgr).tobytes())

    def release(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                try:
                    self._proc.stdin.close()
                except BrokenPipeError:
                    pass
            rc = self._proc.wait(timeout=30)
            if rc != 0:
                err = b""
                if self._proc.stderr is not None:
                    try:
                        err = self._proc.stderr.read()[-1024:]
                    except Exception:
                        err = b""
                self._path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"ffmpeg exited with rc={rc}: {err.decode(errors='replace')}"
                )
        finally:
            if self._proc is not None and self._proc.stderr is not None:
                try:
                    self._proc.stderr.close()
                except Exception:
                    pass
            self._proc = None

    @property
    def width(self) -> int:
        return self._w_eff

    @property
    def height(self) -> int:
        return self._h_eff

    def __enter__(self) -> "H264VideoWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
