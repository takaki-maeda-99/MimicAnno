"""Phase 1/2 config_hash byte-identity invariant under Phase 3 schema additions
(spec §9.1, §9.3). If this test ever fails, every existing Phase 1/2
canonical_name on disk is invalidated."""

from __future__ import annotations

import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    BoundaryWeights,
    ModelConfig,
    TrackingConfig,
    VLMConfig,
    compute_config_hash,
)

# NB: Phase 2 hash bumped 2026-05-06 with the introduction of
# `VLMConfig.mask_overlay` (spec 2026-05-04-vlm-mask-overlay-design §7.2 —
# overlay settings are intentionally part of config_hash so ablations land
# in distinct run dirs). Phase 1 unaffected because vlm is None.
PHASE1_HASH_PRE_MERGE = "sha256:f6de5eb8209e1d4d902370c4fe63ebfb7cb32284d2f8528ec44f20c8e387b115"
PHASE2_HASH_PRE_MERGE = "sha256:bf9f46391f4bbdd2d1288f3ccd9176d2f00dc99bc7683b006661c778f4e6792a"


def _phase1_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(),
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
        vlm=None,
    )


def _phase2_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(),
        target_phase=2,
        model_config=ModelConfig("google/gemma-4-E2B-it", "sha256:abc", None, None),
        vlm=VLMConfig(model_id="google/gemma-4-E2B-it", resolved_checkpoint="sha256:abc"),
    )


def _phase3_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(weights=BoundaryWeights.phase3_defaults()),
        target_phase=3,
        model_config=ModelConfig(
            "google/gemma-4-E2B-it", "sha256:abc",
            "facebook/sam3", "sha256:def",
        ),
        vlm=VLMConfig(model_id="google/gemma-4-E2B-it", resolved_checkpoint="sha256:abc"),
        tracking=TrackingConfig(
            sam3_model_id="facebook/sam3",
            sam3_checkpoint="/path/to/sam3.ckpt",
        ),
    )


def test_phase1_hash_unchanged() -> None:
    assert compute_config_hash(_phase1_config()) == PHASE1_HASH_PRE_MERGE


def test_phase2_hash_unchanged() -> None:
    assert compute_config_hash(_phase2_config()) == PHASE2_HASH_PRE_MERGE


def test_phase1_payload_omits_tracking_key() -> None:
    payload = _phase1_config().to_dict()
    assert "tracking" not in payload["annotation_config"]


def test_phase2_payload_omits_tracking_key() -> None:
    payload = _phase2_config().to_dict()
    assert "tracking" not in payload["annotation_config"]


def test_phase1_payload_includes_sam3_model_keys_as_null() -> None:
    payload = _phase1_config().to_dict()
    assert payload["model_config"]["sam3_model"] is None
    assert payload["model_config"]["sam3_checkpoint"] is None


def test_phase1_boundary_weights_omit_phase3_keys() -> None:
    payload = _phase1_config().to_dict()
    weights = payload["annotation_config"]["boundary"]["weights"]
    assert "gripper_object_distance_threshold_crossing" not in weights
    assert "object_motion_start_stop" not in weights


def test_phase3_payload_includes_tracking_key() -> None:
    payload = _phase3_config().to_dict()
    assert "tracking" in payload["annotation_config"]
    assert payload["annotation_config"]["tracking"]["sam3_model_id"] == "facebook/sam3"


def test_phase3_payload_excludes_sam3_path_in_tracking() -> None:
    payload = _phase3_config().to_dict()
    assert "sam3_checkpoint" not in payload["annotation_config"]["tracking"]


def test_phase3_payload_includes_phase3_boundary_keys() -> None:
    payload = _phase3_config().to_dict()
    weights = payload["annotation_config"]["boundary"]["weights"]
    assert weights["gripper_object_distance_threshold_crossing"] == pytest.approx(0.25)
    assert weights["object_motion_start_stop"] == pytest.approx(0.10)
    assert weights["gripper"] == pytest.approx(0.45)


def test_phase3_hash_distinct_from_phase2() -> None:
    assert compute_config_hash(_phase3_config()) != compute_config_hash(_phase2_config())
