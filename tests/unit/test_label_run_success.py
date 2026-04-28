"""label_run — happy path, per-segment retry, segment-level fallback.
Run-level degrade triggers (vlm_init_failed / vlm_unreachable / vlm_runtime_failed)
are tested separately in test_label_run_degrade.py (spec §4.3)."""
from __future__ import annotations

import copy
from pathlib import Path

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    label_run,
)
from tests.unit.helpers_phase1 import make_synthetic_phase1_run

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _vlm_config(model_id: str = "fixture") -> VLMConfig:
    return VLMConfig(
        model_id=model_id, resolved_checkpoint="abc",
        keyframes_per_segment=4, max_retries=3,
    )


def test_happy_path_all_segments_labeled() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=4)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor,
        gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "ok"
    assert outcome.degrade_reason is None
    assert all(s.phase == "approach_object" for s in labeled)
    assert all(s.label_source == "vlm_robot_state_only" for s in labeled)
    assert all(a.final_status == "ok" for a in attempts)
    assert all(a.attempt_count == 1 for a in attempts)


def test_retry_then_success() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=2)
    segs[1].segment_id = "s_001"
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "retry_then_ok.json")
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "ok"
    a1 = next(a for a in attempts if a.segment_id == "s_001")
    assert a1.attempt_count == 3
    assert a1.reject_reasons == ["json_parse_error", "invalid_label"]
    assert labeled[1].phase == "grasp_object"


def test_segment_level_fallback_to_unknown() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=3)
    segs[1].segment_id = "s_002"
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "fallback_unknown.json")
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "ok", "segment fallback must NOT trigger run-level degrade"
    a = next(a for a in attempts if a.segment_id == "s_002")
    assert a.final_status == "unknown_fallback"
    assert a.attempt_count == 3
    assert all(r == "json_parse_error" for r in a.reject_reasons)
    seg = next(s for s in labeled if s.segment_id == "s_002")
    assert seg.phase == "unknown"
    assert seg.vlm_confidence == 0.0
    assert seg.label_source == "vlm_robot_state_only"  # spec §4.4 invariant
    assert seg.overall_confidence == 0.0


def test_baseline_isolation_phase_does_not_leak_back() -> None:
    """Mutations on the working copy MUST NOT alter the caller's segments."""
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=2)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    for before, after in zip(snapshot, segs):
        assert before.phase == after.phase
        assert before.label_source == after.label_source
