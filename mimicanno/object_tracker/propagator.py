"""Phase 3 propagator dataclasses, Step B grounding, and Propagator class.

Holds the Phase 3 tracking dataclasses (`BBox`, `TrackSample`, `GapEvent`,
`Track`, `TrackingPlan`), the Step B builder `ground_initial_detections`
(spec §2.4.0), and the Step C propagation algorithm `Propagator.run`
(spec §2.4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.track_id import ROLE, make_track_id, slugify

if TYPE_CHECKING:
    from mimicanno.config import TrackingConfig
    from mimicanno.object_tracker.mask_cache import MaskCache
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

GapReason = Literal["sam3_lost", "sam3_low_conf"]


@dataclass(slots=True, frozen=True)
class BBox:
    """Normalized image coords (spec §2.4). (0,0) = top-left, (1,1) = bottom-right.
    All four floats in [0, 1]; w > 0; h > 0; x + w <= 1; y + h <= 1."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        if self.w <= 0.0 or self.h <= 0.0:
            raise ValueError(
                f"BBox w/h must be > 0; got w={self.w}, h={self.h}"
            )
        if not (self.x >= 0.0 and self.x + self.w <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox x out of unit square; x={self.x}, w={self.w}"
            )
        if not (self.y >= 0.0 and self.y + self.h <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox y out of unit square; y={self.y}, h={self.h}"
            )

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def iou(self, other: BBox) -> float:
        """Intersection-over-union in normalized image coords."""
        ix0 = max(self.x, other.x)
        iy0 = max(self.y, other.y)
        ix1 = min(self.x + self.w, other.x + other.w)
        iy1 = min(self.y + self.h, other.y + other.h)
        iw = max(0.0, ix1 - ix0)
        ih = max(0.0, iy1 - iy0)
        inter = iw * ih
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0.0 else 0.0


@dataclass(slots=True, frozen=True)
class TrackSample:
    """One sub-sampled propagation result for a single track (spec §2.4)."""

    frame: int
    time_sec: float
    bbox: BBox
    score: float


@dataclass(slots=True, frozen=True)
class GapEvent:
    """Contiguous frame range where the bbox is invalid / missing (spec §2.4).

    Re-acquisition is implicit (the next sample after a gap), NOT recorded
    here. Mixing range semantics with point semantics ('this single frame
    was a track event') would conflict with `compute_object_signals`'
    'NaN inside gap_events' rule (spec §2.5).
    """

    from_frame: int
    to_frame: int
    reason: GapReason


@dataclass(slots=True)
class Track:
    """One propagated track for one (role, prompt) seed (spec §2.4)."""

    track_id: str
    role: ROLE
    prompt: str
    slug: str
    index: int
    primary: bool
    samples: list[TrackSample] = field(default_factory=list)
    gap_events: list[GapEvent] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class TrackingPlan:
    """Step A + Step B combined; consumed by Propagator.run (spec §2.4.0)."""

    entities: EntityPlan
    initial_detections: dict[tuple[ROLE, str], BBox]
    failed_prompts: list[tuple[ROLE, str]]


# ---------------------------------------------------------------------------
# Step B: ground_initial_detections (spec §2.4.0, Task 16)
# ---------------------------------------------------------------------------


def ground_initial_detections(
    *,
    runtime: SAM3Runtime,
    initial_frame: np.ndarray,
    entities: EntityPlan,
) -> TrackingPlan:
    """Ground each (role, prompt) on the initial frame; take top-scoring bbox.

    For each prompt in entities.all_prompts_with_role(), call
    runtime.ground_on_frame(initial_frame, prompt). Takes the highest-scoring
    bbox; empty result -> failed_prompts entry. Returns the full TrackingPlan
    ready for Propagator.run (Step C).

    Args:
        runtime: SAM3Runtime or test double implementing ground_on_frame.
        initial_frame: The first frame (np.ndarray), used for grounding.
        entities: EntityPlan from Step A, containing prompts organized by role.

    Returns:
        TrackingPlan with initial_detections (highest-score bbox per prompt)
        and failed_prompts (prompts with no detection).
    """
    initial_detections: dict[tuple[ROLE, str], BBox] = {}
    failed_prompts: list[tuple[ROLE, str]] = []

    for role, prompt in entities.all_prompts_with_role():
        results = runtime.ground_on_frame(initial_frame, prompt)
        if not results:
            failed_prompts.append((role, prompt))
            continue
        # Highest-score wins. SAM3Runtime contract returns sorted desc by spec
        # §2.3, but be defensive: max() doesn't assume sortedness.
        best_bbox, _best_score = max(results, key=lambda r: r[1])
        initial_detections[(role, prompt)] = best_bbox

    return TrackingPlan(
        entities=entities,
        initial_detections=initial_detections,
        failed_prompts=failed_prompts,
    )


