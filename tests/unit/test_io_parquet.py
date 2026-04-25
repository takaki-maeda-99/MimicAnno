# tests/unit/test_io_parquet.py
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicanno.io_parquet import (
    ParquetLoadError,
    interpolate_short_nan_spans,
    load_episode_parquet,
    resolve_fps,
)


def _write_parquet(table: pa.Table, path: Path) -> Path:
    pq.write_table(table, path)
    return path


def _good_table(n: int = 30, fps: float = 30.0) -> pa.Table:
    return pa.table({
        "observation.state": pa.array([[0.0] * 14 for _ in range(n)]),
        "action": pa.array([[0.0] * 14 for _ in range(n)]),
        "timestamp": pa.array((np.arange(n) / fps).tolist()),
    })


class TestLoad:
    def test_load_returns_table_and_sha256(self, tmp_path: Path):
        p = _write_parquet(_good_table(), tmp_path / "ep.parquet")
        result = load_episode_parquet(p)
        assert result.table.num_rows == 30
        assert result.sha256.startswith("sha256:")

    def test_missing_required_column_raises(self, tmp_path: Path):
        bad = pa.table({
            "observation.state": pa.array([[0.0] * 14]),
            # action missing — but action is OPTIONAL per §7.1, so this is OK
            "timestamp": pa.array([0.0]),
        })
        p = _write_parquet(bad, tmp_path / "no_action.parquet")
        # Should NOT raise — action is optional in Phase 1.
        result = load_episode_parquet(p)
        assert result.table.num_rows == 1

    def test_missing_state_raises(self, tmp_path: Path):
        bad = pa.table({
            "action": pa.array([[0.0]]),
            "timestamp": pa.array([0.0]),
        })
        p = _write_parquet(bad, tmp_path / "bad.parquet")
        with pytest.raises(ParquetLoadError, match="observation.state"):
            load_episode_parquet(p)


class TestResolveFps:
    def test_uniform_timestamps(self):
        ts = np.arange(60, dtype=np.float64) / 30.0
        assert resolve_fps(ts) == pytest.approx(30.0, abs=0.01)

    def test_variance_too_high_raises(self):
        ts = np.array([0.0, 0.033, 0.066, 0.5, 0.6, 0.7])  # huge gap
        with pytest.raises(ParquetLoadError, match="variance"):
            resolve_fps(ts)

    def test_non_monotonic_raises(self):
        ts = np.array([0.0, 0.033, 0.020, 0.066])
        with pytest.raises(ParquetLoadError, match="monotonic"):
            resolve_fps(ts)


class TestInterpolateShortNan:
    def test_short_span_filled(self):
        x = np.array([1.0, 2.0, np.nan, np.nan, 5.0, 6.0])
        out = interpolate_short_nan_spans(x, fps=30.0, max_span_sec=0.5)
        assert np.isfinite(out).all()
        assert out[2] == pytest.approx(3.0, abs=1e-6)
        assert out[3] == pytest.approx(4.0, abs=1e-6)

    def test_long_span_raises(self):
        # 30 fps, 30 NaN frames in a row = 1.0 s span > 0.5 s threshold
        x = np.concatenate([np.arange(10.0), np.full(30, np.nan), np.arange(10.0) + 40])
        with pytest.raises(ParquetLoadError, match="NaN span"):
            interpolate_short_nan_spans(x, fps=30.0, max_span_sec=0.5)
