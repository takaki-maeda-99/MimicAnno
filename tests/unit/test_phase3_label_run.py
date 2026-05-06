"""Tests for apply_phase3_labeling + per-segment fallback (spec §5.5, §6).

Step 13.1 — written before implementation (TDD).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.config import TrackingConfig, VLMConfig
from mimicanno.object_tracker.propagator import BBox, GapEvent, Track, TrackSample
from mimicanno.object_tracker.signals import ObjectSignals
from mimicanno.schema import ObjectStateSummary
from mimicanno.vlm_labeler import FixtureVLMLabeler
from tests.unit.helpers_phase1 import make_synthetic_phase1_run

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vlm_config() -> VLMConfig:
    return VLMConfig(
        model_id="fixture", resolved_checkpoint="abc",
        keyframes_per_segment=4, max_retries=3,
    )


def _tracking_config() -> TrackingConfig:
    return TrackingConfig(visibility_threshold=0.5)


def _make_fully_visible_track(
    track_id: str,
    role: str,
    prompt: str,
    primary: bool,
    start_frame: int,
    end_frame: int,
) -> Track:
    """Track with no gaps — fully visible in every segment."""
    samples = [
        TrackSample(
            frame=start_frame,
            time_sec=start_frame / 30.0,
            bbox=BBox(x=0.1, y=0.1, w=0.2, h=0.2),
            score=1.0,
        ),
        TrackSample(
            frame=end_frame,
            time_sec=end_frame / 30.0,
            bbox=BBox(x=0.1, y=0.1, w=0.2, h=0.2),
            score=1.0,
        ),
    ]
    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=prompt,
        slug=track_id,
        index=0,
        primary=primary,
        samples=samples,
        gap_events=[],
    )


def _make_gapped_track(
    track_id: str,
    role: str,
    prompt: str,
    primary: bool,
    start_frame: int,
    end_frame: int,
    gap_start: int,
    gap_end: int,
) -> Track:
    """Track with a single gap covering [gap_start, gap_end]."""
    samples = [
        TrackSample(
            frame=start_frame,
            time_sec=start_frame / 30.0,
            bbox=BBox(x=0.1, y=0.1, w=0.2, h=0.2),
            score=1.0,
        ),
        TrackSample(
            frame=end_frame,
            time_sec=end_frame / 30.0,
            bbox=BBox(x=0.1, y=0.1, w=0.2, h=0.2),
            score=1.0,
        ),
    ]
    return Track(
        track_id=track_id,
        role=role,  # type: ignore[arg-type]
        prompt=prompt,
        slug=track_id,
        index=0,
        primary=primary,
        samples=samples,
        gap_events=[GapEvent(from_frame=gap_start, to_frame=gap_end, reason="sam3_lost")],
    )


def _make_signals(tracks: list[Track], n_frames: int) -> ObjectSignals:
    """Compute ObjectSignals with no gripper track (no distances)."""
    from mimicanno.object_tracker.signals import compute_object_signals
    return compute_object_signals(
        tracks, fps=30.0, n_frames=n_frames, image_aspect_ratio=16.0 / 9.0,
    )


# ---------------------------------------------------------------------------
# Test 1: All segments labeled with object_state (Phase 3 happy path)
# ---------------------------------------------------------------------------


def test_all_segments_phase3_labeled() -> None:
    """3-segment scenario: every segment has visible primary object.

    Expects: all 3 segments labeled with label_source='vlm_with_object_state',
    object_state_unavailable=False, non-empty object_track_ids.
    """
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    # One fully visible primary object track spanning the full episode.
    tracks = [
        _make_fully_visible_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    labeled, _attempts, outcome, coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json"),
    )

    assert outcome.kind == "ok"
    assert len(labeled) == 3

    for seg in labeled:
        assert seg.label_source == "vlm_with_object_state", (
            f"Expected vlm_with_object_state, got {seg.label_source}"
        )
        assert seg.object_state_unavailable is False
        assert len(seg.object_track_ids) > 0
        assert "obj:red_block:0" in seg.object_track_ids

    # coverage = 3/3 = 1.0
    assert coverage == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 2: Single segment falls back to Phase 2 (per-segment fallback)
# ---------------------------------------------------------------------------


def test_single_segment_falls_back() -> None:
    """Segment 1 (index 1) has primary object in gap >50% of frames.

    Segment 0 and 2 are full Phase 3; segment 1 falls back.
    - Segment 1: label_source='vlm_robot_state_only', object_state_unavailable=True,
      object_track_ids=[].
    - Segments 0 and 2: label_source='vlm_with_object_state'.
    """
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    # Track is fully visible in segments 0 and 2 (frames 0-9 and 20-29).
    # In segment 1 (frames 10-19): gap covers frames 10-19 (all 10 frames = 100% gap).
    # 0 non-gap frames → visibility = 0.0 < 0.5 → fallback for segment 1.
    tracks = [
        _make_gapped_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=10, gap_end=19,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    labeled, _attempts, outcome, _coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json"),
    )

    assert outcome.kind == "ok"
    assert len(labeled) == 3

    seg0 = labeled[0]
    seg1 = labeled[1]
    seg2 = labeled[2]

    # Segment 0: Phase 3 success
    assert seg0.label_source == "vlm_with_object_state"
    assert seg0.object_state_unavailable is False
    assert "obj:red_block:0" in seg0.object_track_ids

    # Segment 1: per-segment fallback
    assert seg1.label_source == "vlm_robot_state_only"
    assert seg1.object_state_unavailable is True
    assert seg1.object_track_ids == []

    # Segment 2: Phase 3 success
    assert seg2.label_source == "vlm_with_object_state"
    assert seg2.object_state_unavailable is False
    assert "obj:red_block:0" in seg2.object_track_ids


# ---------------------------------------------------------------------------
# Test 3: LabelAttempt.notes includes "phase3_per_segment_fallback" for fallback only
# ---------------------------------------------------------------------------


def test_label_attempt_notes_fallback_only() -> None:
    """Fallback segment's LabelAttempt.notes must contain 'phase3_per_segment_fallback'.

    Non-fallback segments must NOT have this note.
    """
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    # Segment 1 gap = full 10 frames → fallback
    tracks = [
        _make_gapped_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=10, gap_end=19,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    _labeled, attempts, _outcome, _coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json"),
    )

    fallback_attempt = next(a for a in attempts if a.segment_id == segs[1].segment_id)
    ok_attempts = [a for a in attempts if a.segment_id != segs[1].segment_id]

    assert "phase3_per_segment_fallback" in fallback_attempt.notes
    for a in ok_attempts:
        assert "phase3_per_segment_fallback" not in a.notes


# ---------------------------------------------------------------------------
# Test 4: object_state_segment_coverage computed correctly
# ---------------------------------------------------------------------------


def test_coverage_fraction_2_of_3() -> None:
    """2 Phase 3 segments + 1 fallback → coverage = 2/3."""
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    tracks = [
        _make_gapped_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=10, gap_end=19,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    _labeled, _attempts, _outcome, coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json"),
    )

    assert coverage == pytest.approx(2.0 / 3.0)


# ---------------------------------------------------------------------------
# Test 5: run-level object_state_available is True even with 1 fallback (§6.4)
# ---------------------------------------------------------------------------


def test_run_level_outcome_ok_with_fallback() -> None:
    """Per-segment fallback is NOT a degrade → outcome.kind == 'ok' (§6.4)."""
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    tracks = [
        _make_gapped_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=10, gap_end=19,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    _labeled, _attempts, outcome, _coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json"),
    )

    # Per §6.4: per-segment fallback is NOT a degrade
    assert outcome.kind == "ok"
    assert outcome.degrade_reason is None


# ---------------------------------------------------------------------------
# Test 6: Phase 2 prompt byte-identity for fallback segments
# (verified by inspecting the VLMRequest passed to the labeler)
# ---------------------------------------------------------------------------


def test_fallback_segment_uses_phase2_prompt() -> None:
    """Fallback segment's VLMRequest has object_state_summary absent/None (Phase 2 mode).

    Phase 3 segments have a non-None object_state_summary in their VLMRequest.
    """
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 3
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    tracks = [
        _make_gapped_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=10, gap_end=19,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    # Intercept label_segment calls to inspect each VLMRequest
    received_requests: list[dict] = []  # type: ignore[type-arg]
    real_labeler = FixtureVLMLabeler(FIXT / "ok_first_try.json")

    class RecordingLabeler:
        def model_identity(self):  # type: ignore[no-untyped-def]
            return real_labeler.model_identity()

        def label_segment(self, request, attempt, last_reject_reason=None):  # type: ignore[no-untyped-def]
            received_requests.append(dict(request))
            return real_labeler.label_segment(request, attempt, last_reject_reason)

    _labeled, _attempts, _outcome, _coverage = apply_phase3_labeling(
        segments=segs,
        tracks=tracks,
        object_signals=signals,
        extractor=extractor,
        gripper=gripper,
        eef_velocity=eef,
        episode_meta=meta,
        config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: RecordingLabeler(),
    )

    # 3 segments → 3 label_segment calls
    assert len(received_requests) == 3

    fallback_seg_id = segs[1].segment_id
    fallback_reqs = [r for r in received_requests if r["segment_id"] == fallback_seg_id]
    phase3_reqs = [r for r in received_requests if r["segment_id"] != fallback_seg_id]

    assert len(fallback_reqs) == 1
    # Fallback: object_state_summary absent or None → Phase 2 mode
    oss = fallback_reqs[0].get("object_state_summary")
    assert oss is None, (
        f"Fallback segment must have object_state_summary=None (Phase 2 mode), got {oss!r}"
    )

    # Phase 3 segments: non-None object_state_summary
    assert len(phase3_reqs) == 2
    for req in phase3_reqs:
        oss3 = req.get("object_state_summary")
        assert oss3 is not None, (
            "Phase 3 segment must have non-None object_state_summary"
        )


# ---------------------------------------------------------------------------
# Test 7: visible_track_ids on ObjectStateSummary (Option B prerequisite)
# ---------------------------------------------------------------------------


def test_object_state_summary_has_visible_track_ids() -> None:
    """ObjectStateSummary.visible_track_ids contains the track_ids that passed
    the visibility filter (Option B — single source of truth)."""
    from mimicanno.clip_features import compute_object_state_summary

    n_frames = 10
    tracks = [
        _make_fully_visible_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
        ),
    ]
    signals = _make_signals(tracks, n_frames)
    config = TrackingConfig(visibility_threshold=0.5)

    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=n_frames - 1,
        object_signals=signals,
        config=config,
    )

    assert summary is not None
    assert hasattr(summary, "visible_track_ids")
    assert "obj:red_block:0" in summary.visible_track_ids


def test_visible_track_ids_excludes_below_threshold() -> None:
    """Track below visibility threshold must NOT appear in visible_track_ids."""
    from mimicanno.clip_features import compute_object_state_summary

    # 10-frame segment. Primary track is fully visible (no gap).
    # Non-primary track has 100% gap → not visible → not in visible_track_ids.
    n_frames = 10
    tracks = [
        _make_fully_visible_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
        ),
        _make_gapped_track(
            "obj:blue_block:1", "object", "blue block", primary=False,
            start_frame=0, end_frame=n_frames - 1,
            gap_start=0, gap_end=n_frames - 1,
        ),
    ]
    signals = _make_signals(tracks, n_frames)
    config = TrackingConfig(visibility_threshold=0.5)

    summary = compute_object_state_summary(
        tracks,
        segment_start_frame=0,
        segment_end_frame=n_frames - 1,
        object_signals=signals,
        config=config,
    )

    assert summary is not None
    assert "obj:red_block:0" in summary.visible_track_ids
    assert "obj:blue_block:1" not in summary.visible_track_ids


# ---------------------------------------------------------------------------
# Test 8: visible_track_ids round-trips through to_dict / from_dict
# ---------------------------------------------------------------------------


def test_visible_track_ids_roundtrip() -> None:
    """visible_track_ids survives to_dict / from_dict round-trip."""
    original = ObjectStateSummary(
        object_prompts=["red block"],
        target_prompts=[],
        tool_prompts=[],
        visible_track_ids=["obj:red_block:0"],
        gripper_object_distance_at_start=None,
        gripper_object_distance_at_end=None,
        gripper_object_distance_min=None,
        primary_object_displacement=None,
        primary_object_max_speed=None,
        primary_object_at_target_at_end=None,
    )
    d = original.to_dict()
    assert "visible_track_ids" in d
    assert d["visible_track_ids"] == ["obj:red_block:0"]

    restored = ObjectStateSummary.from_dict(d)
    assert restored.visible_track_ids == ["obj:red_block:0"]


# ---------------------------------------------------------------------------
# Task 8 (vlm-mask-overlay): MaskCache propagation through apply_phase3_labeling
# ---------------------------------------------------------------------------


def test_mask_cache_threaded_through_to_request() -> None:
    """Task 8: mask_cache + alpha → labeler.label_segment(...) sees a request
    whose mask_overlay_legend is set per spec §6.1.

    Uses a probe labeler that captures the request and short-circuits.
    Doesn't run a real Gemma — only verifies wiring.
    """
    import numpy as np

    from mimicanno.object_tracker.mask_cache import MaskCache, encode_mask
    from mimicanno.vlm_labeler import apply_phase3_labeling

    n_segments = 2
    frames_per_seg = 10
    n_frames = n_segments * frames_per_seg

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(
        n_segments=n_segments, fps=30.0, frames_per_seg=frames_per_seg,
    )
    tracks = [
        _make_fully_visible_track(
            "obj:red_block:0", "object", "red block", primary=True,
            start_frame=0, end_frame=n_frames - 1,
        ),
    ]
    signals = _make_signals(tracks, n_frames)

    # Fill every keyframe-eligible frame with a non-empty mask so the
    # legend is non-None for both segments.
    full_mask = np.ones((4, 4), dtype=bool)
    by_frame = {f: {"red block": encode_mask(full_mask)} for f in range(n_frames)}
    cache = MaskCache(
        by_frame=by_frame, shape=(4, 4),
        palette={"red block": (214, 39, 40)},  # red
    )

    captured: list[dict] = []

    class _ProbeLabeler:
        def label_segment(self, request, attempt, last_reject_reason=None):
            captured.append(dict(request))
            from mimicanno.vlm_labeler import VLMResponse
            return VLMResponse(
                phase="approach_object", verb="approach", object="red block",
                target=None, vlm_confidence=0.9, evidence=None,
            )

    apply_phase3_labeling(
        segments=segs, tracks=tracks, object_signals=signals,
        extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=_vlm_config(),
        tracking_config=_tracking_config(),
        labeler_factory=lambda c: _ProbeLabeler(),
        mask_cache=cache, mask_alpha=0.4,
    )

    assert len(captured) == n_segments
    for req in captured:
        legend = req.get("mask_overlay_legend")
        assert legend is not None
        assert "red=red block" in legend
        # Spec §6.1 wording sanity check.
        assert "Colored translucent overlays" in legend
