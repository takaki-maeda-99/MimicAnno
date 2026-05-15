"""Phase 5 B r2 T8: real-concurrency race on boundary PATCH (spec §5.1 #16).

TestClient serialises requests, so T5's threading test covers logic but
not OS-level interleaving. This test spawns uvicorn.Server in a background
thread — identical pattern to r1's test_patch_concurrent.py — so two
parallel boundary PATCHes race for ``runs/index.json.lock`` in
``patch_boundary``.  Result MUST be exactly {200, 412}.

Prerequisite: the PATCH boundary route dispatches via asyncio.to_thread
(routes.py T5) so the blocking call doesn't pin the event loop.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from pathlib import Path

import httpx
import uvicorn


_READY_DEADLINE_SEC = 10.0
_BOUNDARY_ID = "episode_000000__seg0001"  # boundary at frame 20


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


def test_concurrent_boundary_patch_one_wins_one_412(
    tmp_runs_root_loadable: Path, loadable_canonical_name: str,
    free_port: int,
) -> None:
    """Two concurrent boundary PATCHes with the same If-Match →
    exactly one 200, exactly one 412 etag_mismatch."""
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

        with httpx.Client(base_url=base, timeout=10.0) as client:
            initial_rh = client.get(
                f"/api/runs/{name}/manifest.json",
            ).json()["run_hash"]

            barrier = threading.Barrier(2)

            def do_patch(frame: int) -> httpx.Response:
                barrier.wait(timeout=5)
                return client.patch(
                    f"/api/runs/{name}/boundaries/{_BOUNDARY_ID}",
                    headers={
                        "Content-Type": "application/json",
                        "If-Match": f'"{initial_rh}"',
                    },
                    content=json.dumps({"frame": frame}),
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                futures = [
                    ex.submit(do_patch, 15),
                    ex.submit(do_patch, 25),
                ]
                results = [f.result() for f in futures]

        codes = sorted(r.status_code for r in results)
        assert codes == [200, 412], (
            f"got {codes}; bodies={[r.text for r in results]}"
        )

        for r in results:
            if r.status_code == 412:
                assert r.json()["error"] == "etag_mismatch"
            else:
                new_rh = r.json()["run_hash"]
                assert r.headers["etag"] == f'"{new_rh}"'

        # Disk reflects exactly one winning edit.
        with httpx.Client(base_url=base, timeout=5.0) as client:
            ann_post = client.get(f"/api/runs/{name}/annotation.json").json()

        segs = ann_post["segments"]
        # Left and right sides of the dragged boundary must be consistent.
        left_end = segs[0]["end_frame"]
        right_start = segs[1]["start_frame"]
        assert right_start == left_end + 1
        assert segs[0]["smoothing_ops"][-1] == "edited"
        assert segs[1]["smoothing_ops"][-1] == "edited"
        assert segs[0]["reviewer_id"] == "race-test"

    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=2)
