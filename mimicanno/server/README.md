# `mimicanno/server/` — Phase 5 A persistence backend (read-only)

Internal developer notes. User-facing entry point is the top-level
[`README.md`](../../README.md) `## Server` section.

Spec / plan:
- spec: [`docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md`](../../docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md)
- plan: [`docs/superpowers/plans/2026-05-12-phase5-A-persistence-backend-plan.md`](../../docs/superpowers/plans/2026-05-12-phase5-A-persistence-backend-plan.md)

---

## Module layout

| file | role |
|---|---|
| `errors.py` | `MimicAnnoHTTPError` + `install_handlers(app)` — `{error, message}` envelope and a generic `Exception` handler that logs the stack but never leaks it to the response body. |
| `runs_repo.py` | `RunsRepository` — sole I/O entry point. Artifact allow-list (5 files), `canonical_name` regex, `resolve() + is_relative_to(root)` traversal guard, 100 ms × 3 retry on `FileNotFoundError`. Returns `(path, bytes \| None)` so the route can stream non-manifest artifacts via `FileResponse`. |
| `routes.py` | `make_router(runs_root)` — `/healthz`, `GET /api/runs/index.json`, `GET /api/runs/{name}/{artifact}` (manifest carries `ETag: "<run_hash>"`). |
| `app.py` | `create_app(*, runs_root, cors_origins)` — FastAPI factory. CORS middleware is added only when `cors_origins` is non-empty. |
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

## Out of scope

Deferred to other Phase 5 sub-projects (see spec §2 and §3.8):

- Write endpoints (`PATCH /api/runs/<name>/segments/...`, edit locking)
  — Phase 5 B
- Viewer migration from static fetch to `/api/runs/*` — Phase 5 B
- Evaluation metrics (`human_edit_time`, label agreement) — Phase 5 D
- MimicRec Replay page integration — Phase 5 E
- Auth, multi-user, HTTPS, docker / systemd / reverse proxy — Phase 6+