# ---------------------------------------------------------------------------
# Private helpers (spec §2.4.1)
# ---------------------------------------------------------------------------


def _build_frame_iterator(n_frames: int, stride: int) -> list[int]:
    """Build frame indices: 0, stride, 2*stride, ... always including n_frames - 1."""
    if n_frames == 0:
        return []
    frames = list(range(0, n_frames, stride))
    last = n_frames - 1
    if frames[-1] != last:
        frames.append(last)
    return frames


def _consolidate_gap(pending_reasons: dict[int, GapReason]) -> GapEvent:
    """Build one GapEvent spanning min(frame) to max(frame) in pending.

    Reason is 'sam3_low_conf' if any frame had that reason; else 'sam3_lost'.
    Caller must ensure pending_reasons is non-empty.
    """
    from_frame = min(pending_reasons)
    to_frame = max(pending_reasons)
    reason: GapReason = (
        "sam3_low_conf"
        if any(r == "sam3_low_conf" for r in pending_reasons.values())
        else "sam3_lost"
    )
    return GapEvent(from_frame=from_frame, to_frame=to_frame, reason=reason)


def _role_order(role: ROLE) -> int:
    return {"object": 0, "target": 1, "tool": 2}[role]


def _sort_tracks(tracks: list[Track]) -> list[Track]:
    """Sort by (role_order, slug, index) per spec §2.4.2."""
    return sorted(tracks, key=lambda t: (_role_order(t.role), t.slug, t.index))


def _assign_primary(tracks: list[Track], plan: TrackingPlan) -> None:
    """Mutate tracks in place to set primary=True/False per spec §2.4.1 step 7.

    Per role, find the first prompt (in role-order from plan.entities) that
    survived Step B grounding (is NOT in plan.failed_prompts). The index=0
    occurrence of that prompt gets primary=True; all others get primary=False.
    """
    # Build lookup: (role, prompt) -> list of tracks for that prompt
    track_map: dict[tuple[ROLE, str], list[Track]] = {}
    for track in tracks:
        key = (track.role, track.prompt)
        track_map.setdefault(key, []).append(track)

    # Determine the primary prompt per role
    primary_keys: set[tuple[ROLE, str]] = set()
    role_prompts: list[tuple[ROLE, list[str]]] = [
        ("object", plan.entities.object_prompts),
        ("target", plan.entities.target_prompts),
        ("tool", plan.entities.tool_prompts),
    ]
    for role, prompts in role_prompts:
        for prompt in prompts:
            if (role, prompt) not in plan.failed_prompts and (role, prompt) in track_map:
                primary_keys.add((role, prompt))
                break  # Only the first surviving prompt per role is primary

    # Mark primary=True for index=0 of each primary prompt; False for all others
    for track in tracks:
        key = (track.role, track.prompt)
        track.primary = key in primary_keys and track.index == 0


# ---------------------------------------------------------------------------
# Per-prompt state machine (internal)
# ---------------------------------------------------------------------------


