# tests/unit/test_signals.py
import numpy as np
import pytest

from mimicanno.signals import (
    SignalChannel,
    downsample_for_viewer,
    gaussian_smooth_1d,
    smoothing_sigma_for_fps,
)


class TestSmooth:
    def test_sigma_50ms(self):
        assert smoothing_sigma_for_fps(30.0) == pytest.approx(1.5)
        assert smoothing_sigma_for_fps(60.0) == pytest.approx(3.0)

    def test_smooth_preserves_dc(self):
        x = np.full(120, 0.7)
        out = gaussian_smooth_1d(x, sigma=1.5)
        assert out.shape == x.shape
        assert np.allclose(out, 0.7, atol=1e-3)

    def test_smooth_attenuates_step_edge(self):
        x = np.concatenate([np.zeros(60), np.ones(60)])
        out = gaussian_smooth_1d(x, sigma=3.0)
        # The exact midpoint (frame 60) should be near 0.5; right after it
        # the smoothed value rises monotonically toward 1.
        assert 0.3 < out[60] < 0.7
        assert out[58] < out[62]


class TestDownsample:
    def test_keeps_uniform_dt(self):
        full = np.arange(600, dtype=np.float64)
        ch = SignalChannel(name="x", unit="raw", values=full, dt_sec=1.0 / 60.0)
        out = downsample_for_viewer(ch, target_hz=30.0)
        assert out.dt_sec == pytest.approx(1.0 / 30.0, abs=1e-6)
        # 600 samples at 60Hz over 10s -> 300 samples at 30Hz
        assert 295 <= out.values.size <= 305

    def test_no_op_when_already_below_target(self):
        full = np.arange(60, dtype=np.float64)
        ch = SignalChannel(name="x", unit="raw", values=full, dt_sec=1.0 / 30.0)
        out = downsample_for_viewer(ch, target_hz=30.0)
        assert out.values.size == 60
        assert out.dt_sec == pytest.approx(1.0 / 30.0)


class TestSmoothEdgeCases:
    def test_zero_sigma_returns_copy(self):
        x = np.array([1.0, 2.0, 3.0])
        out = gaussian_smooth_1d(x, sigma=0.0)
        assert np.array_equal(out, x)
        assert out is not x  # copy, not the same object

    def test_nan_input_raises(self):
        x = np.array([1.0, float("nan"), 3.0])
        with pytest.raises(ValueError, match="NaN"):
            gaussian_smooth_1d(x, sigma=1.0)


class TestDownsampleEdgeCases:
    def test_zero_dt_raises(self):
        ch = SignalChannel(name="x", unit="raw", values=np.array([1.0]), dt_sec=0.0)
        with pytest.raises(ValueError, match="dt_sec"):
            downsample_for_viewer(ch, target_hz=30.0)

    def test_zero_target_hz_raises(self):
        ch = SignalChannel(name="x", unit="raw", values=np.array([1.0]), dt_sec=1.0 / 60.0)
        with pytest.raises(ValueError, match="target_hz"):
            downsample_for_viewer(ch, target_hz=0.0)
