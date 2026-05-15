"""Shared test fixtures for the hand_pipeline test suite.

Path constants live here so they can be overridden in CI or local setups
without touching individual test files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Project root: MimicAnno/ (two levels up from tests/hand_pipeline/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Ensure package root and scripts/ are importable.
sys.path.insert(0, str(PROJECT_ROOT))

# Reference fisheye test asset: a GoPro Hero 11 Max Lens clip where two hands
# are visible near the centre throughout (handwriting demo for imitation
# learning). 1042 frames, 2704x1520, 29.97 fps.
TEST_VIDEO_WITH_HANDS = PROJECT_ROOT / "data" / "video" / "GX010013.MP4"
TWO_HANDS_CENTRAL_IMAGE = PROJECT_ROOT / "tests" / "hand_pipeline" / "fixtures" / "two_hands_central.jpg"


@pytest.fixture(scope="session")
def test_video_with_hands() -> Path:
    """Path to a fisheye video with two hands in view (GX010013)."""
    if not TEST_VIDEO_WITH_HANDS.exists():
        pytest.skip(f"test video missing: {TEST_VIDEO_WITH_HANDS}")
    return TEST_VIDEO_WITH_HANDS


@pytest.fixture(scope="session")
def two_hands_central_image():
    """Frame 0 of GX010013 as a BGR uint8 ndarray (shape 1520x2704x3)."""
    import cv2
    if not TWO_HANDS_CENTRAL_IMAGE.exists():
        pytest.skip(f"fixture missing: {TWO_HANDS_CENTRAL_IMAGE}")
    img = cv2.imread(str(TWO_HANDS_CENTRAL_IMAGE))
    assert img is not None, f"cv2 could not read {TWO_HANDS_CENTRAL_IMAGE}"
    return img
