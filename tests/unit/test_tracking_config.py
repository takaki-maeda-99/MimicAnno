"""TrackingConfig validation and serialization (spec §7.4)."""

from __future__ import annotations

import json

import pytest

from mimicanno.config import TrackingConfig, canonical_json


def test_defaults_match_spec_section_7_4() -> None:
    cfg = TrackingConfig()
    assert cfg.sam3_model_id == "facebook/sam3"
    assert cfg.min_track_score == 0.30
    assert cfg.reacquisition_iou_threshold == 0.30
    assert cfg.visibility_threshold == 0.5
    assert cfg.gripper_object_distance_threshold == 0.05
    assert cfg.object_motion_threshold == 0.02
    assert cfg.object_motion_min_sec == 0.10
    assert cfg.image_aspect_ratio_default == pytest.approx(16.0 / 9.0)
    assert cfg.planner_max_retries == 3
    assert cfg.track_stride_frames is None
    assert cfg.max_gap_frames is None


def test_effective_stride_default_at_30fps_is_10() -> None:
    """30 / 3 = 10 (spec §7.4 effective_stride formula)."""
    cfg = TrackingConfig()
    assert cfg.effective_stride(30.0) == 10
    assert cfg.effective_stride(60.0) == 20
    assert cfg.effective_stride(15.0) == 5


def test_effective_stride_explicit_override_wins() -> None:
    cfg = TrackingConfig(track_stride_frames=4)
    assert cfg.effective_stride(30.0) == 4


def test_effective_stride_low_fps_clamped_to_one() -> None:
    """fps below 3 would round to 0; spec §7.4 says max(1, ...)."""
    cfg = TrackingConfig()
    assert cfg.effective_stride(2.0) == 1
    assert cfg.effective_stride(1.0) == 1


def test_effective_max_gap_frames_default_one_second() -> None:
    cfg = TrackingConfig()
    assert cfg.effective_max_gap_frames(30.0) == 30
    assert cfg.effective_max_gap_frames(60.0) == 60


def test_effective_max_gap_frames_explicit_override() -> None:
    cfg = TrackingConfig(max_gap_frames=42)
    assert cfg.effective_max_gap_frames(30.0) == 42


def test_to_dict_excludes_sam3_checkpoint() -> None:
    """spec §9.1: sam3_checkpoint is excluded from TrackingConfig.to_dict;
    authoritative location is model_config.sam3_checkpoint (sha256)."""
    cfg = TrackingConfig(sam3_checkpoint="/path/to/sam3.ckpt")
    payload = cfg.to_dict()
    assert "sam3_checkpoint" not in payload
    assert payload["sam3_model_id"] == "facebook/sam3"


def test_to_dict_serialization_round_trip_via_canonical_json() -> None:
    """Canonicalisation MUST be byte-stable (spec §9.2)."""
    cfg = TrackingConfig(
        sam3_model_id="facebook/sam3",
        sam3_checkpoint="/abs/path",
        track_stride_frames=10,
        min_track_score=0.25,
    )
    blob = canonical_json(cfg.to_dict())
    parsed = json.loads(blob)
    assert parsed["sam3_model_id"] == "facebook/sam3"
    assert parsed["track_stride_frames"] == 10
    assert parsed["min_track_score"] == 0.25
    # Repeat — same bytes
    assert canonical_json(cfg.to_dict()) == blob


def test_frozen_dataclass() -> None:
    """TrackingConfig is frozen — accidental mutation would break hash
    determinism."""
    cfg = TrackingConfig()
    with pytest.raises((AttributeError, TypeError)):
        cfg.sam3_model_id = "modified"  # type: ignore[misc]
