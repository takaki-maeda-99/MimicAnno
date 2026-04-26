# tests/unit/test_locks.py
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from mimicanno.locks import LockTimeout, file_lock


def _hold_lock_then_release(path: str, hold_sec: float, ready: mp.Event):
    from pathlib import Path

    with file_lock(Path(path), timeout_sec=10.0):
        ready.set()
        time.sleep(hold_sec)


def test_basic_acquire_and_release(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path, timeout_sec=2.0):
        assert lock_path.exists()
    # After release, re-acquiring is fine.
    with file_lock(lock_path, timeout_sec=2.0):
        pass


@pytest.mark.timeout(15)
def test_concurrent_blocks_then_acquires(tmp_path: Path):
    lock_path = tmp_path / "y.lock"
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    p = ctx.Process(target=_hold_lock_then_release, args=(str(lock_path), 1.0, ready))
    p.start()
    assert ready.wait(5.0)

    t0 = time.monotonic()
    with file_lock(lock_path, timeout_sec=5.0):
        elapsed = time.monotonic() - t0
        # Should have waited ~1s.
        assert elapsed >= 0.5
    p.join()


def test_timeout_raises(tmp_path: Path):
    lock_path = tmp_path / "z.lock"
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    p = ctx.Process(target=_hold_lock_then_release, args=(str(lock_path), 5.0, ready))
    p.start()
    assert ready.wait(5.0)
    with pytest.raises(LockTimeout), file_lock(lock_path, timeout_sec=0.5):
        pass
    p.join()
