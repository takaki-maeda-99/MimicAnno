# mimicanno/boundaries.py
"""Boundary detectors + integrated weighted score (spec §5.2 / §5.3 / §5.4)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from mimicanno.config import BoundaryWeights, TrackingConfig
from mimicanno.object_tracker.propagator import Track
from mimicanno.object_tracker.signals import ObjectSignals
from mimicanno.schema import BoundaryCandidate

# §5.3 default weights — gripper-biased precision policy.
DEFAULT_PHASE1_WEIGHTS: dict[str, float] = {
    "gripper_transition": 0.50,
    "eef_velocity_valley": 0.25,
    "eef_acceleration_peak": 0.15,
    "action_norm_change": 0.10,
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
    gripper: np.ndarray,
    *,
    fps: float,
    delta_threshold: float = 0.30,
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
    eef_velocity: np.ndarray,
    *,
    fps: float,
    valley_threshold: float = 0.05,
    min_valley_sec: float = 0.10,
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
                events.append(
                    RawEvent(
                        frame=int(start + argmin),
                        time=(start + argmin) / fps,
                        source="eef_velocity_valley",
                        source_score=float(np.clip(1.0 - vmin / valley_threshold, 0.0, 1.0)),
                    )
                )
    if in_valley:
        length = len(below) - start
        if length >= min_frames:
            local = eef_velocity[start:]
            argmin = int(np.argmin(local))
            vmin = float(local[argmin])
            events.append(
                RawEvent(
                    frame=int(start + argmin),
                    time=(start + argmin) / fps,
                    source="eef_velocity_valley",
                    source_score=float(np.clip(1.0 - vmin / valley_threshold, 0.0, 1.0)),
                )
            )
    return events


def detect_eef_acceleration_peak(
    eef_acceleration: np.ndarray,
    *,
    fps: float,
    peak_threshold: float = 1.0,
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
    action_norm: np.ndarray,
    *,
    fps: float,
    change_threshold: float = 0.2,
    window_sec: float = 0.5,
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


# ------------------------------------------------------------------
# Phase 3 detectors (spec §4.1.1 / §4.1.2)
# ------------------------------------------------------------------


def detect_gripper_object_distance_threshold_crossing(
    per_track_distance: dict[str, np.ndarray],
    *,
    fps: float,
    threshold: float = 0.05,
) -> list[RawEvent]:
    """Emit events when gripper-object distance crosses ``threshold`` (spec §4.1.1).

    ``per_track_distance`` maps object_track_id → per-frame distance array.
    NaN frames are skipped. The windowed-delta score requires both t-w and t+w to
    be valid (non-NaN and within [0, n_frames)); if either is out of range or NaN,
    the event is suppressed.
    """
    if not per_track_distance:
        return []
    events: list[RawEvent] = []
    for _track_id, d in per_track_distance.items():
        n = len(d)
        if n < 2:
            continue
        w = max(1, round(0.10 * fps))
        for t in range(1, n):
            d_prev = d[t - 1]
            d_cur = d[t]
            # Skip NaN frames (spec §4.1.1: NaN frames produce no event)
            if np.isnan(d_prev) or np.isnan(d_cur):
                continue
            # Check for sign change across threshold
            if (d_prev - threshold) * (d_cur - threshold) >= 0:
                continue
            # Edge suppression: windowed delta requires t-w >= 0 and t+w < n
            t_left = t - w
            t_right = t + w
            if t_left < 0 or t_right >= n:
                continue
            # Also suppress if windowed positions are NaN (spec guidance in task)
            if np.isnan(d[t_left]) or np.isnan(d[t_right]):
                continue
            score = float(np.clip(abs(d[t_right] - d[t_left]) / threshold, 0.0, 1.0))
            events.append(
                RawEvent(
                    frame=t,
                    time=float(t) / fps,
                    source="gripper_object_distance_threshold_crossing",
                    source_score=score,
                )
            )
    return events


def detect_object_motion_start_stop(
    per_track_speed: dict[str, np.ndarray],
    *,
    fps: float,
    threshold: float = 0.02,
    min_sec: float = 0.10,
) -> list[RawEvent]:
    """Emit events on sustained object start/stop transitions (spec §4.1.2).

    ``per_track_speed`` maps object_track_id → per-frame speed array.
    NaN frames skip. The sustained window must fully fit on both sides (edge
    suppression: t - window < 0 or t + window - 1 >= n_frames → no event).
    If any frame in either window is NaN, the predicate cannot be verified → skip.
    """
    if not per_track_speed:
        return []
    events: list[RawEvent] = []
    for _track_id, v in per_track_speed.items():
        n = len(v)
        window = max(1, round(min_sec * fps))
        for t in range(n):
            # Edge suppression: both windows must fit
            if t - window < 0 or t + window - 1 >= n:
                continue
            # Before-window: frames [t-window, t)
            before = v[t - window : t]
            # After-window: frames [t, t+window)
            after = v[t : t + window]
            # NaN check: skip if any window frame is NaN
            if np.any(np.isnan(before)) or np.any(np.isnan(after)):
                continue
            before_all_below = bool(np.all(before < threshold))
            after_all_above = bool(np.all(after >= threshold))
            before_all_above = bool(np.all(before >= threshold))
            after_all_below = bool(np.all(after < threshold))
            is_start = before_all_below and after_all_above
            is_stop = before_all_above and after_all_below
            if not (is_start or is_stop):
                continue
            score = float(
                np.clip(
                    max(float(np.mean(before)), float(np.mean(after))) / threshold,
                    0.0,
                    1.0,
                )
            )
            events.append(
                RawEvent(
                    frame=t,
                    time=float(t) / fps,
                    source="object_motion_start_stop",
                    source_score=score,
                )
            )
    return events


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
        out.append(
            BoundaryCandidate(
                id=f"b_{next_id:03d}",
                frame=round(median_time * fps),
                time=median_time,
                sources=sorted(scores.keys()),
                scores=dict(scores),
                score=score,
            )
        )
        next_id += 1
    return out


# ------------------------------------------------------------------
# Phase 3 orchestrator (spec §4.1 / §4.3 / §4.4)
# ------------------------------------------------------------------


class Phase3BoundaryDetector:
    """Runs all 6 Phase 3 boundary detectors and returns promoted candidates.

    Handles disabled_sources auto-derivation from §4.4 conditions. Weights are
    NOT renormalized when sources are disabled (spec §4.4).
    """

    def __init__(
        self,
        *,
        fps: float,
        weights: BoundaryWeights,
        score_threshold: float,
        merge_window_sec: float,
        disabled_sources: list[str],
        tracking_config: TrackingConfig,
    ) -> None:
        self._fps = fps
        self._weights = weights
        self._score_threshold = score_threshold
        self._merge_window_sec = merge_window_sec
        self._disabled_sources = list(disabled_sources)
        self._tracking_config = tracking_config

    def detect(
        self,
        *,
        gripper: np.ndarray,
        eef_vel: np.ndarray,
        eef_accel: np.ndarray,
        action_norm: np.ndarray,
        object_signals: ObjectSignals,
        tracks: list[Track],
    ) -> tuple[list[BoundaryCandidate], list[str]]:
        """Run all 6 detectors and return (candidates, final_disabled_sources).

        ``final_disabled_sources`` is the input list extended with auto-derived
        disabled sources from §4.4.
        """
        # --- §4.4 auto-derive disabled sources ---
        auto_disabled: set[str] = set()

        # No gripper tool track → disable distance source
        if object_signals.gripper_tool_track_id is None:
            auto_disabled.add("gripper_object_distance_threshold_crossing")

        # No role="object" tracks → disable both new sources
        has_object_role = any(t.role == "object" for t in tracks)
        if not has_object_role:
            auto_disabled.add("gripper_object_distance_threshold_crossing")
            auto_disabled.add("object_motion_start_stop")

        # All gripper_object_distance arrays entirely NaN (or empty) → disable distance
        dist_dict = object_signals.gripper_object_distance
        if not dist_dict or all(bool(np.isnan(arr).all()) for arr in dist_dict.values()):
            auto_disabled.add("gripper_object_distance_threshold_crossing")

        # All object_speed arrays entirely NaN (or empty) → disable motion
        speed_dict = object_signals.object_speed
        if not speed_dict or all(bool(np.isnan(arr).all()) for arr in speed_dict.values()):
            auto_disabled.add("object_motion_start_stop")

        final_disabled: set[str] = set(self._disabled_sources) | auto_disabled

        # --- Build detector weights dict (source names, not short keys) ---
        weights_dict: dict[str, float] = {
            "gripper_transition": self._weights.gripper,
            "gripper_object_distance_threshold_crossing": (
                self._weights.gripper_object_distance_threshold_crossing
            ),
            "eef_velocity_valley": self._weights.velocity,
            "object_motion_start_stop": self._weights.object_motion_start_stop,
            "eef_acceleration_peak": self._weights.acceleration,
            "action_norm_change": self._weights.action,
        }

        # --- Collect events from each detector (skip if disabled) ---
        events: list[RawEvent] = []
        tcfg = self._tracking_config
        fps = self._fps

        if "gripper_transition" not in final_disabled:
            events.extend(detect_gripper_transition(gripper, fps=fps))

        if "eef_velocity_valley" not in final_disabled:
            events.extend(detect_eef_velocity_valley(eef_vel, fps=fps))

        if "eef_acceleration_peak" not in final_disabled:
            events.extend(detect_eef_acceleration_peak(eef_accel, fps=fps))

        if "action_norm_change" not in final_disabled:
            events.extend(detect_action_norm_change(action_norm, fps=fps))

        if "gripper_object_distance_threshold_crossing" not in final_disabled:
            events.extend(
                detect_gripper_object_distance_threshold_crossing(
                    object_signals.gripper_object_distance,
                    fps=fps,
                    threshold=tcfg.gripper_object_distance_threshold,
                )
            )

        if "object_motion_start_stop" not in final_disabled:
            events.extend(
                detect_object_motion_start_stop(
                    object_signals.object_speed,
                    fps=fps,
                    threshold=tcfg.object_motion_threshold,
                    min_sec=tcfg.object_motion_min_sec,
                )
            )

        candidates = integrated_candidates(
            events,
            fps=fps,
            merge_window_sec=self._merge_window_sec,
            weights=weights_dict,
            score_threshold=self._score_threshold,
        )

        return candidates, sorted(final_disabled)
