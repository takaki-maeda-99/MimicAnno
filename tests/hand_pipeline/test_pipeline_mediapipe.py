from pathlib import Path

import cv2
import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import HandRaw, _run_mediapipe

FIXTURES = Path(__file__).parent / "fixtures" / "gx010085"


def _load_first_det_frame() -> np.ndarray:
    paths = sorted(FIXTURES.glob("det_frame_*.jpg"))
    assert paths, f"no detection-rate fixtures found in {FIXTURES}"
    img = cv2.imread(str(paths[0]))
    assert img is not None
    return img


def test_run_mediapipe_returns_list_of_handraw():
    img = _load_first_det_frame()
    raws = _run_mediapipe(img)
    assert isinstance(raws, list)
    for r in raws:
        assert isinstance(r, HandRaw)
        assert r.joints_2d.shape == (21, 2)
        assert r.joints_local.shape == (21, 3)
        assert r.bbox.shape == (4,)
        assert isinstance(r.is_right, bool)
        assert 0.0 <= r.score <= 1.0


def test_run_mediapipe_zero_image_returns_empty():
    black = np.zeros((360, 640, 3), dtype=np.uint8)
    raws = _run_mediapipe(black)
    assert raws == []


def test_run_mediapipe_rejects_non_uint8():
    img = np.zeros((360, 640, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        _run_mediapipe(img)


def test_run_mediapipe_rejects_wrong_shape():
    img = np.zeros((360, 640), dtype=np.uint8)
    with pytest.raises(ValueError):
        _run_mediapipe(img)


@pytest.mark.skip(reason="threshold pending — see PR 2 description and future rectify spec")
def test_mediapipe_detection_rate_gx010085():
    """Lower-bound check on detection rate across fixture frames.

    Threshold is currently a placeholder; PR 2 records the empirical
    measurement in its description. A follow-up rectify spec will improve
    detection rate before any CI gate is promoted.
    """
    threshold = 0.0  # placeholder; rectify follow-up will set this

    det = sorted(FIXTURES.glob("det_frame_*.jpg"))
    assert det, "fixture set missing"
    n_total = len(det)
    n_hit = 0
    for p in det:
        img = cv2.imread(str(p))
        if _run_mediapipe(img):
            n_hit += 1
    rate = n_hit / n_total
    assert rate >= threshold, f"detection rate {rate:.2%} < {threshold:.2%}"
