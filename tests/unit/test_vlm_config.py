"""Phase 2: VLMConfig and ClipFeatureConfig dataclasses (spec §2.4, §2.6)."""
from __future__ import annotations

import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    ClipFeatureConfig,
    MaskOverlayConfig,
    ModelConfig,
    VLMConfig,
    compute_config_hash,
)


def test_clip_feature_config_defaults() -> None:
    cfg = ClipFeatureConfig()
    assert cfg.gripper_open_threshold == pytest.approx(0.5)
    assert cfg.dwell_speed_threshold_mps == pytest.approx(0.01)


def test_vlm_config_defaults_and_required() -> None:
    cfg = VLMConfig(model_id="dummy-model", resolved_checkpoint="abc")
    assert cfg.keyframes_per_segment == 4
    assert cfg.image_size_px == 224
    assert cfg.max_retries == 3
    assert cfg.temperature == pytest.approx(0.0)
    assert cfg.timeout_sec == pytest.approx(30.0)
    assert cfg.runtime_failure_threshold == 3
    assert cfg.dtype == "bfloat16"
    assert cfg.clip_features.gripper_open_threshold == pytest.approx(0.5)


def test_vlm_config_to_dict_canonical_field_set() -> None:
    cfg = VLMConfig(model_id="m", resolved_checkpoint="c")
    d = cfg.to_dict()
    assert set(d) == {
        "clip_features", "device", "dtype", "image_size_px",
        "keyframe_strategy", "keyframes_per_segment", "mask_overlay",
        "max_output_tokens", "max_retries", "model_id", "resolved_checkpoint",
        "runtime_failure_threshold", "temperature", "timeout_sec",
    }


def test_mask_overlay_config_defaults() -> None:
    cfg = MaskOverlayConfig()
    assert cfg.enabled is True
    assert cfg.alpha == pytest.approx(0.4)
    assert cfg.palette == "builtin_10"
    assert cfg.to_dict() == {"alpha": 0.4, "enabled": True, "palette": "builtin_10"}


def test_vlm_config_includes_mask_overlay_in_to_dict() -> None:
    cfg = VLMConfig(model_id="m", resolved_checkpoint="c")
    d = cfg.to_dict()
    assert d["mask_overlay"] == {"alpha": 0.4, "enabled": True, "palette": "builtin_10"}


def test_mask_overlay_changes_config_hash() -> None:
    """enabled / alpha must each affect config_hash (ablation isolation)."""
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(
        vlm_model="m", vlm_checkpoint="abc",
        sam3_model=None, sam3_checkpoint=None,
    )
    base = VLMConfig(model_id="m", resolved_checkpoint="abc")
    no_overlay = VLMConfig(
        model_id="m", resolved_checkpoint="abc",
        mask_overlay=MaskOverlayConfig(enabled=False),
    )
    diff_alpha = VLMConfig(
        model_id="m", resolved_checkpoint="abc",
        mask_overlay=MaskOverlayConfig(alpha=0.6),
    )

    h_base = compute_config_hash(AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model, vlm=base,
    ))
    h_off = compute_config_hash(AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model, vlm=no_overlay,
    ))
    h_alpha = compute_config_hash(AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model, vlm=diff_alpha,
    ))
    assert h_base != h_off
    assert h_base != h_alpha
    assert h_off != h_alpha


def test_annotation_config_with_vlm_changes_hash() -> None:
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(vlm_model=None, vlm_checkpoint=None,
                        sam3_model=None, sam3_checkpoint=None)

    cfg_p1 = AnnotationConfig(
        boundary=boundary, target_phase=1, model_config=model, vlm=None
    )
    h_p1 = compute_config_hash(cfg_p1)

    vlm = VLMConfig(model_id="m1", resolved_checkpoint="abc")
    model_p2 = ModelConfig(
        vlm_model="m1", vlm_checkpoint="abc", sam3_model=None, sam3_checkpoint=None,
    )
    cfg_p2 = AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model_p2, vlm=vlm
    )
    h_p2 = compute_config_hash(cfg_p2)

    assert h_p1 != h_p2

    # Changing keyframes_per_segment also yields a different hash.
    vlm2 = VLMConfig(model_id="m1", resolved_checkpoint="abc",
                     keyframes_per_segment=6)
    cfg_p2b = AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model_p2, vlm=vlm2
    )
    assert compute_config_hash(cfg_p2b) != h_p2


def test_annotation_config_to_dict_omits_vlm_when_none() -> None:
    """Phase 1 manifest byte-equivalence (spec §2.6)."""
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(vlm_model=None, vlm_checkpoint=None,
                        sam3_model=None, sam3_checkpoint=None)
    cfg = AnnotationConfig(
        boundary=boundary, target_phase=1, model_config=model, vlm=None
    )
    d = cfg.to_dict()
    assert "vlm" not in d["annotation_config"]


def test_vlm_config_fixture_path_excluded_from_to_dict_and_hash() -> None:
    """fixture_path is runtime-only — same content at different paths must
    produce identical config_hash."""
    from pathlib import Path
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(vlm_model="fixture", vlm_checkpoint="abc",
                        sam3_model=None, sam3_checkpoint=None)

    a = VLMConfig(model_id="fixture", resolved_checkpoint="abc",
                  fixture_path=Path("/tmp/a.json"))
    b = VLMConfig(model_id="fixture", resolved_checkpoint="abc",
                  fixture_path=Path("/home/u/b.json"))
    assert "fixture_path" not in a.to_dict()
    assert a.to_dict() == b.to_dict()

    cfg_a = AnnotationConfig(boundary=boundary, target_phase=2,
                             model_config=model, vlm=a)
    cfg_b = AnnotationConfig(boundary=boundary, target_phase=2,
                             model_config=model, vlm=b)
    assert compute_config_hash(cfg_a) == compute_config_hash(cfg_b)
