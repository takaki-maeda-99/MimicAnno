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
    raws = _run_mediapipe(img, timestamp_ms=0)
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
    raws = _run_mediapipe(black, timestamp_ms=0)
    assert raws == []


def test_run_mediapipe_rejects_non_uint8():
    img = np.zeros((360, 640, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        _run_mediapipe(img, timestamp_ms=0)


def test_run_mediapipe_rejects_wrong_shape():
    img = np.zeros((360, 640), dtype=np.uint8)
    with pytest.raises(ValueError):
        _run_mediapipe(img, timestamp_ms=0)


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
    # VIDEO mode requires monotonically-increasing timestamps; the fixture
    # filenames already encode frame indices, so derive ms from those.
    for idx, p in enumerate(det):
        img = cv2.imread(str(p))
        if _run_mediapipe(img, timestamp_ms=idx * 100):
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


# ---------------------------------------------------------------------------
# Delegate (GPU / CPU) resolution
# ---------------------------------------------------------------------------


def test_resolve_delegate_defaults_to_gpu(monkeypatch):
    """Unset env var → GPU delegate (the production default)."""
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from mimicanno.hand_pipeline.pipeline import _resolve_delegate

    monkeypatch.delenv("MIMICANNO_MEDIAPIPE_DELEGATE", raising=False)
    assert _resolve_delegate() == BaseOptions.Delegate.GPU


def test_resolve_delegate_cpu_override(monkeypatch):
    """MIMICANNO_MEDIAPIPE_DELEGATE=CPU → CPU delegate (OpenGL-less hosts)."""
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from mimicanno.hand_pipeline.pipeline import _resolve_delegate

    monkeypatch.setenv("MIMICANNO_MEDIAPIPE_DELEGATE", "CPU")
    assert _resolve_delegate() == BaseOptions.Delegate.CPU


def test_resolve_delegate_case_insensitive(monkeypatch):
    """Case-insensitive comparison so the operator can write 'cpu' or 'Cpu'."""
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from mimicanno.hand_pipeline.pipeline import _resolve_delegate

    monkeypatch.setenv("MIMICANNO_MEDIAPIPE_DELEGATE", "cpu")
    assert _resolve_delegate() == BaseOptions.Delegate.CPU


def test_resolve_delegate_unknown_value_falls_through_to_gpu(monkeypatch):
    """Unknown / typo'd values do not abort the run — they fall back to GPU.

    Rationale: the env var is a debug knob; treating an unknown value as
    an error would be more surprising than silently using the default.
    The valid set ({GPU, CPU}) is documented in the function docstring.
    """
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from mimicanno.hand_pipeline.pipeline import _resolve_delegate

    monkeypatch.setenv("MIMICANNO_MEDIAPIPE_DELEGATE", "TPU")  # not supported
    assert _resolve_delegate() == BaseOptions.Delegate.GPU


# ---------------------------------------------------------------------------
# VIDEO mode timestamp behaviour
# ---------------------------------------------------------------------------


def test_run_mediapipe_video_mode_rejects_non_monotonic_timestamp():
    """MediaPipe VIDEO mode rejects out-of-order timestamps on the same
    detector. The runner is responsible for monotonic timestamps; this
    test documents the underlying constraint so anyone modifying the
    Pass-1 loop knows what they have to preserve.
    """
    img = _load_first_det_frame()
    # First call seeds the detector at ts=2000.
    _run_mediapipe(img, timestamp_ms=2000)
    # A subsequent call with an earlier timestamp must raise. The exact
    # exception class depends on MediaPipe's C++ binding (ValueError on
    # current versions); accept any exception type to keep the test
    # robust across mediapipe minor versions.
    with pytest.raises(Exception):
        _run_mediapipe(img, timestamp_ms=1000)
