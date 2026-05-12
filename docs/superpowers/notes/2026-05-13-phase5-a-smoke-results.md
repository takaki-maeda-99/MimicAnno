# Phase 5 A — manual smoke against `runs/so101_phase4_v5/` (T10)

Date: 2026-05-13
Branch: `feat/phase5-a-persistence-backend`
Spec: [`../specs/2026-05-12-phase5-A-persistence-backend-design.md`](../specs/2026-05-12-phase5-A-persistence-backend-design.md)

## Setup

```bash
PORT=$(uv run python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
uv run --extra server mimicanno serve \
    --runs-root runs/so101_phase4_v5 \
    --host 127.0.0.1 --port $PORT \
    --cors-origin http://localhost:5173 &
```

`runs/so101_phase4_v5/` = SO101 23 ep, Phase 4 v5 (source-aware merge)
output. Real index.json + manifests, not synthetic fixtures.

Ready in ~2.6 s (uvicorn startup + 13 × 200 ms readiness polls).

## Results

| check | result |
|---|---|
| `/healthz` | 200 `{"status":"ok","runs_root":"/misc/dl00/.../runs/so101_phase4_v5"}` |
| `/api/runs/index.json` | 200, 23 runs, schema_version 0.1.0, `manifest_url`-keyed (real shape, not the synthetic `canonical_name` key) |
| `/api/runs/<name>/manifest.json` | 200, `ETag: "sha256:834aa84279bd…"` matches `manifest.run_hash`, `Cache-Control: no-cache` |
| `/api/runs/<name>/boundaries.json` | 200, 4 candidates parsed cleanly |
| `/api/runs/<name>/tracks.json` (≈ 9.4 KB) | 200, served end-to-end in 12 ms |
| HEAD `/api/runs/<name>/manifest.json` | 200, ETag present, body empty |
| 404 path — `video.mp4` (not allow-listed) | 404 ✓ |
| 400 path — `has%20space/manifest.json` | 400 `invalid_name` ✓ |
| 404 path — `episode_999999/manifest.json` | 404 ✓ |
| CORS preflight `Origin: http://localhost:5173` | 200, `access-control-allow-origin: http://localhost:5173`, `access-control-allow-methods: GET, HEAD` |
| Graceful shutdown on SIGTERM | exit 0 within < 0.5 s |

## Finding: fixture vs real index.json shape

The synthetic fixture (`tests/server/conftest.py`) emits a
`canonical_name` field on each run row, but the real
`runs/<name>/index.json` produced by `mimicanno annotate` does
**not** have that field; instead each row carries `manifest_url:
"<canonical_name>/manifest.json"`. The server is bytes-passthrough so
this didn't cause any failure — but the fixture is misleading.

This is a **fixture-only issue**, not a contract issue: the server
spec (§3.3) says index.json is the spec-defined shape and the server
re-emits it as bytes. The fixture should match.

Follow-up:
- Update `tests/server/conftest.py` so the synthetic index.json mirrors
  the real shape (drop `canonical_name`, add `manifest_url`).
- No spec/code change needed.

## Exit criteria check (spec §6)

1. ✓ Local serve on real `runs/` returns 200 on index
2. ✓ Single + integration + concurrent tests all green (1070 passed pre-smoke)
3. ✓ Traversal (literal / percent / symlink) — blocked at 400/404 per `tests/server/test_routes.py`
4. ✓ Dir-gap retry simulated in tests; real-world wasn't triggered here (no concurrent publish during the smoke)
5. ✓ CORS allowlist works; preflight from a registered origin succeeds
6. ✓ Existing test suite green (unchanged)
7. ✓ Manifest carries `ETag: "<run_hash>"`
8. ✓ `mypy --strict` clean
9. ✓ `[server]` extra isolation — `uv sync` without `--extra server` doesn't pull fastapi/uvicorn
10. ✓ This note

All 10 exit criteria met. Sub-project A is ready for the next merge
gate (PR).
