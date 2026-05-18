#!/usr/bin/env python3
"""Transcode mpeg4 part 2 viz mp4s to h264 for browser playback.

Walks a root directory and finds these candidate filenames produced by the
hand pipeline:

  - <root>/**/viz_depth.mp4          (from scripts/visualize_depth.py)
  - <root>/**/viz/erp.mp4            (from scripts/precompute_depth.py)
  - <root>/**/viz/depth_fisheye.mp4  (from scripts/precompute_depth.py)

For each file:

  - probe the codec with ffprobe
  - if already h264, skip
  - otherwise rename to <basename>.<orig-codec>.bak and re-encode the
    original name with libx264 + yuv420p + faststart

Usage:
    python scripts/transcode_viz_to_h264.py outputs/depth/
    python scripts/transcode_viz_to_h264.py outputs/depth/ --dry-run

The .bak files are left on disk so the operation is reversible; clean up
with `find <root> -name '*.bak' -delete` once you're satisfied.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

CANDIDATE_NAMES = ("viz_depth.mp4", "erp.mp4", "depth_fisheye.mp4")


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
    return out or "unknown"


def _find_candidates(root: Path) -> list[Path]:
    results: list[Path] = []
    for name in CANDIDATE_NAMES:
        results.extend(root.rglob(name))
    # rglob returns mixed order; sort for stable output.
    return sorted(set(results))


def _transcode(src_bak: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src_bak),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "medium",
            "-movflags", "+faststart",
            str(dst),
        ],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", type=Path, help="directory to walk")
    ap.add_argument(
        "--dry-run", action="store_true",
        help="list files that would be transcoded; do not write anything",
    )
    args = ap.parse_args(argv)

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("error: ffmpeg/ffprobe not in PATH", file=sys.stderr)
        return 2

    if not args.root.is_dir():
        print(f"error: not a directory: {args.root}", file=sys.stderr)
        return 2

    candidates = _find_candidates(args.root)
    n_done = n_skip = n_fail = 0
    for p in candidates:
        try:
            codec = _probe_codec(p)
        except subprocess.CalledProcessError as e:
            print(f"  ? {p}: ffprobe failed ({e})", file=sys.stderr)
            n_fail += 1
            continue
        if codec == "h264":
            n_skip += 1
            continue
        print(f"  -> {p}  (codec={codec})")
        if args.dry_run:
            n_done += 1
            continue
        bak = p.with_suffix(f".{codec}.bak")
        if bak.exists():
            print(f"  ! {p}: backup {bak.name} already exists, skipping",
                  file=sys.stderr)
            n_fail += 1
            continue
        p.rename(bak)
        try:
            _transcode(bak, p)
        except subprocess.CalledProcessError as e:
            print(f"  ! {p}: ffmpeg failed ({e}), restoring backup",
                  file=sys.stderr)
            if p.exists():
                p.unlink()
            bak.rename(p)
            n_fail += 1
            continue
        n_done += 1

    print(f"done. transcoded={n_done} skipped(h264)={n_skip} failed={n_fail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
