"""Hand pose estimation pipeline (HaMeR + UniDAC fusion).

NOTE: This subpackage requires a dedicated runtime environment — it does NOT
run inside MimicAnno's own ``.venv`` (uv).  Use one of:
  * HaMeR venv (``hamer/.hamer/bin/python``) with
    ``PYTHONPATH=/path/to/MimicAnno:/path/to/MimicAnno/UniDAC`` for
    ``estimate_hand`` and the HaMeR-dependent tests.
  * ``conda activate unidac`` for the UniDAC-dependent tests
    (warp, fuse, precompute_depth).
See ``tests/hand_pipeline/`` and ``scripts/precompute_depth.py`` for examples.
"""
from .pipeline import (
    HamerRaw,
    HandEstimate,
    estimate_hand,
)

__all__ = ["HamerRaw", "HandEstimate", "estimate_hand"]
