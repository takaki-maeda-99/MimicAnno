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


def test_mediapipe_detection_rate_gx010085():
    """Model-regression gate: MediaPipe must detect at least one hand in 95%
    of the GX010085 detection-rate fixture frames.

    Fixture scope. The 25 fixture frames cover the stable working phase of
    GX010085 (frame indices 90..378, every 12 frames) where the hand is
    clearly visible. The empirical baseline on this fixture is 25/25 = 100%;
    the threshold is set at 95% (measured minus 5 percentage points) per the
    project's model-regression policy.

    What this test does NOT measure.

    - Content quality on real, full-length videos. The full-video detection
      rate on GX010085 is ~73% because (a) the intro frames 0..65 have no
      hand in view and (b) the work segment 1080..1199 contains heavy
      occlusion (hand wrapped around a held object) that MediaPipe handles
      poorly regardless of camera projection.
    - Fisheye-periphery robustness. Failures attributable to peripheral
      bbox positions are a small minority (~18% of failure frames in the
      full-run analysis); rectifying the fisheye projection would help only
      that minority and is deferred.

    Both above are content/architecture concerns, not model-regression
    concerns; mixing them into this gate would mask real MediaPipe
    regressions in the clear-visibility regime. Future work that needs an
    end-to-end content-quality metric should add a separate test.

    Detailed empirical backing (failure-mode breakdown, contact-sheet
    observations, decision logic) is recorded in the PR 3 description.
    """
    threshold = 0.95  # measured 100% on GX010085 working phase − 5pp margin

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


# ---------------------------------------------------------------------------
# Model-path resolution tests
# ---------------------------------------------------------------------------


def test_resolve_model_path_uses_env_var(tmp_path, monkeypatch):
    """When MIMICANNO_HAND_LANDMARKER_PATH points at an existing file,
    _resolve_model_path returns that path unchanged — no network, no cache."""
    from mimicanno.hand_pipeline.pipeline import _resolve_model_path

    fake = tmp_path / "fake_model.task"
    fake.write_bytes(b"dummy")
    monkeypatch.setenv("MIMICANNO_HAND_LANDMARKER_PATH", str(fake))

    assert _resolve_model_path() == fake


def test_resolve_model_path_env_var_missing_file_raises(tmp_path, monkeypatch):
    """When the env var is set but the file is missing, fail loudly rather
    than silently falling back to network download."""
    from mimicanno.hand_pipeline.pipeline import _resolve_model_path

    monkeypatch.setenv(
        "MIMICANNO_HAND_LANDMARKER_PATH", str(tmp_path / "nonexistent.task")
    )
    with pytest.raises(FileNotFoundError):
        _resolve_model_path()


def test_resolve_model_path_uses_cache_when_present(tmp_path, monkeypatch):
    """When the env var is not set and a properly-sized cached file exists at
    ~/.cache/mimicanno/hand_landmarker.task, _resolve_model_path returns it
    without re-downloading."""
    from mimicanno.hand_pipeline.pipeline import _resolve_model_path

    monkeypatch.delenv("MIMICANNO_HAND_LANDMARKER_PATH", raising=False)
    fake_cache = tmp_path / ".cache" / "mimicanno" / "hand_landmarker.task"
    fake_cache.parent.mkdir(parents=True)
    # Must satisfy the size check (5 MB minimum) so the cache path is used.
    fake_cache.write_bytes(b"\x00" * (6 * 1024 * 1024))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    assert _resolve_model_path() == fake_cache
