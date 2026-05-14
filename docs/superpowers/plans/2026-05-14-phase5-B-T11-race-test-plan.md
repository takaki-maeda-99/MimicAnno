# T11 — uvicorn-in-process PATCH race test (final, post 2 review rounds)

Date: 2026-05-14
Branch: `feat/phase5-b-r1-relabel`
Parent plan: [`2026-05-14-phase5-B-T6-T11-subplans.md`](./2026-05-14-phase5-B-T6-T11-subplans.md)
Spec: [`../specs/2026-05-13-phase5-B-edit-relabel-design.md`](../specs/2026-05-13-phase5-B-edit-relabel-design.md) §5.1 #13

---

## Goal

Real-concurrency race test: 2 parallel PATCH requests with the same
If-Match → exactly one 200, one 412. Proves `runs/index.json.lock` in
`edit_repo.apply_edit` is the serializing primitive (not the event loop).

## Round 1 critical finding (resolved)

`patch_segment` in `mimicanno/server/routes.py` is `async def` but
synchronously calls blocking `apply_edit(...)`. Under uvicorn's single
event loop, that call blocks the loop and serialises ALL requests
(including `/healthz`). A race test would observe `[200, 412]` even with
`file_lock` removed — testing nothing.

**Fix (load-bearing for T11)**: wrap `apply_edit` in
`await asyncio.to_thread(...)`, dispatching the blocking call to a
threadpool worker so the event loop stays responsive and the file lock
becomes the only serialising primitive.

This is **also a production correctness fix** — without it, long PATCHes
freeze `/healthz` and any other endpoint.

## Files touched

1. `mimicanno/server/routes.py` — `import asyncio` + the `apply_edit(...)`
   call at the current line ~131 becomes
   `await asyncio.to_thread(apply_edit, ...)`. All other code paths
   unchanged.
2. `tests/server/test_patch_concurrent.py` — new file, 1 test.

## routes.py change (consolidated, copy-paste ready)

```python
import asyncio
...
        # Step 4: edit_repo.apply_edit + EditError → HTTP mapping.
        try:
            new_manifest = await asyncio.to_thread(
                apply_edit,
                runs_root=runs_root,
                name=name,
                segment_id=segment_id,
                new_phase=body["phase"],
                if_match=if_match,
                reviewer=reviewer,
                labelset=labelset.ls,
            )
        except RunNotFound:
            raise MimicAnnoHTTPError(...)
        # ... rest of exception mapping unchanged
```

## Test file (consolidated)

```python
"""Phase 5 B r1 T11: real-concurrency race on PATCH (spec §5.1 #13)."""
from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path

import httpx
import pytest
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
    exactly one 200, exactly one 412 etag_mismatch. Proves the
    file_lock in edit_repo.apply_edit (not the event loop, after T11's
    asyncio.to_thread fix to routes.py) is the serializing primitive.

    Deterministic invariants:
    - sorted([r1.status_code, r2.status_code]) == [200, 412]
    - Never [200, 200]: the second PATCH's If-Match equals the OLD
      run_hash; after the first completes, manifest.run_hash has changed
      → second hits EtagMismatch.
    - Never [500, ...]: file_lock timeout is 30s, far above ms-scale.
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

        # One shared httpx.Client — httpx is thread-safe since 0.20.
        with httpx.Client(base_url=base, timeout=10.0) as client:
            initial_rh = client.get(
                f"/api/runs/{name}/manifest.json",
            ).json()["run_hash"]
            seg_id = client.get(
                f"/api/runs/{name}/annotation.json",
            ).json()["segments"][0]["segment_id"]

            # Barrier so both worker threads call client.patch within μs
            # of each other — minimises sync jitter.
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
            # finish — safe to tear down the server now.

        codes = sorted(r.status_code for r in results)
        assert codes == [200, 412], (
            f"got {codes}; bodies={[r.text for r in results]}"
        )

        # 412 carries the etag_mismatch envelope; 200 carries the new
        # ETag header equal to the response body's run_hash.
        for r in results:
            if r.status_code == 412:
                assert r.json()["error"] == "etag_mismatch"
            else:
                new_rh = r.json()["run_hash"]
                assert r.headers["etag"] == f'"{new_rh}"'

        # Disk reflects the winner's edit only.
        with httpx.Client(base_url=base, timeout=5.0) as client:
            ann_post = client.get(f"/api/runs/{name}/annotation.json").json()
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
```

## Procedure (TDD-light)

1. Apply the routes.py `asyncio.to_thread` change first
2. Re-run existing T8 (22) + T10 (3) + T10b (2) → confirm no regression
3. Write `tests/server/test_patch_concurrent.py` with the test above
4. Run only the new test
5. mypy --strict clean
6. Full server regression (`pytest tests/server/`)
7. commit `feat(phase5-b/T11): asyncio.to_thread for true concurrency + race test`

## Verify

```bash
uv run --extra server pytest tests/server/test_routes_patch.py tests/server/test_routes_patch_cycle.py tests/server/test_edit_short_circuit.py -q   # regression
uv run --extra server pytest tests/server/test_patch_concurrent.py -v
uv run --extra server pytest tests/server/ -q --tb=no
uv run --extra server mypy mimicanno/server
```

## Risks

- **uvicorn lifecycle quirks**: `should_exit` checked between request
  loops; `force_exit` is the hard kill. Daemon thread + ephemeral port
  means leftover socket dies with process anyway. Test cleanup safe.
- **flaky port reuse**: each test fixture call to `free_port` gets a new
  one; no inter-test collision.
- **pytest global timeout**: confirmed `pyproject.toml` has
  `pytest-timeout` but no aggressive `--timeout` config; our 15-second
  wall-clock is fine.
- **httpx.Client thread-safety**: confirmed safe since 0.20 (we pin
  `httpx>=0.27`).
- **route fix breaks existing tests**: `asyncio.to_thread` is supported
  by TestClient's asyncio loop; T8 tests stay green (re-confirmed in
  Procedure step 2).
- **Barrier hang**: `Barrier.wait(timeout=5)` raises `BrokenBarrierError`
  if one thread crashes pre-barrier — test fails fast instead of hanging.

## 所要

~40-45 minutes:
- routes.py to_thread edit + import asyncio: 3 min
- existing T8/T10/T10b re-run: 2 min
- test_patch_concurrent.py: 18 min
- red→green (flake debug): 10 min
- mypy + full regression: 5 min
- commit: 2 min

## Out of scope

- 3+ PATCH concurrent (2 covers spec §5.1 #13)
- different-segment concurrent PATCH (T10 already covers chained)
- frontend concurrency (T13+ unrelated)
- async edit_repo refactor (T11 only inserts `asyncio.to_thread`, not a
  full async port)
