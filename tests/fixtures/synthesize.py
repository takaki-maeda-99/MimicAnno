"""Programmatic generators for synthetic LeRobot episodes used in tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(slots=True)
class SyntheticEpisode:
    episode_id: str
    video: Path
    parquet: Path


def _write_mp4(
    path: Path, n_frames: int, fps: float, *, width: int = 64, height: int = 64
) -> Path:
    writer = imageio_ffmpeg.write_frames(
        str(path),
        size=(width, height),
        fps=int(fps),
        codec="libx264",
        macro_block_size=1,
        quality=8,
    )
    writer.send(None)
    for i in range(n_frames):
        # Simple gradient that advances each frame so SAM3 (later phases) sees motion.
        frame = np.full((height, width, 3), (i * 4) % 255, dtype=np.uint8)
        frame[:, :, 1] = (i * 7) % 255
        writer.send(frame.tobytes())
    writer.close()
    return path


def synthesize_aloha_episode(
    out_dir: Path,
    *,
    n_frames: int = 120,
    fps: float = 30.0,
    episode_id: str = "ep_synth_000",
) -> SyntheticEpisode:
    out_dir.mkdir(parents=True, exist_ok=True)
    video = _write_mp4(out_dir / f"{episode_id}.mp4", n_frames=n_frames, fps=fps)

    rng = np.random.default_rng(0)
    state = rng.uniform(-0.5, 0.5, size=(n_frames, 14)).astype(np.float64)
    # Cumulative EEF position (small steps).
    state[:, 0:3] = np.cumsum(
        rng.normal(0, 0.005, size=(n_frames, 3)),
        axis=0,
    )
    # Inject a clear gripper close at frame 50 and open at frame 90 so the test
    # can assert at least one boundary candidate is emitted.
    gripper = np.ones(n_frames)
    gripper[50:90] = 0.0
    state[:, 13] = gripper
    action = rng.uniform(-0.1, 0.1, size=(n_frames, 14)).astype(np.float64)
    timestamps = (np.arange(n_frames) / fps).astype(np.float64)

    table = pa.table(
        {
            "observation.state": pa.array(state.tolist()),
            "action": pa.array(action.tolist()),
            "timestamp": pa.array(timestamps.tolist()),
        }
    )
    parquet = out_dir / f"{episode_id}.parquet"
    pq.write_table(table, parquet)

    return SyntheticEpisode(episode_id=episode_id, video=video, parquet=parquet)


def synthesize_koch_episode(
    out_dir: Path,
    *,
    n_frames: int = 120,
    fps: float = 30.0,
    episode_id: str = "ep_synth_koch_000",
) -> SyntheticEpisode:
    """Joint-only state — no Cartesian EEF columns. Triggers EEF-disabled path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    video = _write_mp4(out_dir / f"{episode_id}.mp4", n_frames=n_frames, fps=fps)

    rng = np.random.default_rng(1)
    state = rng.uniform(-0.5, 0.5, size=(n_frames, 6)).astype(np.float64)
    gripper = np.ones(n_frames)
    gripper[60:] = 0.0
    state[:, 5] = gripper
    action = rng.uniform(-0.1, 0.1, size=(n_frames, 6)).astype(np.float64)
    timestamps = (np.arange(n_frames) / fps).astype(np.float64)

    table = pa.table(
        {
            "observation.state": pa.array(state.tolist()),
            "action": pa.array(action.tolist()),
            "timestamp": pa.array(timestamps.tolist()),
        }
    )
    parquet = out_dir / f"{episode_id}.parquet"
    pq.write_table(table, parquet)
    return SyntheticEpisode(episode_id=episode_id, video=video, parquet=parquet)


def synthesize_minimal_mp4(
    out_dir: Path, n_frames: int, *, width: int = 64, height: int = 48,
    fps: float = 30.0,
) -> Path:
    """Render an n_frames mp4 using the same _write_mp4 helper used by the
    full-episode synthesizer. Returns the file path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "minimal.mp4"
    return _write_mp4(path, n_frames=n_frames, fps=fps, width=width, height=height)
