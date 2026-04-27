# mimicanno/io_video.py
"""Video probing + run-dir materialization (spec §4.6, §13)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore[import-untyped]

from mimicanno.hashing import sha256_file


class VideoProbeError(Exception):
    pass


@dataclass(slots=True)
class VideoProbe:
    sha256: str  # "sha256:<hex>"
    duration_sec: float
    fps: float
    width: int
    height: int


def _find_ffprobe() -> str:
    """Return the path to ffprobe, preferring the imageio_ffmpeg sibling binary.

    Falls back to the system ffprobe when the bundled sibling is absent
    (some imageio_ffmpeg builds ship only ffmpeg).
    """
    ffmpeg = get_ffmpeg_exe()
    sibling = Path(ffmpeg).with_name("ffprobe")
    if sibling.exists():
        return str(sibling)
    system = shutil.which("ffprobe")
    if system:
        return system
    raise VideoProbeError(f"ffprobe binary not found (tried {sibling} and PATH)")


def probe_video(path: Path) -> VideoProbe:
    """Probe a video for fps, duration, and dimensions using ffprobe.

    ``imageio_ffmpeg`` ships an ``ffmpeg`` binary; we invoke its sibling
    ``ffprobe`` (on the same PATH directory) for structured output.
    """
    ffprobe = _find_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise VideoProbeError(f"ffprobe binary not found at {ffprobe!r}") from e
    except subprocess.CalledProcessError as e:
        raise VideoProbeError(
            f"ffprobe failed for {path}: {e.stderr.strip()}",
        ) from e

    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise VideoProbeError(f"no video stream in {path}")
    stream = data["streams"][0]
    num, _, den = stream["r_frame_rate"].partition("/")
    fps = float(num) / float(den) if den else float(num)

    duration_str = stream.get("duration") or data.get("format", {}).get("duration")
    if duration_str is None:
        raise VideoProbeError(f"could not read duration for {path}")
    duration = float(duration_str)

    return VideoProbe(
        sha256="sha256:" + sha256_file(path),
        duration_sec=duration,
        fps=fps,
        width=int(stream["width"]),
        height=int(stream["height"]),
    )


def copy_video(src: Path, dest: Path) -> Path:
    shutil.copyfile(src, dest)
    return dest


def symlink_video(src: Path, dest: Path) -> Path:
    """Create a relative symlink from ``dest`` to ``src``."""
    rel = os.path.relpath(src.resolve(), dest.parent.resolve())
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(rel)
    return dest


def materialize_video(src: Path, run_dir: Path, *, link: bool) -> Path:
    """Place the video into ``run_dir`` as ``video.mp4`` (copy default; symlink opt-in)."""
    dest = run_dir / "video.mp4"
    if link:
        return symlink_video(src, dest)
    return copy_video(src, dest)


def extract_frames_at_indices(
    video_path: Path,
    frame_indices: list[int],
    *,
    long_edge_px: int | None = None,
) -> list[np.ndarray]:
    """Extract a set of frames from a video by frame index.

    Uses ffmpeg's ``select=eq(n,<index>)`` filter. Returns RGB uint8 arrays
    in the same order as ``frame_indices``. If ``long_edge_px`` is set, frames
    are letterbox-resized so the long edge equals ``long_edge_px`` (preserving
    aspect ratio).

    This implementation is purposely simple — it issues one ffmpeg call per
    frame index for clarity. K=4 per segment × N=8 segments = 32 ffmpeg calls
    per Phase 2 run, which is well within the §13 performance budget.
    """
    if not frame_indices:
        return []
    out: list[np.ndarray] = []
    ffmpeg = get_ffmpeg_exe()
    probe = probe_video(video_path)
    w, h = probe.width, probe.height
    if long_edge_px is not None:
        if w >= h:
            tw = long_edge_px
            th = int(round(h * (long_edge_px / w)))
        else:
            th = long_edge_px
            tw = int(round(w * (long_edge_px / h)))
        # Align to even dims so libx264 / rgb24 reshape stays consistent.
        if tw % 2:
            tw -= 1
        if th % 2:
            th -= 1
        scale_filter = f",scale={tw}:{th}"
    else:
        tw, th = w, h
        scale_filter = ""

    for idx in frame_indices:
        cmd = [
            ffmpeg, "-loglevel", "error", "-nostdin", "-y",
            "-i", str(video_path),
            "-vf", f"select=eq(n\\,{idx}){scale_filter}",
            "-vframes", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, check=True)
        arr = np.frombuffer(proc.stdout, dtype=np.uint8).reshape(th, tw, 3)
        out.append(arr.copy())
    return out
