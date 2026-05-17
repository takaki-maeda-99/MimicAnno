"""Tests for Propagator.run anchor_frame_index / propagation_direction (spec §5.4)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mimicanno.config import TrackingConfig
from mimicanno.object_tracker.fixtures import FixtureSAM3Tracker
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    Propagator,
    TrackingPlan,
)


def _plan() -> TrackingPlan:
    return TrackingPlan(
        entities=EntityPlan(
            object_prompts=["tape"], target_prompts=[], tool_prompts=[],
        ),
        initial_detections={("object", "tape"): BBox(0.1, 0.1, 0.2, 0.2)},
        failed_prompts=[],
    )


def test_propagator_run_default_anchor_is_zero_forward() -> None:
    fx = FixtureSAM3Tracker(
        propagation_results={
            0: {"tape": (BBox(0.1, 0.1, 0.2, 0.2), 0.9)},
            5: {"tape": (BBox(0.1, 0.1, 0.2, 0.2), 0.9)},
        },
    )
    propagator = Propagator()
    cfg = TrackingConfig(sam3_checkpoint=None)
    tracks, _ = propagator.run(
        runtime=fx, plan=_plan(), video_path=Path("/dev/null"),
        fps=10.0, n_frames=10, stride=5, config=cfg,
    )
    assert fx.last_anchor_frame_index == 0
    assert fx.last_propagation_direction == "forward"
    assert len(tracks) >= 1


def test_propagator_run_forwards_anchor_and_direction() -> None:
    fx = FixtureSAM3Tracker(
        propagation_results={
            5: {"tape": (BBox(0.1, 0.1, 0.2, 0.2), 0.9)},
            9: {"tape": (BBox(0.1, 0.1, 0.2, 0.2), 0.9)},
        },
    )
    propagator = Propagator()
    cfg = TrackingConfig(sam3_checkpoint=None)
    propagator.run(
        runtime=fx, plan=_plan(), video_path=Path("/dev/null"),
        fps=10.0, n_frames=10, stride=5, config=cfg,
        anchor_frame_index=5,
        propagation_direction="both",
    )
    assert fx.last_anchor_frame_index == 5
    assert fx.last_propagation_direction == "both"
