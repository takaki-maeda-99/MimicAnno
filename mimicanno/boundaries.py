# mimicanno/boundaries.py
"""Boundary detectors + integrated weighted score (spec §5.2 / §5.3 / §5.4)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from mimicanno.schema import BoundaryCandidate

# §5.3 default weights — gripper-biased precision policy.
DEFAULT_PHASE1_WEIGHTS: dict[str, float] = {
    "gripper_transition":   0.50,
    "eef_velocity_valley":  0.25,
    "eef_acceleration_peak": 0.15,
    "action_norm_change":   0.10,
}


@dataclass(slots=True)
class RawEvent:
    frame: int
    time: float
    source: str
    source_score: float


# ------------------------------------------------------------------
# Per-source detectors. Each returns a list[RawEvent] in frame order.
# ------------------------------------------------------------------

def detect_gripper_transition(
    gripper: np.ndarray, *, fps: float, delta_threshold: float = 0.30,
) -> list[RawEvent]:
    """Fire on |Δgripper| local peaks above ``delta_threshold`` (§5.2)."""
    if gripper.size < 2:
        return []
    delta = np.abs(np.diff(gripper, prepend=gripper[0]))
    peaks = _local_maxima(delta, threshold=delta_threshold)
    return [
        RawEvent(
            frame=int(i),
            time=float(i) / fps,
            source="gripper_transition",
            source_score=float(np.clip(delta[i] / 0.5, 0.0, 1.0)),
        )
        for i in peaks
    ]


def detect_eef_velocity_valley(
    eef_velocity: np.ndarray, *, fps: float,
    valley_threshold: float = 0.05, min_valley_sec: float = 0.10,
) -> list[RawEvent]:
    """Fire on smoothed |v| local minima below ``valley_threshold`` whose
    duration below threshold is at least ``min_valley_sec`` (§5.2)."""
    if eef_velocity.size < 3:
        return []
    below = eef_velocity < valley_threshold
    min_frames = int(min_valley_sec * fps)
    events: list[RawEvent] = []
    in_valley = False
    start = 0
    for i, is_below in enumerate(below):
        if is_below and not in_valley:
            in_valley = True
            start = i
        elif not is_below and in_valley:
            in_valley = False
            length = i - start
            if length >= min_frames:
                local = eef_velocity[start:i]
                argmin = int(np.argmin(local))
                vmin = float(local[argmin])
                events.append(RawEvent(
                    frame=int(start + argmin),
                    time=(start + argmin) / fps,
                    source="eef_velocity_valley",
                    source_score=float(np.clip(1.0 - vmin / valley_threshold, 0.0, 1.0)),
                ))
    if in_valley:
        length = len(below) - start
        if length >= min_frames:
            local = eef_velocity[start:]
            argmin = int(np.argmin(local))
            vmin = float(local[argmin])
            events.append(RawEvent(
                frame=int(start + argmin),
                time=(start + argmin) / fps,
                source="eef_velocity_valley",
                source_score=float(np.clip(1.0 - vmin / valley_threshold, 0.0, 1.0)),
            ))
    return events


def detect_eef_acceleration_peak(
    eef_acceleration: np.ndarray, *, fps: float, peak_threshold: float = 1.0,
) -> list[RawEvent]:
    """Fire on |a| local maxima above ``peak_threshold`` (§5.2)."""
    peaks = _local_maxima(eef_acceleration, threshold=peak_threshold)
    return [
        RawEvent(
            frame=int(i),
            time=float(i) / fps,
            source="eef_acceleration_peak",
            source_score=float(np.clip(eef_acceleration[i] / (3 * peak_threshold), 0.0, 1.0)),
        )
        for i in peaks
    ]


def detect_action_norm_change(
    action_norm: np.ndarray, *, fps: float,
    change_threshold: float = 0.2, window_sec: float = 0.5,
) -> list[RawEvent]:
    """Rolling-mean change-point on ``||a_t||`` (§5.2).

    For each candidate frame ``i`` in ``[win, n-win]``, compare the mean of
    the ``win``-frame window before ``i`` against the mean of the ``win``-frame
    window after ``i``.  Local maxima of that difference signal above
    ``change_threshold`` are returned as events.
    """
    n = action_norm.size
    win = max(1, int(window_sec * fps))
    if n < 2 * win:
        return []
    cumsum = np.cumsum(np.insert(action_norm, 0, 0.0))
    # delta[j] = |mean_right - mean_left| at position j = win + j (0-indexed)
    n_inner = n - 2 * win
    delta = np.empty(n_inner, dtype=np.float64)
    for j in range(n_inner):
        i = win + j
        left_mean = (cumsum[i] - cumsum[i - win]) / win
        right_mean = (cumsum[i + win] - cumsum[i]) / win
        delta[j] = abs(right_mean - left_mean)
    peaks = _local_maxima(delta, threshold=change_threshold)
    return [
        RawEvent(
            frame=int(win + p),
            time=(win + p) / fps,
            source="action_norm_change",
            source_score=float(np.clip(delta[p] / change_threshold, 0.0, 1.0)),
        )
        for p in peaks
    ]


def _local_maxima(x: np.ndarray, *, threshold: float) -> list[int]:
    """Local maxima of ``x`` above ``threshold``, including plateau members.

    Emits every index ``i`` where ``x[i] >= x[i-1]`` AND ``x[i] >= x[i+1]``
    (non-strict). A flat plateau therefore emits all its constituent
    indices; downstream ``integrated_candidates`` merging collapses
    co-located events within ``merge_window_sec`` into a single candidate
    via the max-merge per-source rule.

    Naive O(n) implementation is adequate for Phase 1 (episode length
    O(10^3) frames); we don't need scipy.signal.find_peaks.
    """
    out: list[int] = []
    for i in range(len(x)):
        if x[i] < threshold:
            continue
        left_ok = i == 0 or x[i] >= x[i - 1]
        right_ok = i == len(x) - 1 or x[i] >= x[i + 1]
        if left_ok and right_ok:
            out.append(i)
    return out


# ------------------------------------------------------------------
# Integrated score and candidate promotion (§5.3).
# ------------------------------------------------------------------

def integrated_candidates(
    events: Iterable[RawEvent],
    *,
    fps: float,
    merge_window_sec: float,
    weights: dict[str, float],
    score_threshold: float,
) -> list[BoundaryCandidate]:
    """Merge events within ``merge_window_sec`` and return promoted candidates.

    Merge policy is **sliding-anchor**: each event is compared against the
    previous event in the current group. Long chains of closely-spaced events
    therefore collapse into a single candidate even when the chain's total
    span exceeds ``merge_window_sec``. This matches §5.3's "merge_window_sec"
    semantics — co-located bursts of detector activity (e.g., a gripper
    transition that fires across multiple smoothed-signal samples) become
    one boundary, not many.

    Same-source merge uses ``max(source_score)`` (§5.3 — explicitly NOT
    last-wins). Disabled sources contribute 0; weights are NOT renormalized.
    """
    sorted_events = sorted(events, key=lambda e: (e.time, e.source))
    if not sorted_events:
        return []

    merged_groups: list[list[RawEvent]] = []
    current: list[RawEvent] = [sorted_events[0]]
    for ev in sorted_events[1:]:
        if ev.time - current[-1].time <= merge_window_sec:
            current.append(ev)
        else:
            merged_groups.append(current)
            current = [ev]
    merged_groups.append(current)

    out: list[BoundaryCandidate] = []
    next_id = 1
    for group in merged_groups:
        # Per §5.3: max over same source; sources sorted unique.
        scores: dict[str, float] = {}
        for ev in group:
            prev = scores.get(ev.source, 0.0)
            if ev.source_score > prev:
                scores[ev.source] = ev.source_score
        score = sum(weights.get(src, 0.0) * s for src, s in scores.items())
        score = float(np.clip(score, 0.0, 1.0))
        if score < score_threshold:
            continue
        median_time = float(np.median([ev.time for ev in group]))
        out.append(BoundaryCandidate(
            id=f"b_{next_id:03d}",
            frame=int(round(median_time * fps)),
            time=median_time,
            sources=sorted(scores.keys()),
            scores=dict(scores),
            score=score,
        ))
        next_id += 1
    return out
