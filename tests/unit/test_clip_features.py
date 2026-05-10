"""ClipFeatureExtractor (spec §2.7, §3.1)."""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.clip_features import (
    compute_keyframe_offsets,
    compute_robot_state_summary,
)
from mimicanno.config import ClipFeatureConfig

# ---- compute_keyframe_offsets ---------------------------------------------

def test_keyframe_offsets_K4_long_segment() -> None:
    # 30 fps, 90 frames spanning [0, 90), K=4 → start, +30, +60, +89
    offs = compute_keyframe_offsets(start_frame=0, end_frame=89, k=4)
    assert offs == [0, 30, 59, 89]


def test_keyframe_offsets_K2_returns_endpoints() -> None:
    offs = compute_keyframe_offsets(start_frame=10, end_frame=20, k=2)
    assert offs == [10, 20]


def test_keyframe_offsets_K1_branch() -> None:
    """K_effective == 1 must NOT divide by zero (spec §2.7)."""
    offs = compute_keyframe_offsets(start_frame=5, end_frame=5, k=1)
    assert offs == [5]


def test_keyframe_offsets_short_segment_reduces_K() -> None:
    # 2-frame segment [0, 1] requested with K=4 → K_effective = 2.
    offs = compute_keyframe_offsets(start_frame=0, end_frame=1, k=4)
    assert offs == [0, 1]


# ---- compute_robot_state_summary ------------------------------------------

def test_summary_no_eef_returns_null_speed_and_dwell() -> None:
    """When EEF velocity is unavailable, both mean_eef_speed_mps and
    dwell_fraction MUST be None (spec §2.4 ClipFeatureConfig note)."""
    fps = 30.0
    gripper = np.linspace(0.0, 1.0, num=30, dtype=np.float64)
    cfg = ClipFeatureConfig()
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["mean_eef_speed_mps"] is None
    assert summ["dwell_fraction"] is None
    assert summ["duration_sec"] == pytest.approx(1.0)


def test_summary_gripper_open_fraction_threshold() -> None:
    """gripper_open_fraction is the time-weighted average of (g >= threshold)."""
    fps = 30.0
    # First half closed (0.0), second half open (1.0). Threshold default 0.5.
    gripper = np.concatenate([np.zeros(15), np.ones(15)]).astype(np.float64)
    cfg = ClipFeatureConfig(gripper_open_threshold=0.5)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["gripper_open_fraction"] == pytest.approx(0.5)


def test_summary_gripper_transitions_count() -> None:
    """gripper_transitions counts threshold crossings."""
    fps = 30.0
    gripper = np.array([0.0, 1.0, 0.0, 1.0, 0.0])  # 4 crossings
    cfg = ClipFeatureConfig(gripper_open_threshold=0.5)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=4, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["gripper_transitions"] == 4


def test_summary_dwell_fraction_with_eef() -> None:
    """dwell_fraction is the fraction of time |eef_velocity| < threshold."""
    fps = 30.0
    gripper = np.zeros(30)
    # First 10 frames "fast" (>= 0.1), next 20 frames "dwell" (< 0.01).
    eef_vel = np.zeros((30, 3), dtype=np.float64)
    eef_vel[:10, 0] = 0.1
    eef_vel[10:, 0] = 0.005
    cfg = ClipFeatureConfig(dwell_speed_threshold_mps=0.01)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=eef_vel, cfg=cfg,
    )
    assert summ["dwell_fraction"] == pytest.approx(20 / 30)
    assert summ["mean_eef_speed_mps"] is not None


def test_clip_feature_extractor_composes(tmp_path) -> None:
    """ClipFeatureExtractor.extract() returns frames + summary."""
    from mimicanno.clip_features import ClipFeatureExtractor
    from mimicanno.schema import BoundaryRef, SubtaskSegment
    from tests.fixtures.synthesize import synthesize_minimal_mp4
    video = synthesize_minimal_mp4(tmp_path, n_frames=30, width=64, height=48)
    seg = SubtaskSegment(
        segment_id="s_000", episode_id="ep", start_frame=0, end_frame=29,
        start_time=0.0, end_time=1.0, phase="unlabeled",
        verb=None, object=None, target=None, failure_flags=[],
        label_source="signals_only", object_state_unavailable=True,
        object_track_ids=[], label_version="manipulation.v1",
        start_boundary=BoundaryRef(None, 0.0, ["episode_start"], 1.0),
        end_boundary=BoundaryRef(None, 1.0, ["episode_end"], 1.0),
        boundary_confidence=1.0, vlm_confidence=None,
        overall_confidence=1.0, evidence=None, reviewed=False, reviewer_id=None,
    )
    extractor = ClipFeatureExtractor(
        video_path=video, fps=30.0,
        clip_features_config=ClipFeatureConfig(),
        image_size_px=64,
    )
    feat = extractor.extract(
        segment=seg,
        gripper=np.zeros(30, dtype=np.float64),
        eef_velocity=None,
        keyframes_per_segment=4,
    )
    assert len(feat.keyframes) == 4
    assert feat.keyframe_offsets_sec[0] == pytest.approx(0.0)
    assert feat.robot_state_summary["mean_eef_speed_mps"] is None


