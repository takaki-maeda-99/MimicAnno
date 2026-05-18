"""Test the NaN-tolerant Gaussian smoothing helper used by the pinch-distance
post-processing in ``scripts/run_hand_estimation.py``.

The helper is exercised on the production path whenever a frame range
contains long contiguous no-detection segments (pinch is None there).
Previously it emitted ``RuntimeWarning: invalid value encountered in divide``
on every such region because the division was computed before the
``np.where`` mask. The fix wraps the divide in ``np.errstate(...)`` so the
warning no longer surfaces. This test guards against accidental
reintroduction.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# scripts/ is not a package; add to sys.path so the test can import directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_hand_estimation import _gaussian_smooth_with_nan  # type: ignore


def test_gaussian_smooth_all_nan_does_not_warn():
    """The input is entirely NaN — every output index has zero weight.

    Pre-fix this emitted the divide-by-zero RuntimeWarning on every element.
    After the fix the operation runs silently and returns all-NaN.
    """
    vals = np.full(50, np.nan, dtype=np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning -> test failure
        out = _gaussian_smooth_with_nan(vals, sigma=2.0)
    assert out.shape == vals.shape
    assert np.isnan(out).all()


def test_gaussian_smooth_partial_nan_does_not_warn():
    """Mixed input: valid values bookend a long NaN gap.

    The NaN region should come back as NaN (no nearby valid weight) while
    the bookend regions should smooth normally — without any warning."""
    vals = np.full(50, np.nan, dtype=np.float64)
    vals[:5] = 1.0
    vals[-5:] = 2.0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = _gaussian_smooth_with_nan(vals, sigma=1.5)
    assert np.isfinite(out[0])
    assert np.isfinite(out[-1])
    # Center indices are far from any valid sample → NaN.
    assert np.isnan(out[25])


def test_gaussian_smooth_no_smoothing_with_sigma_zero():
    """sigma <= 0 short-circuits to a plain copy (existing semantics)."""
    vals = np.array([1.0, np.nan, 3.0, np.nan])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = _gaussian_smooth_with_nan(vals, sigma=0.0)
    np.testing.assert_array_equal(np.isnan(out), np.isnan(vals))
    np.testing.assert_array_equal(out[~np.isnan(out)], vals[~np.isnan(vals)])


def test_gaussian_smooth_empty_input():
    """Empty input is a degenerate but valid case (operator passes a
    zero-frame range)."""
    vals = np.array([], dtype=np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = _gaussian_smooth_with_nan(vals, sigma=2.0)
    assert out.shape == (0,)
