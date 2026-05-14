"""Phase 5 B r1 T11: real-concurrency race on PATCH (spec §5.1 #13).

TestClient is synchronous and serialises requests, so race conditions
aren't observable. T11 spawns ``uvicorn.Server`` in a background thread
so two parallel PATCH requests with the same If-Match race for the
``runs/index.json.lock`` in ``edit_repo.apply_edit``. The serialiser
MUST produce exactly one 200 + one 412 etag_mismatch.

Prerequisite (T11 commit): the PATCH route wraps ``apply_edit`` in
``asyncio.to_thread`` so the blocking call doesn't pin the event loop;
otherwise this test would observe [200, 412] even with the file_lock
removed (event loop would serialise at request level), testing
nothing.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path

import httpx
import uvicorn


_READY_DEADLINE_SEC = 10.0


def _wait_ready(port: int) -> None:
    deadline = time.monotonic() + _READY_DEADLINE_SEC
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise TimeoutError(f"uvicorn never became ready on port {port}")


def test_concurrent_patch_one_wins_one_412(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    free_port: int,
) -> None:
    """Spec §5.1 #13: two concurrent PATCH with the SAME If-Match →
    exactly one 200, exactly one 412 etag_mismatch.

    Deterministic invariants:
    - ``sorted([codes]) == [200, 412]``
    - Never [200, 200]: the second PATCH's If-Match equals the OLD
      run_hash; after the first completes, manifest.run_hash has
      changed → second hits EtagMismatch.
    - Never [500, ...]: the file_lock timeout is 30s, far above the
      ms-scale workload.
    """
    from mimicanno.server.app import create_app

    name = loadable_canonical_name
    app = create_app(
        runs_root=tmp_runs_root_loadable,
        cors_origins=[],
        reviewer="race-test",
    )
    config = uvicorn.Config(
        app, host="127.0.0.1", port=free_port,
        log_level="warning", lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        _wait_ready(free_port)
        base = f"http://127.0.0.1:{free_port}"

        # One shared httpx.Client — thread-safe since httpx 0.20.
        with httpx.Client(base_url=base, timeout=10.0) as client:
            initial_rh = client.get(
                f"/api/runs/{name}/manifest.json",
            ).json()["run_hash"]
            seg_id = client.get(
                f"/api/runs/{name}/annotation.json",
            ).json()["segments"][0]["segment_id"]

            # Barrier so both worker threads call client.patch within
            # μs of each other — minimises synchronization jitter.
            # timeout=5 raises BrokenBarrierError if one thread crashes
            # pre-barrier, so the test fails fast instead of hanging.
            barrier = threading.Barrier(2)

            def do_patch(target_phase: str) -> httpx.Response:
                barrier.wait(timeout=5)
                return client.patch(
                    f"/api/runs/{name}/segments/{seg_id}",
                    headers={
                        "Content-Type": "application/json",
                        "If-Match": f'"{initial_rh}"',
                    },
                    content=f'{{"phase":"{target_phase}"}}',
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                futures = [
                    ex.submit(do_patch, "idle"),
                    ex.submit(do_patch, "approach_object"),
                ]
                results = [f.result() for f in futures]
            # ThreadPoolExecutor.__exit__ blocks until both workers
            # finish — safe to read disk state below.

        codes = sorted(r.status_code for r in results)
        assert codes == [200, 412], (
            f"got {codes}; bodies={[r.text for r in results]}"
        )

        # 412 carries the etag_mismatch envelope; 200 carries an ETag
        # header equal to the response body's new run_hash.
        for r in results:
            if r.status_code == 412:
                assert r.json()["error"] == "etag_mismatch"
            else:
                new_rh = r.json()["run_hash"]
                assert r.headers["etag"] == f'"{new_rh}"'

        # Disk reflects only the winner's edit.
        with httpx.Client(base_url=base, timeout=5.0) as client:
            ann_post = client.get(
                f"/api/runs/{name}/annotation.json",
            ).json()
        seg = ann_post["segments"][0]
        assert seg["phase"] in {"idle", "approach_object"}
        assert seg["smoothing_ops"][-1] == "edited"
        assert seg["reviewed"] is True
        assert seg["reviewer_id"] == "race-test"

    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=2)
