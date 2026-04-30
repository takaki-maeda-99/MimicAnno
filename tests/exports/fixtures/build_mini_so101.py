"""Deterministic builder for the ``mini_so101`` LeRobot v3 fixture.

Run with ``uv run python tests/exports/fixtures/build_mini_so101.py`` from the
repository root. Produces ``tests/exports/fixtures/mini_so101/`` containing a
3-episode SO101-shaped dataset (~20 frames per episode at 15 fps).

The fixture is committed to git so CI can run the export round-trip tests
without re-running this script. Re-running with the same source must produce
byte-identical artifacts (idempotency check in ``test_fixtures.py``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from imageio_ffmpeg import get_ffmpeg_exe  # type: ignore[import-untyped]

FPS = 15
NUM_EPISODES = 3
FRAMES_PER_EPISODE = 20
SEED = 42
GRIPPER_KEYFRAMES = (5.0, 35.0, 5.0, 35.0, 5.0)


def _gripper_pos(frame_index: int) -> float:
    """Sweep open/close: ``5 -> 35 -> 5 -> 35 -> 5`` linearly across an episode."""
    n_keys = len(GRIPPER_KEYFRAMES)
    # Map [0, FRAMES_PER_EPISODE - 1] -> [0, n_keys - 1] linearly.
    pos = (frame_index / (FRAMES_PER_EPISODE - 1)) * (n_keys - 1)
    lo = int(np.floor(pos))
    hi = min(lo + 1, n_keys - 1)
    frac = pos - lo
    return float(
        GRIPPER_KEYFRAMES[lo] * (1.0 - frac) + GRIPPER_KEYFRAMES[hi] * frac
    )


def _episode_table(episode_index: int, global_offset: int) -> pa.Table:
    rng = np.random.default_rng(SEED + episode_index)
    n = FRAMES_PER_EPISODE
    timestamp = [float(i) / FPS for i in range(n)]
    frame_index = list(range(n))
    episode_index_col = [episode_index] * n
    global_index = list(range(global_offset, global_offset + n))
    task_index_col = [0] * n
    # 6-vec joint pos: deterministic per episode (rng + seed offset).
    joint_pos = rng.uniform(-0.5, 0.5, size=(n, 6)).astype(np.float32).tolist()
    gripper_pos = [_gripper_pos(i) for i in range(n)]
    ee_pos = [
        [0.10 + 0.001 * i, 0.20, 0.30] for i in range(n)
    ]
    ee_rotvec = [[0.0, 0.0, 0.01 * i] for i in range(n)]
    return pa.table(
        {
            "timestamp": pa.array(timestamp, type=pa.float64()),
            "frame_index": pa.array(frame_index, type=pa.int64()),
            "episode_index": pa.array(episode_index_col, type=pa.int64()),
            "index": pa.array(global_index, type=pa.int64()),
            "task_index": pa.array(task_index_col, type=pa.int64()),
            "observation.state.joint_pos": pa.array(
                joint_pos, type=pa.list_(pa.float32(), 6)
            ),
            "observation.state.gripper_pos": pa.array(
                gripper_pos, type=pa.float64()
            ),
            "observation.state.ee_pos": pa.array(
                ee_pos, type=pa.list_(pa.float32(), 3)
            ),
            "observation.state.ee_rotvec": pa.array(
                ee_rotvec, type=pa.list_(pa.float32(), 3)
            ),
            "action.gripper_pos": pa.array(gripper_pos, type=pa.float64()),
            "action.ee_pos": pa.array(ee_pos, type=pa.list_(pa.float32(), 3)),
            "action.ee_rotvec": pa.array(
                ee_rotvec, type=pa.list_(pa.float32(), 3)
            ),
            "action.joint_pos": pa.array(
                joint_pos, type=pa.list_(pa.float32(), 6)
            ),
        }
    )


def _info_json() -> dict[str, object]:
    return {
        "codebase_version": "v3.0",
        "total_episodes": NUM_EPISODES,
        "total_frames": NUM_EPISODES * FRAMES_PER_EPISODE,
        "chunks_size": 1000,
        "fps": FPS,
        "splits": {"train": f"0:{NUM_EPISODES}"},
        "data_path": (
            "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet"
        ),
        "video_path": (
            "videos/{video_key}/chunk-{chunk_index:03d}/"
            "episode_{episode_index:06d}.mp4"
        ),
        "features": {
            "timestamp": {"dtype": "float64", "shape": [1], "names": None},
            "frame_index": {"dtype": "int64", "shape": [1], "names": None},
            "episode_index": {"dtype": "int64", "shape": [1], "names": None},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
            "observation.state.joint_pos": {
                "dtype": "float32",
                "shape": [6],
                "names": None,
            },
            "observation.state.gripper_pos": {
                "dtype": "float64",
                "shape": [1],
                "names": None,
            },
            "observation.state.ee_pos": {
                "dtype": "float32",
                "shape": [3],
                "names": None,
            },
            "observation.state.ee_rotvec": {
                "dtype": "float32",
                "shape": [3],
                "names": None,
            },
            "action.gripper_pos": {
                "dtype": "float64",
                "shape": [1],
                "names": None,
            },
            "action.ee_pos": {"dtype": "float32", "shape": [3], "names": None},
            "action.ee_rotvec": {
                "dtype": "float32",
                "shape": [3],
                "names": None,
            },
            "action.joint_pos": {
                "dtype": "float32",
                "shape": [6],
                "names": None,
            },
        },
    }


def _write_tasks_parquet(meta_dir: Path) -> None:
    table = pa.table(
        {
            "task_index": pa.array([0], type=pa.int64()),
            "task": pa.array(["mini test"], type=pa.string()),
        }
    )
    pq.write_table(table, meta_dir / "tasks.parquet")  # type: ignore[no-untyped-call]


def _write_episodes_parquet(episodes_chunk_dir: Path) -> None:
    rows: list[tuple[int, list[str], int, int, int]] = []
    for ep in range(NUM_EPISODES):
        start = ep * FRAMES_PER_EPISODE
        end = start + FRAMES_PER_EPISODE
        rows.append((ep, ["mini test"], FRAMES_PER_EPISODE, start, end))
    table = pa.table(
        {
            "episode_index": pa.array(
                [r[0] for r in rows], type=pa.int64()
            ),
            "tasks": pa.array(
                [r[1] for r in rows], type=pa.list_(pa.string())
            ),
            "length": pa.array([r[2] for r in rows], type=pa.int64()),
            "dataset_from_index": pa.array(
                [r[3] for r in rows], type=pa.int64()
            ),
            "dataset_to_index": pa.array(
                [r[4] for r in rows], type=pa.int64()
            ),
        }
    )
    pq.write_table(  # type: ignore[no-untyped-call]
        table, episodes_chunk_dir / "file-000.parquet"
    )


def _write_placeholder_video(path: Path) -> None:
    """Write a 1x1 single-frame mp4 to ``path`` via ffmpeg.

    The pixel content is irrelevant — no test code reads the frames; we just
    need a valid file at the expected path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_ffmpeg_exe()
    # 1 frame at 1x1 black, stable encode. Re-encoding the same input gives a
    # byte-identical mp4 across runs (no muxer-level timestamps from wallclock).
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel", "error",
        "-f", "lavfi",
        "-i", "color=c=black:s=2x2:r=1:d=1",
        "-frames:v", "1",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def build(out_root: Path) -> None:
    if out_root.exists():
        shutil.rmtree(out_root)
    (out_root / "data" / "chunk-000").mkdir(parents=True)
    (out_root / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (out_root / "videos" / "observation.images.front" / "chunk-000").mkdir(
        parents=True
    )

    # data/ parquets
    global_offset = 0
    for ep in range(NUM_EPISODES):
        table = _episode_table(ep, global_offset)
        pq.write_table(  # type: ignore[no-untyped-call]
            table,
            out_root
            / "data"
            / "chunk-000"
            / f"episode_{ep:06d}.parquet",
        )
        global_offset += FRAMES_PER_EPISODE

    # meta/info.json
    (out_root / "meta" / "info.json").write_text(
        json.dumps(_info_json(), indent=2, sort_keys=True), encoding="utf-8"
    )
    # meta/tasks.parquet
    _write_tasks_parquet(out_root / "meta")
    # meta/episodes/chunk-000/file-000.parquet
    _write_episodes_parquet(out_root / "meta" / "episodes" / "chunk-000")
    # videos placeholders
    for ep in range(NUM_EPISODES):
        _write_placeholder_video(
            out_root
            / "videos"
            / "observation.images.front"
            / "chunk-000"
            / f"episode_{ep:06d}.mp4"
        )


def main() -> None:
    here = Path(__file__).resolve().parent
    build(here / "mini_so101")


if __name__ == "__main__":
    main()
