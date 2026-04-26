# mimicanno/locks.py
"""Cross-platform exclusive file lock with timeout."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class LockTimeout(Exception):  # noqa: N818
    pass


@contextmanager
def file_lock(path: Path, *, timeout_sec: float, poll_sec: float = 0.05) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``path``.

    Creates ``path`` if it does not exist. Releases automatically on exit.
    Raises :class:`LockTimeout` if the lock can't be acquired in ``timeout_sec``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")  # noqa: SIM115
    try:
        deadline = time.monotonic() + timeout_sec
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"could not acquire {path} within {timeout_sec:.2f}s",
                        ) from None
                    time.sleep(poll_sec)
            try:
                yield
            finally:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"could not acquire {path} within {timeout_sec:.2f}s",
                        ) from None
                    time.sleep(poll_sec)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()
