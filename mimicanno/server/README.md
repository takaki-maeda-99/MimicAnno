# `mimicanno/server/` — Phase 5 A read-only + Phase 5 B r1 edit backend

Internal developer notes. User-facing entry point is the top-level
[`README.md`](../../README.md) `## Server` section.

Spec / plan:
- Phase 5 A spec: [`docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md`](../../docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md)
- Phase 5 B r1 spec: [`docs/superpowers/specs/2026-05-13-phase5-B-edit-relabel-design.md`](../../docs/superpowers/specs/2026-05-13-phase5-B-edit-relabel-design.md)
- Phase 5 B r1 plan: [`docs/superpowers/plans/2026-05-13-phase5-B-edit-relabel-plan.md`](../../docs/superpowers/plans/2026-05-13-phase5-B-edit-relabel-plan.md)
- Phase 5 B r1 smoke results: [`docs/superpowers/notes/2026-05-14-phase5-b-r1-results.md`](../../docs/superpowers/notes/2026-05-14-phase5-b-r1-results.md)

---

## Module layout

| file | role |
|---|---|
| `errors.py` | `MimicAnnoHTTPError` + `install_handlers(app)` — `{error, message}` envelope and a generic `Exception` handler that logs the stack but never leaks it to the response body. Preserves `exc.headers` so Starlette auto-405 keeps its `Allow: PATCH` header. |
| `runs_repo.py` | `RunsRepository` — sole read-side I/O entry point. Artifact allow-list, traversal guard, 100 ms × 3 retry on `FileNotFoundError`. |
| `labelset.py` | `LabelSetCache` — loads `labels.yaml` once at server startup, computes `labels_yaml_sha256`, and serves it on `GET /api/labelset` with `Cache-Control: public, max-age=300`. |
| `edit_repo.py` | `apply_edit(...)` — Phase 5 B r1 transactional write. Takes the `runs/index.json.lock` file lock, re-reads manifest + annotation, validates `If-Match` against current `run_hash`, validates the new phase against the labelset, mutates segment (`reviewed=True`, `reviewer_id`, `smoothing_ops += ["edited"]`, `_recompute_confidence`), writes annotation → manifest → index in that order. Derives the new `run_hash` as `sha256("edit:" + old_run_hash + ":" + segment_id + ":" + new_phase + ":" + (reviewer or ""))` — disjoint from auto-pipeline hashes. |
| `routes.py` | `make_router(runs_root, labelset, reviewer)` — `/healthz`, GET endpoints, `GET /api/labelset`, and `PATCH /api/runs/{name}/segments/{segment_id}`. PATCH route is `async def` and dispatches to `apply_edit` via `asyncio.to_thread` so the blocking file lock doesn't pin the uvicorn event loop. |
| `app.py` | `create_app(*, runs_root, cors_origins, reviewer=None, labelset=None)` — FastAPI factory. CORS allows `GET, HEAD, PATCH, OPTIONS` when `cors_origins` is non-empty. |
| `__init__.py` | empty (package marker) |

CLI wiring lives in [`mimicanno/cli.py`](../cli.py) (`serve_cmd`). The lazy
`from mimicanno.server.app import create_app` inside the command body
keeps the base install slim — if the user runs `mimicanno serve` without
`uv sync --extra server`, they get a friendly error rather than an
ImportError stack.

## Concurrency contract

Reads never take `runs/index.json.lock`. The contract relies on writers
using `tmp.replace()` (atomic, see `mimicanno/runindex.py:45-47`) for the
index and a two-step rename (`final → bak`, then `tmp → final`, then
`rm -rf bak`) for the run dir replacement (see
`mimicanno/publish.py:141-165`). The dir-gap between the two renames is
typically milliseconds; the server's 100 ms × 3 retry on
`FileNotFoundError` covers it.

This is verified by `tests/server/test_concurrent_publish.py` which spins
a real rename loop in a thread against 200 GETs — expects every response
to be 200 or 404, never 500.

## Error envelope

```json
{ "error": "<code>", "message": "<human-readable>" }
```

Codes currently emitted:

| HTTP | code | when |
|---|---|---|
| 400 | `invalid_name` | `canonical_name` did not match `^[A-Za-z0-9_]+$` |
| 404 | `index_missing` | `runs/index.json` not present after retries |
| 404 | `run_not_found` | run dir missing after retries |
| 404 | `artifact_not_found` | artifact not in allow-list, or resolved outside `runs_root` (symlink escape) |
| 500 | `internal` | unhandled exception; the stack is logged at `ERROR` on the `mimicanno.server` logger, never in the body |

