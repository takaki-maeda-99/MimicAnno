"""Shared monkeypatch helpers for Phase 3 integration tests.

Phase 3's orchestrator (`annotate_episode_phase3`) hard-wires
`LocalGemmaVLMLabeler`, `LocalGemmaTrackingPlanner`, and `SAM3Runtime`. To
exercise the orchestrator end-to-end without GPU / model weights, the
integration tests substitute these symbols at module scope with the
test doubles in `mimicanno.object_tracker.fixtures` plus a small
`FixtureVLMLabeler` adapter that exposes `shared_handle()`.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from mimicanno.config import VLMConfig
from mimicanno.object_tracker.fixtures import (
    FixtureSAM3Tracker,
    FixtureTrackingPlanner,
)
from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import BBox
from mimicanno.vlm_labeler import FixtureVLMLabeler, GemmaHandle


__all__ = [
    "BBox",
    "EntityPlan",
    "FIXTURE_VLM_OK_FIRST_TRY",
    "FixtureSAM3Tracker",
    "FixtureTrackingPlanner",
    "FrameDetections",
    "build_full_propagation",
    "patch_phase3",
]


FIXTURE_VLM_OK_FIRST_TRY = (
    Path(__file__).resolve().parent.parent / "fixtures" / "vlm" / "ok_first_try.json"
)


# Default propagation frames for synthesize_aloha_episode (n_frames=120, fps=30).
# stride = max(1, round(30 / 3)) = 10 -> [0,10,20,...,110,119].
_DEFAULT_PROP_FRAMES: tuple[int, ...] = (
    0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 119,
)


FrameDetections = dict[int, dict[str, tuple[BBox, float] | None]]


class _FixtureVLMWithHandle(FixtureVLMLabeler):
    """`FixtureVLMLabeler` + `shared_handle()` so it can stand in for
    `LocalGemmaVLMLabeler` in Phase 3.

    Phase 3's orchestrator constructs the VLM at line 775 with
    `vlm = LocalGemmaVLMLabeler(vlm_cfg)` and then calls
    `vlm.shared_handle()` to feed `LocalGemmaTrackingPlanner`. The
    real `GemmaHandle.model` is the loaded torch module; tests don't use
    its identity so we hand back a stub handle whose `.config` is the
    `VLMConfig` and whose `.model`/`.processor` are `None`.
    """

    def __init__(self, vlm_config: VLMConfig) -> None:
        if vlm_config.fixture_path is None:
            raise ValueError(
                "_FixtureVLMWithHandle requires VLMConfig.fixture_path; "
                "tests must use --vlm-model fixture://<path>"
            )
        super().__init__(vlm_config.fixture_path)
        self._vlm_config = vlm_config

    def shared_handle(self) -> GemmaHandle:
        return GemmaHandle(model=None, processor=None, config=self._vlm_config)


def build_full_propagation(
    *,
    prompts: list[str],
    bbox: BBox = BBox(x=0.4, y=0.4, w=0.1, h=0.1),
    score: float = 0.9,
    frames: tuple[int, ...] = _DEFAULT_PROP_FRAMES,
) -> FrameDetections:
    """Construct propagation results yielding `(bbox, score)` for every prompt
    on every frame in *frames*. Default frames cover the synthesize_aloha_episode
    happy-path (n_frames=120 @ 30fps, stride=10)."""
    return {f: {p: (bbox, score) for p in prompts} for f in frames}


@contextmanager
def patch_phase3(
    *,
    entities: EntityPlan,
    sam3_tracker: FixtureSAM3Tracker | None = None,
    raise_on_planner: Exception | None = None,
) -> Iterator[FixtureSAM3Tracker]:
    """Patch the three Phase 3 ML symbols + the SAM3 import check.

    ``sam3_tracker`` is constructed by callers when they want to inject
    custom detections / failure modes; otherwise an empty tracker is created
    so the orchestrator hits the `sam3_no_initial_detection` degrade path.
    """
    tracker = sam3_tracker or FixtureSAM3Tracker()
    fixture_planner = FixtureTrackingPlanner(
        entities=entities,
        raise_on_extract=raise_on_planner,
    )

    def _planner_factory(_handle: Any) -> FixtureTrackingPlanner:
        return fixture_planner

    class _Sam3Stub:
        @classmethod
        def load(cls, *, checkpoint: object = None, device: object = "cpu") -> Any:
            return tracker.load(checkpoint=checkpoint, device=device)

    with ExitStack() as stack:
        stack.enter_context(mock.patch(
            "mimicanno.object_tracker.sam3_runtime._ensure_transformers_sam3_importable",
            return_value=None,
        ))
        stack.enter_context(mock.patch(
            "mimicanno.pipeline.LocalGemmaVLMLabeler",
            _FixtureVLMWithHandle,
        ))
        stack.enter_context(mock.patch(
            "mimicanno.pipeline.LocalGemmaTrackingPlanner",
            _planner_factory,
        ))
        stack.enter_context(mock.patch(
            "mimicanno.pipeline.SAM3Runtime",
            _Sam3Stub,
        ))
        yield tracker
