"""Shared test fixtures for the hand_pipeline test suite.

Path constants live here so they can be overridden in CI or local setups
without touching individual test files.

GPU policy: MediaPipe is forced to CPU delegate for the entire pytest
session by default. The pipeline uses GPU delegate at runtime, but
``CUDA_VISIBLE_DEVICES`` does not propagate to MediaPipe's EGL/GL device
selection, so a test that triggers MediaPipe init can land on whichever
GPU has free OpenGL context — a real hazard on shared multi-tenant
hosts. Tests that need to verify GPU-delegate behaviour explicitly
override the env var via ``monkeypatch``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Force CPU delegate before any test imports MediaPipe. ``setdefault``
# preserves an explicit GPU override from the caller's shell.
os.environ.setdefault("MIMICANNO_MEDIAPIPE_DELEGATE", "CPU")


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


@pytest.fixture(scope="session", autouse=True)
def _mediapipe_hand_model_prewarm():
    """Resolve the MediaPipe HandLandmarker model once per session.

    Runs before any test in tests/hand_pipeline/. Respects the
    ``MIMICANNO_HAND_LANDMARKER_PATH`` env var override; otherwise hits the
    network only if the user-level cache is empty.
    """
    from mimicanno.hand_pipeline.pipeline import _resolve_model_path

    _resolve_model_path()


def _safe_close_landmarker() -> None:
    """Close the cached HandLandmarker via its explicit ``close()`` method
    if available, then null the singleton.

    Relying on ``__del__`` to clean up the landmarker has been observed to
    hang on session teardown (MediaPipe internal threads / GL contexts).
    Calling ``close()`` explicitly avoids the hang.
    """
    from mimicanno.hand_pipeline import pipeline as _pipeline

    lm = _pipeline._MP_LANDMARKER
    if lm is not None:
        close = getattr(lm, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    _pipeline._MP_LANDMARKER = None


@pytest.fixture(autouse=True)
def _reset_mediapipe_landmarker_per_test():
    """Null the cached HandLandmarker before and after each test.

    The pipeline runs MediaPipe in VIDEO mode, which rejects out-of-order
    timestamps on the same detector instance. Nulling the singleton
    between tests means each test starts with a fresh detector whose
    timestamp history is empty, so test cases can independently use any
    non-negative monotonic timestamp sequence without coupling.

    Explicit ``close()`` (via :func:`_safe_close_landmarker`) is required:
    relying on ``__del__`` causes the test session to hang on the next
    test boundary because MediaPipe's destructor blocks on internal
    cleanup. The session-scoped ``_mediapipe_hand_model_prewarm`` above
    ensures the model file is already on disk, so recreation is
    network-free.
    """
    _safe_close_landmarker()
    yield
    _safe_close_landmarker()