FastAPI's default `{"detail": "..."}` shape is overridden by
`install_handlers` so the contract is stable.

## Tests

```bash
uv run --extra server pytest tests/server/ -q
```

| file | count | covers |
|---|---|---|
| `test_errors.py` | 5 | envelope shape, FastAPI HTTPException re-wrap, no-stack-leak, status code range, logging |
| `test_runs_repo.py` | 11 | allow-list, regex, symlink escape, retry success / exhaust, index-missing |
| `test_routes.py` | 17 | spec §4.1 cases (CORS-less) — happy path, 404s, ETag, HEAD, traversal, dir-gap retry, truncated JSON, streaming |
| `test_app.py` | 4 | factory wiring + CORS preflight (allowed / unconfigured / disallowed origin) |
| `test_serve_cli.py` | 2 | subprocess integration (free-port, SIGTERM graceful shutdown) + friendly missing-extra error |
| `test_concurrent_publish.py` | 1 | real rename race against 200 GETs |

Plus the full repo regression `uv run pytest tests/ -q` (1070 passing as
of the last green check) stays green when `[server]` is not synced.

## Type checking

```bash
uv run --extra server mypy --strict mimicanno/server
```

The `[[tool.mypy.overrides]]` block in `pyproject.toml` carries
`ignore_missing_imports = true` for `fastapi.*`, `starlette.*`, `uvicorn*`
(their stubs are incomplete). Handlers use `assert isinstance(exc, ...)`
to narrow `Exception` to the concrete subclass since starlette's
`add_exception_handler` only accepts `Callable[[Request, Exception], ...]`.

## PATCH write contract (Phase 5 B r1)

`PATCH /api/runs/{name}/segments/{segment_id}` is the **only** write
endpoint. Contract (spec §3.5):

1. Request validation pre-lock: `Content-Type: application/json` (415 if not), `If-Match: "<hash>"` present (428 if not), body must be `{"phase": "<id>"}` with exactly one key (400 `invalid_body`), name + segment_id match canonical regexes (400 `invalid_name` / `invalid_segment`).
2. Acquire `runs/index.json.lock` (30 s timeout — far above the ms-scale workload; failure is a 500).
3. **Re-read** manifest + annotation under the lock. Compare `If-Match` to the freshly-read `manifest.run_hash` (412 `etag_mismatch` if drift).
4. Validate the new phase against the labelset (400 `invalid_label`).
5. Mutate the segment: `phase = new`, `reviewed = True`, `reviewer_id = <MIMICANNO_REVIEWER env>`, `smoothing_ops += ["edited"]` (deduped — re-edits don't double-append), and recompute `overall_confidence` via the existing smoother.
6. Compute new `run_hash` as `sha256("edit:" + old_hash + ":" + segment_id + ":" + new_phase + ":" + (reviewer or ""))`. Edit-derived hashes carry the `"edit:"` prefix in the pre-image so they're disjoint from auto-pipeline `run_hash`es by construction — `git log`-style audit can tell at a glance which runs were human-touched.
7. Write annotation.json → manifest.json → index.json in that order. Annotation is written first so a crash mid-write leaves manifest pointing at the OLD `run_hash` and the index reflecting that state. Recovery: rerun the same PATCH (idempotent since manifest's `run_hash` is unchanged and the new value is deterministic).
8. Release lock, return 200 with body = new manifest and `ETag: "<new_run_hash>"`.

Real-concurrency test (`tests/server/test_patch_concurrent.py`) spawns
`uvicorn.Server` in a thread and fires two parallel PATCHes with the
same `If-Match` against a real disk: result is deterministically
`sorted(codes) == [200, 412]`, never `[200, 200]` or `[500, *]`.

## Out of scope

Deferred to other Phase 5 r2+ / sub-projects (see spec §1.4 and §2):

- Boundary drag edits, object/target relabel, `reviewed` toggle independent of phase change — Phase 5 B r2-r4
- Bulk multi-segment edits, undo history — Phase 5 B r5+
- Evaluation metrics (`human_edit_time`, label agreement) — Phase 5 D
- MimicRec Replay page integration — Phase 5 E
- Auth, multi-user, HTTPS, docker / systemd / reverse proxy — Phase 6+
