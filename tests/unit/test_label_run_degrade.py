"""label_run — run-level degrade triggers (spec §4.3)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelerRuntimeError,
    VLMLabeler,
    VLMRequest,
    VLMResponse,
    label_run,
    ModelIdentity,
)
from tests.unit.helpers_phase1 import make_synthetic_phase1_run


FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _vlm_config(rt_thresh: int = 3) -> VLMConfig:
    return VLMConfig(model_id="fixture", resolved_checkpoint="x",
                     runtime_failure_threshold=rt_thresh, max_retries=3)


# ---- vlm_init_failed ------------------------------------------------------

def test_init_should_raise_returns_baseline_and_degrade() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=3)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "init_should_raise.json")
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "degraded"
    assert outcome.degrade_reason == "vlm_init_failed"
    assert outcome.underlying_error is not None
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)
    assert attempts == []


# ---- vlm_unreachable (first-call fail-fast) ------------------------------

class _FirstCallUnreachable:
    def label_segment(self, request, attempt, last_reject_reason=None):
        raise LabelerRuntimeError("model_unreachable")
    def model_identity(self):
        return ModelIdentity(vlm_model="fake", vlm_checkpoint="x")


def test_first_call_unreachable_short_circuits() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=5)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=lambda c: _FirstCallUnreachable(),
    )
    assert outcome.degrade_reason == "vlm_unreachable"
    assert len(attempts) == 1
    assert attempts[0].runtime_errors == ["model_unreachable"]
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)


# ---- vlm_runtime_failed (consecutive threshold) --------------------------

def test_consecutive_runtime_failures_trigger_degrade() -> None:
    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=5)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config(rt_thresh=3)
    factory = lambda c: FixtureVLMLabeler(FIXT / "runtime_oom.json")
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=factory,
    )
    assert outcome.degrade_reason == "vlm_runtime_failed"
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)


def test_runtime_failures_reset_on_success() -> None:
    """A successful call between two flaky ones resets the consecutive counter."""
    class _FlakyThenOK:
        def __init__(self) -> None:
            self.calls = 0
        def label_segment(self, request, attempt, last_reject_reason=None):
            self.calls += 1
            if self.calls in (1, 2, 4):
                raise LabelerRuntimeError("cuda_oom")
            return VLMResponse(phase="idle", verb=None, object=None,
                               target=None, vlm_confidence=0.5, evidence=None)
        def model_identity(self):
            return ModelIdentity(vlm_model="x", vlm_checkpoint="y")

    segs, gripper, eef, extractor, meta = make_synthetic_phase1_run(n_segments=3)
    cfg = _vlm_config(rt_thresh=3)
    labeled, attempts, outcome = label_run(
        segments=segs, extractor=extractor, gripper=gripper, eef_velocity=eef,
        episode_meta=meta, config=cfg, labeler_factory=lambda c: _FlakyThenOK(),
    )
    assert outcome.kind == "ok", "non-consecutive faults must NOT degrade"
    assert all(s.phase == "idle" for s in labeled)
