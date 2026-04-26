"""Extract one episode from a LeRobot v3.0 chunked dataset into single-episode files.

Usage:
    python tools/extract_lerobot_episode.py <dataset-snapshot-dir> <episode_index> <out-dir> [--video-key observation.images.top]

Reads:
    <dataset>/meta/info.json
    <dataset>/meta/episodes/chunk-000/file-000.parquet
    <dataset>/data/chunk-000/file-000.parquet
    <dataset>/videos/<video_key>/chunk-000/file-000.mp4

Writes:
    <out-dir>/<episode_index>.parquet     — only this episode's rows; timestamps reset to start at 0
    <out-dir>/<episode_index>.mp4         — video sliced to this episode's timestamp range
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir", type=Path)
    ap.add_argument("episode_index", type=int)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--video-key", default="observation.images.top")
    args = ap.parse_args()

    info = json.loads((args.dataset_dir / "meta/info.json").read_text())
    fps = float(info["fps"])

    eps_path = args.dataset_dir / "meta/episodes/chunk-000/file-000.parquet"
    eps = pq.read_table(eps_path).to_pylist()
    ep = next((e for e in eps if e["episode_index"] == args.episode_index), None)
    if ep is None:
        print(f"episode {args.episode_index} not found in {eps_path}", file=sys.stderr)
        return 2

    print(f"episode {args.episode_index}: {ep['length']} frames, "
          f"task={ep['tasks'][0]!r}, "
          f"video {ep[f'videos/{args.video_key}/from_timestamp']:.3f}s "
          f"to {ep[f'videos/{args.video_key}/to_timestamp']:.3f}s")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Filter the chunked parquet to this episode and reset timestamp/frame_index.
    chunk_idx = ep["data/chunk_index"]
    file_idx = ep["data/file_index"]
    src_parquet = args.dataset_dir / f"data/chunk-{chunk_idx:03d}/file-{file_idx:03d}.parquet"
    full = pq.read_table(src_parquet)
    mask = pa.compute.equal(full.column("episode_index"), args.episode_index)
    sub = full.filter(mask)
    # Reset timestamp to start at 0 (spec assumes per-episode timestamps).
    ts = sub.column("timestamp").to_numpy().astype("float64")
    ts -= ts[0]
    fi = sub.column("frame_index").to_numpy().astype("int64")
    fi -= fi[0]
    new_cols = {}
    for name in sub.column_names:
        if name == "timestamp":
            new_cols[name] = pa.array(ts, type=pa.float32())
        elif name == "frame_index":
            new_cols[name] = pa.array(fi, type=pa.int64())
        else:
            new_cols[name] = sub.column(name)
    out_table = pa.table(new_cols)
    out_parquet = args.out_dir / f"episode_{args.episode_index:03d}.parquet"
    pq.write_table(out_table, out_parquet)
    print(f"wrote {out_parquet} ({out_table.num_rows} rows)")

    # 2) Slice the chunked mp4 with ffmpeg -ss/-to (re-encode for accurate cut).
    src_video = args.dataset_dir / f"videos/{args.video_key}/chunk-{chunk_idx:03d}/file-{file_idx:03d}.mp4"
    out_video = args.out_dir / f"episode_{args.episode_index:03d}.mp4"
    from_t = ep[f"videos/{args.video_key}/from_timestamp"]
    to_t = ep[f"videos/{args.video_key}/to_timestamp"]
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{from_t:.6f}",
        "-to", f"{to_t:.6f}",
        "-i", str(src_video),
        "-c:v", "libx264",  # re-encode to H.264 for downstream compatibility
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        str(out_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"wrote {out_video} ({out_video.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
