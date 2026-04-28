"""apply_phase2_labeling — notes aggregation + degrade messaging."""
from __future__ import annotations

from pathlib import Path

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import FixtureVLMLabeler
from tests.unit.helpers_phase1 import make_synthetic_phase1_run

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _vlm_config() -> VLMConfig:
    return VLMConfig(
        model_id="fixture", resolved_checkpoint="abc",
        keyframes_per_segment=4, max_retries=3,
    )


def test_apply_phase2_labeling_aggregates_notes() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=2)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    from mimicanno.pipeline import apply_phase2_labeling
    _, outcome, notes = apply_phase2_labeling(
        segments=segs, extractor=extractor,
        gripper=gripper, eef_velocity=eef, episode_meta=meta,
        vlm_config=cfg, labeler_factory_override=factory,
    )
    assert outcome.kind == "ok"
    assert notes is not None
    assert "2/2 segments labeled" in notes


def test_apply_phase2_labeling_degrade_path_in_notes() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=3)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "init_should_raise.json")
    from mimicanno.pipeline import apply_phase2_labeling
    _, outcome, notes = apply_phase2_labeling(
        segments=segs, extractor=extractor,
        gripper=gripper, eef_velocity=eef, episode_meta=meta,
        vlm_config=cfg, labeler_factory_override=factory,
    )
    assert outcome.kind == "degraded"
    assert outcome.degrade_reason == "vlm_init_failed"
    assert notes is not None
    assert "degraded to Phase 1" in notes
