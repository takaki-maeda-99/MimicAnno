"""Shared pytest fixtures for mimicanno tests.

Side-effect: import ``torch`` at module load so that ``sys.modules['torch']``
is the *real* package before any test that does
``sys.modules.setdefault('torch', <fake>)`` runs (notably
``tests/unit/test_local_gemma_skeleton.py``). Without this, alphabetical
collection order causes that test to install a MagicMock under
``torch`` and poison every later test that legitimately needs torch
(e.g. anything that imports ``sam3.model_builder``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import torch  # noqa: F401  (intentional eager import)
except ImportError:  # pragma: no cover - torch is a hard dep in dev/test env
    pass

if TYPE_CHECKING:
    import numpy as np

    from mimicanno.object_tracker.propagator import BBox
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult


def make_test_propagation_result(
    frame: int,
    detections: "dict[str, tuple[BBox, float] | None]",
    masks: "dict[str, np.ndarray | None] | None" = None,
) -> "FramePropagationResult":
    """Construct a FramePropagationResult for tests with sensible defaults.

    Task 4: ``FramePropagationResult.masks`` became a required field with the
    invariant ``detections.keys() == masks.keys()``. Older tests that don't
    care about masks should use this helper — it fills in ``None`` for every
    prompt automatically. Tests that DO care about masks should pass the
    ``masks`` arg explicitly.
    """
    from mimicanno.object_tracker.sam3_runtime import FramePropagationResult

    if masks is None:
        masks = {prompt: None for prompt in detections}
    return FramePropagationResult(
        frame=frame, detections=detections, masks=masks,
    )
