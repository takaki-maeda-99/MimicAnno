"""Phase 5 A T7: server retry under a real publish-style rename race.

Reproduces the publish sequence (``publish.py:141-165``) in a thread:

  1. ``runs/<name>/``        → ``runs/<name>.bak/``  (rename)
  2. ``runs/<name>.tmp.N/``  → ``runs/<name>/``      (rename)
  3. ``rm -rf runs/<name>.bak/``

Races against many concurrent GETs on the manifest. The server's 3×100ms
retry should absorb the dir-gap window — we accept 200 (read succeeded
either before or after the swap) or 404 (retry exhausted), but NEVER 500
(= unhandled FileNotFoundError reached the client).
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient


def test_concurrent_publish_no_500(tmp_runs_root: Path, canonical_name: str) -> None:
    from mimicanno.server.app import create_app

    app = create_app(runs_root=tmp_runs_root, cors_origins=[])
    client = TestClient(app)

    final = tmp_runs_root / canonical_name
    bak = tmp_runs_root / f"{canonical_name}.bak"
    tmp_new = tmp_runs_root / f"{canonical_name}.tmp.999"

    # Preseed the tmp dir with a valid manifest so each cycle has something
    # to rename into place.
    shutil.copytree(final, tmp_new)

    stop = threading.Event()
    errors: list[BaseException] = []

    def publisher() -> None:
        """Race publish.py:141-165 sequence repeatedly until stopped."""
        try:
            cycles = 0
            while not stop.is_set() and cycles < 50:
                # 1. final → bak
                final.rename(bak)
                # 2. tmp → final
                tmp_new_path = tmp_runs_root / f"{canonical_name}.tmp.{cycles}"
                shutil.copytree(bak, tmp_new_path)
                tmp_new_path.rename(final)
                # 3. rm -rf bak
                shutil.rmtree(bak)
                cycles += 1
        except BaseException as exc:  # noqa: BLE001 — capture for assertion
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(100):
                r = client.get(f"/api/runs/{canonical_name}/manifest.json")
                # NEVER 500 — the server must absorb FileNotFoundError into 200/404.
                assert r.status_code in (200, 404), (
                    f"unexpected status {r.status_code}: {r.text}"
                )
                if r.status_code == 200:
                    parsed = json.loads(r.content)
                    assert "run_hash" in parsed
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    pub = threading.Thread(target=publisher, daemon=True)
    rd1 = threading.Thread(target=reader, daemon=True)
    rd2 = threading.Thread(target=reader, daemon=True)

    pub.start()
    rd1.start()
    rd2.start()
    rd1.join(timeout=30)
    rd2.join(timeout=30)
    stop.set()
    pub.join(timeout=30)

    # If any thread raised, surface that.
    if errors:
        raise errors[0]
    # Confirm readers actually finished (didn't hang on a dirgap).
    assert not rd1.is_alive() and not rd2.is_alive()