# ---------------------------------------------------------------------------
# Task 6 (vlm-mask-overlay): mask_cache plumbing on ClipFeatureExtractor
# ---------------------------------------------------------------------------


def _make_segment_for_overlay() -> "SubtaskSegment":  # type: ignore[name-defined]
    from mimicanno.schema import BoundaryRef, SubtaskSegment
    return SubtaskSegment(
        segment_id="s_000", episode_id="ep", start_frame=0, end_frame=29,
        start_time=0.0, end_time=1.0, phase="unlabeled",
        verb=None, object=None, target=None, failure_flags=[],
        label_source="signals_only", object_state_unavailable=True,
        object_track_ids=[], label_version="manipulation.v1",
        start_boundary=BoundaryRef(None, 0.0, ["episode_start"], 1.0),
        end_boundary=BoundaryRef(None, 1.0, ["episode_end"], 1.0),
        boundary_confidence=1.0, vlm_confidence=None,
        overall_confidence=1.0, evidence=None, reviewed=False, reviewer_id=None,
    )


def test_extract_with_mask_cache_none_is_bit_exact_to_default(tmp_path) -> None:
    """Spec §7.4: mask_cache=None must be pixel-exact to pre-Task-6 path."""
    from mimicanno.clip_features import ClipFeatureExtractor
    from tests.fixtures.synthesize import synthesize_minimal_mp4

    video = synthesize_minimal_mp4(tmp_path, n_frames=30, width=64, height=48)
    seg = _make_segment_for_overlay()
    extractor = ClipFeatureExtractor(
        video_path=video, fps=30.0,
        clip_features_config=ClipFeatureConfig(),
        image_size_px=64,
    )
    base = extractor.extract(
        segment=seg, gripper=np.zeros(30), eef_velocity=None,
        keyframes_per_segment=4,
    )
    with_none = extractor.extract(
        segment=seg, gripper=np.zeros(30), eef_velocity=None,
        keyframes_per_segment=4,
        mask_cache=None, mask_alpha=0.4,
    )
    assert len(base.keyframes) == len(with_none.keyframes)
    for a, b in zip(base.keyframes, with_none.keyframes, strict=True):
        np.testing.assert_array_equal(a, b)


def test_extract_with_full_mask_paints_keyframes(tmp_path) -> None:
    """A mask covering the whole frame at alpha=1 → keyframe == palette color."""
    from mimicanno.clip_features import ClipFeatureExtractor
    from mimicanno.object_tracker.mask_cache import MaskCache, encode_mask
    from tests.fixtures.synthesize import synthesize_minimal_mp4

    video = synthesize_minimal_mp4(tmp_path, n_frames=30, width=64, height=48)
    seg = _make_segment_for_overlay()
    extractor = ClipFeatureExtractor(
        video_path=video, fps=30.0,
        clip_features_config=ClipFeatureConfig(),
        image_size_px=64,
    )
    # Frame size after long_edge_px=64 resize: H≤64, W≤64 (extract_frames_at_indices
    # returns up to long_edge_px on its longer side). Build the mask at the
    # actual frame shape we observe.
    base = extractor.extract(
        segment=seg, gripper=np.zeros(30), eef_velocity=None,
        keyframes_per_segment=4,
    )
    h, w = base.keyframes[0].shape[:2]
    from mimicanno.clip_features import compute_keyframe_offsets
    full_mask = np.ones((h, w), dtype=bool)
    offsets = compute_keyframe_offsets(
        seg.start_frame, seg.end_frame, 4,
    )
    by_frame = {fi: {"red block": encode_mask(full_mask)} for fi in offsets}
    cache = MaskCache(
        by_frame=by_frame, shape=(h, w),
        palette={"red block": (255, 0, 0)},
    )

    feat = extractor.extract(
        segment=seg, gripper=np.zeros(30), eef_velocity=None,
        keyframes_per_segment=4,
        mask_cache=cache, mask_alpha=1.0,
    )
    expected = np.zeros((h, w, 3), dtype=np.uint8)
    expected[..., 0] = 255  # red channel only
    for kf in feat.keyframes:
        assert kf.shape == (h, w, 3)
        # alpha=1.0 + full mask → every pixel becomes (255, 0, 0).
        np.testing.assert_array_equal(kf, expected)
