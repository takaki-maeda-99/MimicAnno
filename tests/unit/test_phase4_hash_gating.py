"""Phase 4 hash-gating regression (spec §6).

The presence of SmootherConfig MUST NOT alter config_hash for
target_phase < 4. This test pins Phase 1/2/3 config hashes for a
deterministic fixture; if Phase 4 code changes them, every existing
runs/<canonical_name>/ directory becomes invalid.

Pinned hashes captured against baseline (pre-AnnotationConfig.smoother
field-add) on 2026-04-29.
"""
from __future__ import annotations

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    SmootherConfig,
    TrackingConfig,
    VLMConfig,
    build_model_config,
    compute_config_hash,
)


# Pinned baselines — DO NOT EDIT without auditing config_hash inputs.
# Captured: Phase 1 BoundaryConfig.with_defaults() + no vlm + no tracking;
#           Phase 2 adds VLMConfig(model_id="google/gemma-4-E2B-it",
#                                  resolved_checkpoint="sha256:cafe123");
#           Phase 3 adds TrackingConfig() + sam3_checkpoint_sha256="sha256:beef456".
# Phase 3 baseline rotated 2026-05-04 when TrackingConfig.sam3_offload (default
# True) joined to_dict() — see plan Task 3 + spec §4.4. Phase 1/2 baselines
# unchanged because TrackingConfig is gated out under target_phase < 3.
PINNED_PHASE1_HASH = (
    "sha256:f6de5eb8209e1d4d902370c4fe63ebfb7cb32284d2f8528ec44f20c8e387b115"
)
# Phase 2/3 hashes bumped 2026-05-06 with the introduction of
# `VLMConfig.mask_overlay` (spec 2026-05-04-vlm-mask-overlay-design §7.2).
PINNED_PHASE2_HASH = (
    "sha256:6acaaa0420e80822752dbea05b5993f668e3c60de9ec53f1861343b6dc9be182"
)
# Phase 3 hash bumped 2026-05-17: TrackingConfig.grounding_retry_fractions added
# to to_dict() (spec §5.2 / feat+sam3-grounding-retry T1).
PINNED_PHASE3_HASH = (
    "sha256:387434f893fb17e27f0caac7ace5db8ed6fb84babec771a39045f885a5b43932"
)


def _cfg(target_phase: int, *, with_vlm: bool = False,
         with_tracking: bool = False,
         smoother: SmootherConfig | None = None) -> AnnotationConfig:
    vlm = (
        VLMConfig(model_id="google/gemma-4-E2B-it",
                  resolved_checkpoint="sha256:cafe123")
        if with_vlm else None
    )
    tracking = TrackingConfig() if with_tracking else None
    kwargs = dict(
        boundary=BoundaryConfig.with_defaults(),
        target_phase=target_phase,
        model_config=build_model_config(
            target_phase=target_phase, vlm=vlm, tracking=tracking,
            sam3_checkpoint_sha256=(
                "sha256:beef456" if with_tracking else None
            ),
        ),
        vlm=vlm,
        tracking=tracking,
    )
    if smoother is not None:
        kwargs["smoother"] = smoother
    return AnnotationConfig(**kwargs)  # type: ignore[arg-type]


def test_phase1_hash_unchanged_after_smoother_field_added() -> None:
    cfg = _cfg(1)
    h = compute_config_hash(cfg)
    assert h == PINNED_PHASE1_HASH, (
        f"Phase 1 config_hash drifted: {h} != {PINNED_PHASE1_HASH}. "
        "Phase 4 code must NOT enter the Phase 1 hash payload."
    )
    assert "smoother" not in cfg.to_dict()["annotation_config"]


def test_phase2_hash_unchanged_after_smoother_field_added() -> None:
    cfg = _cfg(2, with_vlm=True)
    h = compute_config_hash(cfg)
    assert h == PINNED_PHASE2_HASH, (
        f"Phase 2 config_hash drifted: {h} != {PINNED_PHASE2_HASH}."
    )
    assert "smoother" not in cfg.to_dict()["annotation_config"]


def test_phase3_hash_unchanged_after_smoother_field_added() -> None:
    cfg = _cfg(3, with_vlm=True, with_tracking=True)
    h = compute_config_hash(cfg)
    assert h == PINNED_PHASE3_HASH, (
        f"Phase 3 config_hash drifted: {h} != {PINNED_PHASE3_HASH}."
    )
    assert "smoother" not in cfg.to_dict()["annotation_config"]


def test_phase4_hash_includes_smoother() -> None:
    cfg = _cfg(4, with_vlm=True, with_tracking=True, smoother=SmootherConfig())
    payload = cfg.to_dict()
    assert "smoother" in payload["annotation_config"]
    assert payload["annotation_config"]["smoother"] == SmootherConfig().to_dict()


def test_phase4_smoother_change_changes_hash() -> None:
    a = _cfg(4, with_vlm=True, with_tracking=True, smoother=SmootherConfig())
    b = _cfg(4, with_vlm=True, with_tracking=True,
             smoother=SmootherConfig(viterbi_enabled=False))
    assert compute_config_hash(a) != compute_config_hash(b)


def test_phase4_lambda_change_changes_hash() -> None:
    a = _cfg(4, with_vlm=True, with_tracking=True, smoother=SmootherConfig())
    b = _cfg(4, with_vlm=True, with_tracking=True,
             smoother=SmootherConfig(lambda_forbidden=2.0))
    assert compute_config_hash(a) != compute_config_hash(b)
