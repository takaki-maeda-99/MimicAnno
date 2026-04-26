# mimicanno/io_video.py
"""Video probing + run-dir materialization (spec §4.6, §13)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