@dataclass
class _PerPromptState:
    role: ROLE
    prompt: str
    completed_tracks: list[Track] = field(default_factory=list)
    current_track: Track | None = None
    pending_gap_reasons: dict[int, GapReason] = field(default_factory=dict)
    last_sample: TrackSample | None = None
    next_index: int = 0

    def _open_track(self) -> Track:
        """Open a new Track and set it as current_track."""
        track = Track(
            track_id=make_track_id(self.role, self.prompt, self.next_index),
            role=self.role,
            prompt=self.prompt,
            slug=slugify(self.prompt),
            index=self.next_index,
            primary=False,  # assigned later by _assign_primary
        )
        self.current_track = track
        return track

    def handle_good_sample(
        self,
        frame: int,
        bbox: BBox,
        score: float,
        fps: float,
        max_gap_frames: int,
        iou_threshold: float,
    ) -> None:
        """Process a frame where detection passes the score threshold."""
        sample = TrackSample(
            frame=frame,
            time_sec=frame / fps,
            bbox=bbox,
            score=score,
        )

        if self.current_track is None:
            # First sample ever: open initial track
            self._open_track()

        assert self.current_track is not None
        if self.last_sample is not None:
            gap_frames = frame - self.last_sample.frame
            if gap_frames > max_gap_frames and self.pending_gap_reasons:
                # Re-acquisition check
                old_bbox = self.last_sample.bbox
                if old_bbox.iou(bbox) >= iou_threshold:
                    # Same track: consolidate gap and continue
                    self.current_track.gap_events.append(
                        _consolidate_gap(self.pending_gap_reasons)
                    )
                    self.pending_gap_reasons = {}
                else:
                    # New track: finalize current, open new one
                    # Consolidate pending gap into the old track
                    if self.pending_gap_reasons:
                        self.current_track.gap_events.append(
                            _consolidate_gap(self.pending_gap_reasons)
                        )
                    self.completed_tracks.append(self.current_track)
                    self.next_index += 1
                    self.pending_gap_reasons = {}
                    self._open_track()
            elif self.pending_gap_reasons:
                # Gap within max_gap_frames: consolidate and continue same track
                self.current_track.gap_events.append(
                    _consolidate_gap(self.pending_gap_reasons)
                )
                self.pending_gap_reasons = {}

        assert self.current_track is not None
        self.current_track.samples.append(sample)
        self.last_sample = sample

    def handle_bad_frame(self, frame: int, reason: GapReason) -> None:
        """Record a gap reason for a frame that failed (None or low-conf)."""
        # Only record if we have opened a track (i.e., there was at least one
        # good sample before), OR if we are still waiting for the first sample.
        # We always record to handle the "immediate loss" case.
        self.pending_gap_reasons[frame] = reason

    def finalize(self, n_frames: int) -> list[Track]:
        """Finalize all tracks after processing all frames.

        Returns the complete list of tracks for this prompt (completed + current).
        Tracks with no samples get a single GapEvent covering [0, n_frames - 1].
        """
        if self.current_track is None:
            # No track was ever opened; this prompt was never even detected
            # (though it had an initial_detection — this shouldn't happen in
            # normal flow since we open a track on first good sample, but
            # if ALL frames were bad, current_track stays None)
            #
            # Create a track with empty samples + synthesized gap
            self._open_track()

        assert self.current_track is not None

        # Flush any remaining pending gap reasons
        if self.pending_gap_reasons:
            self.current_track.gap_events.append(
                _consolidate_gap(self.pending_gap_reasons)
            )
            self.pending_gap_reasons = {}

        # Tracks with no samples: synthesize a gap covering [0, n_frames - 1]
        if not self.current_track.samples and not self.current_track.gap_events:
            self.current_track.gap_events.append(
                GapEvent(from_frame=0, to_frame=n_frames - 1, reason="sam3_lost")
            )

        return [*self.completed_tracks, self.current_track]


# ---------------------------------------------------------------------------
# Propagator (spec §2.4)
# ---------------------------------------------------------------------------


