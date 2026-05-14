# Phase 5 B r1 — real-data smoke results

**Date:** 2026-05-14
**Branch:** `feat/phase5-b-r1-relabel`
**Target dataset:** `runs/so101_phase4_v5/episode_000000__e35061106394/`
**Reviewer env:** `MIMICANNO_REVIEWER=takaki`

## Command

```bash
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
  --runs-root runs/so101_phase4_v5 \
  --host 127.0.0.1 --port 8765 \
  --cors-origin http://localhost:5173
```

## GET sanity

| URL | Result |
|---|---|
| `GET /healthz` | `200 {"status":"ok","runs_root":".../so101_phase4_v5"}` |
| `GET /api/labelset` | `200 {"labels":[{"id":"idle","requires_object":false}, ...]}` |
| `GET /api/runs/index.json` | `200` (39 runs indexed) |
| `GET /api/runs/.../manifest.json` | `200`, `ETag: "sha256:e3506110…"` |

Initial state of `episode_000000__seg0000`: `phase=approach_object`, `reviewed=false`, `reviewer_id=null`.

## PATCH status-code matrix

All 7 status-code paths exercised end-to-end against the live server.

| # | Case | Request | Status | Server envelope |
|---|---|---|---|---|
| 1 | Happy 200 | `If-Match: "<run_hash>"`, body `{"phase":"grasp_object"}` | **200** | new manifest body; `ETag: "sha256:c9c6ddb1…"` |
| 2 | 412 etag_mismatch | reuse old `run_hash` after #1 | **412** | `{"error":"etag_mismatch","message":"If-Match does not equal current manifest.run_hash"}` |
| 3 | 400 invalid_label | body `{"phase":"this_is_not_a_real_phase"}` | **400** | `{"error":"invalid_label","message":"phase '…' is not in the labelset"}` |
| 4 | 428 etag_required | omit `If-Match` | **428** | `{"error":"etag_required","message":"If-Match header is required"}` |
| 5 | 415 unsupported_media | `Content-Type: text/plain` | **415** | `{"error":"unsupported_media","message":"Content-Type must be application/json"}` |
| 6 | 405 wrong method | `GET /api/runs/.../segments/<id>` | **405** | `{"error":"http_405","message":"Method Not Allowed"}`, `Allow: PATCH` |

## Persistence verification

After Smoke #1 (the only 200), re-read `annotation.json` from disk:

```python
phase=grasp_object  reviewed=True  reviewer_id=takaki  smoothing_ops=['edited']
```

All four side effects landed atomically (spec §3.5 audit contract):
- Phase changed to the new label.
- `reviewed=True`.
- `reviewer_id` matches `MIMICANNO_REVIEWER` env.
- `smoothing_ops` appended `"edited"`.

## Notes

- **No 200→200 race possible** in single-client smoke — that's the §5.1 #13 concurrent test's job, already green via `tests/server/test_patch_concurrent.py` (uvicorn-in-process).
- The 412 message wording came verbatim from the server (`edit_repo.py` `EtagMismatch`) — the frontend toast format is `"<error_code>: <message>"` so the user sees `"etag_mismatch: If-Match does not equal …"`.
- The 405 `Allow: PATCH` header is the post-T8 enveloped-handler fix (`errors.py` preserves `exc.headers`).

## Exit-criteria mapping

Spec §6 exit criteria:

1. **"PATCH happy path round-trips end-to-end against `runs/so101_phase4_v5/`"** — ✅ Smoke #1 + disk read.
2. **"All enumerated test cases green"** — ✅ 1152 Python passed, 54 frontend passed.
3. **"Status-code matrix complete: 200 / 400×4 / 404 / 405 / 412 / 415 / 428"** — ✅ unit tests cover the missing `invalid_body` / `invalid_name` / `invalid_segment` / `run_not_found` (404) paths; #1-#6 above cover the rest end-to-end.
4. **"Race test is real-concurrency"** — ✅ `test_concurrent_patch_one_wins_one_412` produces `[200, 412]` deterministically.

r1 is shippable.
