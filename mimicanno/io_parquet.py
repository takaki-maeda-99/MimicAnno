# mimicanno/io_parquet.py
"""Parquet loading + FPS resolution + NaN gap handling (spec §7.1 / §7.3 / §7.4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicanno.hashing import sha256_file


class ParquetLoadError(Exception):
    """Raised on any parquet schema / shape / consistency problem worth aborting on."""


@dataclass(slots=True)
class LoadedEpisode:
    table: pa.Table
    sha256: str  # "sha256:<hex>"


# Only `timestamp` is universally required at the loader layer. Adapter-specific
# state columns (e.g. legacy aggregated `observation.state`, or split
# `observation.state.{joint_pos, ee_pos, ...}` for LeRobot v3 / SO101) are the
# adapter's responsibility — they raise their own error on first access if
# missing. This decoupling lets one loader handle both v2 (aggregated state
# vector) and v3 (split per-field) parquet layouts.
REQUIRED_COLUMNS: tuple[str, ...] = ("timestamp",)
# action is optional in Phase 1 (spec §7.1)
OPTIONAL_COLUMNS: tuple[str, ...] = ("action", "frame_index", "episode_index")


def load_episode_parquet(path: Path) -> LoadedEpisode:
    if not path.exists():
        raise ParquetLoadError(f"parquet file not found: {path}")
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    missing = [c for c in REQUIRED_COLUMNS if c not in table.column_names]
    if missing:
        raise ParquetLoadError(
            f"parquet missing required column(s): {missing} (file={path})",
        )
    return LoadedEpisode(table=table, sha256="sha256:" + sha256_file(path))


def resolve_fps(timestamps: np.ndarray) -> float:
    """Compute FPS from timestamps (spec §7.3 step 2)."""
    if timestamps.ndim != 1 or timestamps.size < 2:
        raise ParquetLoadError("timestamp column too short to resolve fps")
    diffs = np.diff(timestamps)
    if (diffs <= 0).any():
        raise ParquetLoadError("timestamps must be strictly monotonic")
    median = float(np.median(diffs))
    std = float(np.std(diffs))
    rel = std / median if median > 0 else float("inf")
    if rel > 0.05:
        raise ParquetLoadError(
            f"timestamp variance too high to resolve fps "
            f"(std/median = {rel:.3f}; threshold 0.05). "
            "Provide fps via episode metadata.",
        )
    return 1.0 / median


def interpolate_short_nan_spans(
    x: np.ndarray,
    *,
    fps: float,
    max_span_sec: float = 0.5,
) -> np.ndarray:
    """Linear-interpolate NaN spans no longer than ``max_span_sec``; abort longer ones."""
    if x.ndim != 1:
        raise ValueError("interpolate_short_nan_spans expects 1-D")
    out = x.astype(np.float64).copy()
    isnan = np.isnan(out)
    if not isnan.any():
        return out
    max_span_frames = int(max_span_sec * fps)
    # Find consecutive NaN runs.
    in_span = False
    span_start = 0
    for i, missing in enumerate(isnan):
        if missing and not in_span:
            in_span = True
            span_start = i
        elif not missing and in_span:
            in_span = False
            span_len = i - span_start
            if span_len > max_span_frames:
                raise ParquetLoadError(
                    f"NaN span of {span_len} frames "
                    f"(>{max_span_sec}s @ {fps}fps) at frames {span_start}..{i - 1}",
                )
    if in_span:
        span_len = len(out) - span_start
        if span_len > max_span_frames:
            raise ParquetLoadError(
                f"NaN span of {span_len} frames extends to end "
                f"(>{max_span_sec}s @ {fps}fps) starting at frame {span_start}",
            )
    # All spans are short — interpolate.
    # All-NaN: cannot interpolate without any anchor.
    if not (~isnan).any():
        raise ParquetLoadError("column is entirely NaN; cannot interpolate")
    if isnan[0]:
        raise ParquetLoadError(
            "NaN span starts at frame 0 (no left anchor for interpolation)",
        )
    if isnan[-1]:
        raise ParquetLoadError(
            "NaN span extends to last frame (no right anchor for interpolation)",
        )
    idx = np.arange(len(out))
    out[isnan] = np.interp(idx[isnan], idx[~isnan], out[~isnan])
    return out