class Propagator:
    """Runs the spec §2.4.1 7-step propagation algorithm."""

    def run(
        self,
        *,
        runtime: Any,
        plan: TrackingPlan,
        video_path: Path,
        fps: float,
        n_frames: int,
        stride: int,
        config: TrackingConfig,
        mask_image_size_px: int | None = None,
    ) -> "tuple[list[Track], MaskCache | None]":
        """Execute propagation per spec §2.4.1.

        Args:
            runtime: SAM3Runtime (real or fixture). Must implement propagate().
            plan: TrackingPlan from Step A + Step B.
            video_path: Path to video (passed through to runtime).
            fps: Frames per second (used for time_sec computation).
            n_frames: Total number of frames in the episode.
            stride: Sub-sampling stride for propagation.
            config: TrackingConfig (thresholds, etc.).
            mask_image_size_px: when set, propagator collects per-frame
                binary masks from the runtime, downsampled to
                ``(mask_image_size_px, mask_image_size_px)``, and returns
                a populated ``MaskCache`` (spec 2026-05-04 §4.4). When
                ``None`` (default), no masks are collected and the cache
                is ``None`` — preserves pre-Task-5 behaviour for callers
                that don't need overlay.

        Returns:
            ``(tracks, mask_cache)``. ``tracks`` is sorted by
            ``(role_order, slug, index)``. ``mask_cache`` is ``None`` when
            ``mask_image_size_px`` was not supplied.
        """
        from mimicanno.object_tracker.mask_cache import (
            MaskCache,
            assign_palette,
            encode_mask,
        )

        if not plan.initial_detections:
            empty_cache: MaskCache | None = None
            if mask_image_size_px is not None:
                empty_cache = MaskCache(
                    by_frame={},
                    shape=(mask_image_size_px, mask_image_size_px),
                    palette={},
                )
            return [], empty_cache

        max_gap_frames = config.effective_max_gap_frames(fps)
        iou_threshold = config.reacquisition_iou_threshold
        min_score = config.min_track_score

        # Step 1: Build frame iterator. _build_frame_iterator includes both
        # the strided sequence AND the final n_frames-1 frame; we hand the
        # whole set to the runtime so SAM3Runtime can filter from sam3's
        # contiguous propagation stream.
        frame_indices = _build_frame_iterator(n_frames, stride)
        expected_frames: set[int] = set(frame_indices)

        # Step 2: Call runtime.propagate exactly once. The runtime owns video
        # I/O — sam3's session-based predictor reads frames from video_path
        # itself (2026-05-04 backend swap). FixtureSAM3Tracker mirrors the
        # same signature but ignores video_path.
        prompts_with_bbox = [
            (prompt, bbox)
            for (role, prompt), bbox in plan.initial_detections.items()
        ]

        mask_size_hw: tuple[int, int] | None = (
            (mask_image_size_px, mask_image_size_px)
            if mask_image_size_px is not None
            else None
        )
        propagation_stream = runtime.propagate(
            video_path=video_path,
            prompts_with_initial_bbox=prompts_with_bbox,
            expected_frames=expected_frames,
            mask_size_hw=mask_size_hw,
        )

        # Initialize per-prompt state machines
        states: dict[tuple[ROLE, str], _PerPromptState] = {
            (role, prompt): _PerPromptState(role=role, prompt=prompt)
            for (role, prompt) in plan.initial_detections
        }

        # Mask collection buffer: {frame_index: {prompt: rle_bytes | None}}.
        # Populated only when mask_image_size_px is set; encoded to RLE on
        # the fly so we keep memory bounded even on long episodes.
        all_prompts = sorted({
            prompt for (_role, prompt) in plan.initial_detections
        })
        collected_masks: dict[int, dict[str, bytes | None]] = {}

        # Step 3: Stream-consume the propagation results
        for result in propagation_stream:
            frame = result.frame
            for (_role, prompt), state in states.items():
                detection = result.detections.get(prompt)
                if detection is not None:
                    bbox, score = detection
                    if score >= min_score:
                        state.handle_good_sample(
                            frame=frame,
                            bbox=bbox,
                            score=score,
                            fps=fps,
                            max_gap_frames=max_gap_frames,
                            iou_threshold=iou_threshold,
                        )
                    else:
                        state.handle_bad_frame(frame, "sam3_low_conf")
                else:
                    state.handle_bad_frame(frame, "sam3_lost")

            if mask_image_size_px is not None:
                per_prompt: dict[str, bytes | None] = {}
                for prompt in all_prompts:
                    raw_mask = result.masks.get(prompt)
                    per_prompt[prompt] = (
                        encode_mask(raw_mask) if raw_mask is not None else None
                    )
                collected_masks[frame] = per_prompt

        # Finalize all tracks
        all_tracks: list[Track] = []
        for state in states.values():
            all_tracks.extend(state.finalize(n_frames))

        # Step 7: Assign primary marks
        _assign_primary(all_tracks, plan)

        mask_cache: MaskCache | None = None
        if mask_image_size_px is not None:
            mask_cache = MaskCache(
                by_frame=collected_masks,
                shape=(mask_image_size_px, mask_image_size_px),
                palette=assign_palette(all_prompts),
            )

        # Return sorted per spec §2.4.2
        return _sort_tracks(all_tracks), mask_cache
