# mimicanno/signals.py
"""Signal smoothing + viewer-side downsampling (spec §5.1, §5.5)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d


@dataclass(slots=True)
class SignalChannel:
    """A 1-D signal sampled uniformly with ``dt_sec`` between samples."""
    name: str
    unit: str
    values: np.ndarray
    dt_sec: float
    t0_sec: float = 0.0


def smoothing_sigma_for_fps(fps: float) -> float:
    """Spec §5.1: sigma ≈ fps * 0.05 (~50 ms)."""
    return fps * 0.05


def gaussian_smooth_1d(x: np.ndarray, *, sigma: float) -> np.ndarray:
    if np.isnan(x).any():
        raise ValueError(
            "gaussian_smooth_1d received NaN values; "
            "upstream code (io_parquet.interpolate_short_nan_spans) should have "
            "interpolated or aborted before reaching signal smoothing.",
        )
    if sigma <= 0:
        return x.astype(np.float64).copy()
    return gaussian_filter1d(x.astype(np.float64), sigma=sigma, mode="reflect")


def downsample_for_viewer(channel: SignalChannel, *, target_hz: float) -> SignalChannel:
    """Decimate ``channel`` to roughly ``target_hz`` for viewer-side rendering.

    The viewer needs (per §5.5) explicit per-channel ``dt_sec``; this function
    chooses an integer decimation factor and updates ``dt_sec`` accordingly.
    No-op if the signal is already at or below ``target_hz``.
    """
    if channel.dt_sec <= 0:
        raise ValueError(
            f"SignalChannel {channel.name!r} has non-positive dt_sec={channel.dt_sec}; "
            f"downsampling requires a strictly positive sample interval.",
        )
    if target_hz <= 0:
        raise ValueError(f"target_hz must be positive; got {target_hz}")
    current_hz = 1.0 / channel.dt_sec
    if current_hz <= target_hz * 1.05:  # already close enough
        return channel
    factor = max(1, int(round(current_hz / target_hz)))
    decimated = channel.values[::factor]
    return SignalChannel(
        name=channel.name,
        unit=channel.unit,
        values=decimated,
        dt_sec=channel.dt_sec * factor,
        t0_sec=channel.t0_sec,
    )
