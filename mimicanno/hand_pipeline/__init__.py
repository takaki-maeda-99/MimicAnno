"""Hand pose estimation pipeline (MediaPipe HandLandmarker + UniDAC fusion).

Runtime notes:
  * The MediaPipe path (``estimate_hand`` with ``depth=None`` /
    ``_run_mediapipe``) runs cleanly inside MimicAnno's own ``.venv`` (uv).
  * The UniDAC depth path (``estimate_hand`` with a real depth array,
    ``_apply_metric_depth`` / ``_back_warp_depth`` / ``_sample_depth_at_pixels``)
    additionally needs ``torch`` and the ``unidac`` package on
    ``PYTHONPATH`` — run those tests under ``conda activate unidac``.

See ``tests/hand_pipeline/`` and ``scripts/precompute_depth.py`` for examples.
"""
from .pipeline import (
    HandEstimate,
    HandRaw,
    estimate_hand,
)

__all__ = ["HandEstimate", "HandRaw", "estimate_hand"]
