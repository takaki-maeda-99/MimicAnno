"""Split the single LegrandFrederic/Marker_pickup_piper parquet+mp4 into
per-episode SO101-style files under data/Piper/.

For each requested episode_index this writes:
  data/Piper/data/chunk-000/episode_{NNNNNN}.parquet
  data/Piper/videos/chunk-000/observation.images.front/episode_{NNNNNN}.mp4

The parquet adds a synthesized scalar column ``observation.state.gripper_pos``
(=`observation.state[6]`) so MimicAnno's GenericAdapter (which expects a
scalar gripper column) can consume it without modification. Original
aggregated `observation.state` is preserved as well.

NOTE on camera path naming: the destination directory is
``observation.images.front/`` to mirror the SO101 layout MimicAnno expects,
but the **source bytes come from the upstream dataset's
``observation.images.secondary_0/`` (overhead) camera**, NOT the wrist
``main`` view. See the rationale on ``SRC_VID_OVERHEAD`` below — the
local ``data/Piper/`` dir is gitignored, so this docstring is the
canonical record of the rename.

Usage:
  uv run python scripts/prep_piper_episodes.py 0          # just ep0
  uv run python scripts/prep_piper_episodes.py 0 1 2 ...  # subset
  uv run python scripts/prep_piper_episodes.py all        # all 39 eps
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HF_CACHE = Path.home() / ".cache/huggingface/lerobot/LegrandFrederic/Marker_pickup_piper"
SRC_PARQ = HF_CACHE / "data/chunk-000/file-000.parquet"
# Use the overhead (secondary_0) camera, not the wrist-mounted "main" camera:
# direct SAM3 grounding tests on 2026-05-12 showed the wrist view yields 0
# detections for "marker" / "pen" / generic prompts, while secondary_0 grounds
# at score 0.94. SO101 uses an external static cam ("front") similarly.
SRC_VID_OVERHEAD = HF_CACHE / "videos/observation.images.secondary_0/chunk-000/file-000.mp4"
SRC_EP_META = HF_CACHE / "meta/episodes/chunk-000/file-000.parquet"

DST_ROOT = Path("/misc/dl00/gayagaya/MimicAnno/data/Piper")
DST_PARQ_DIR = DST_ROOT / "data/chunk-000"
DST_VID_DIR = DST_ROOT / "videos/chunk-000/observation.images.front"


def _load_ep_ranges() -> dict[int, tuple[int, int, float, float]]:
    em = pq.read_table(SRC_EP_META)
    out: dict[int, tuple[int, int, float, float]] = {}
    for i in range(em.num_rows):
        ep = int(em.column("episode_index")[i].as_py())
        out[ep] = (
            int(em.column("dataset_from_index")[i].as_py()),
            int(em.column("dataset_to_index")[i].as_py()),
            float(em.column("videos/observation.images.main/from_timestamp")[i].as_py()),
            float(em.column("videos/observation.images.main/to_timestamp")[i].as_py()),
        )
    return out


def _build_episode_parquet(src: pa.Table, row_from: int, row_to: int) -> pa.Table:
    sub = src.slice(row_from, row_to - row_from)
    state = np.array(sub.column("observation.state").to_pylist(), dtype=np.float64)
    gripper_pos = state[:, 6].astype(np.float32)
    # Reset timestamps to start at 0 so MimicAnno's fps resolver sees a clean
    # episode (it requires strict monotonicity and consistent dt).
    ts = np.array(sub.column("timestamp").to_pylist(), dtype=np.float64)
    ts_zeroed = (ts - ts[0]).astype(np.float32)
    sub = sub.set_column(
        sub.column_names.index("timestamp"),
        "timestamp",
        pa.array(ts_zeroed, type=pa.float32()),
    )
    sub = sub.append_column(
        "observation.state.gripper_pos",
        pa.array(gripper_pos, type=pa.float32()),
    )
    return sub


def _slice_video(src_mp4: Path, dst_mp4: Path, t_from: float, t_to: float) -> None:
    duration = t_to - t_from
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{t_from:.6f}", "-i", str(src_mp4),
        "-t", f"{duration:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-an",
        str(dst_mp4),
    ]
    subprocess.run(cmd, check=True)


def prep(ep: int, src_table: pa.Table, ranges: dict[int, tuple[int, int, float, float]]) -> None:
    if ep not in ranges:
        raise SystemExit(f"episode_index {ep} not in dataset (have 0..{max(ranges)})")
    row_from, row_to, t_from, t_to = ranges[ep]
    dst_parq = DST_PARQ_DIR / f"episode_{ep:06d}.parquet"
    dst_vid = DST_VID_DIR / f"episode_{ep:06d}.mp4"
    DST_PARQ_DIR.mkdir(parents=True, exist_ok=True)
    DST_VID_DIR.mkdir(parents=True, exist_ok=True)

    table = _build_episode_parquet(src_table, row_from, row_to)
    pq.write_table(table, dst_parq)
    _slice_video(SRC_VID_OVERHEAD, dst_vid, t_from, t_to)
    print(
        f"ep{ep:03d}: rows={row_to-row_from}  ts=[{t_from:.2f}..{t_to:.2f}]  "
        f"-> {dst_parq.name}, {dst_vid.name}"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found in PATH")
    src_table = pq.read_table(SRC_PARQ)
    ranges = _load_ep_ranges()

    if sys.argv[1] == "all":
        eps = sorted(ranges)
    else:
        eps = [int(a) for a in sys.argv[1:]]

    for ep in eps:
        prep(ep, src_table, ranges)


if __name__ == "__main__":
    main()
