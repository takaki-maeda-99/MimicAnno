# T8 — PATCH route implementation plan (final, post 3 review rounds)

Date: 2026-05-14
Branch: `feat/phase5-b-r1-relabel`
Parent plan: [`2026-05-14-phase5-B-T6-T11-subplans.md`](./2026-05-14-phase5-B-T6-T11-subplans.md)
Spec: [`../specs/2026-05-13-phase5-B-edit-relabel-design.md`](../specs/2026-05-13-phase5-B-edit-relabel-design.md) §3.1, §3.4, §3.6, §5.1

---

## Goal

`PATCH /api/runs/{name}/segments/{segment_id}` + 15 unit tests, covering
spec §5.1 #1-#11 and 4 HTTP extras (ETag/Cache-Control/quote handling/
reviewer integration).

## Files touched

1. `mimicanno/server/errors.py` — `_http_exception_handler` forwards
   `exc.headers` so Starlette auto-405's `Allow:` header survives.
2. `mimicanno/server/routes.py` — remove T7's `del reviewer`; add the
   PATCH route inside `make_router`'s closure.
3. `tests/server/test_routes_patch.py` (new) — 15 tests.

## errors.py edit (1 location)

```python
async def _http_exception_handler(
    request: Request, exc: Exception,
) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    headers = (
        dict(exc.headers) if getattr(exc, "headers", None) else None
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code=f"http_{exc.status_code}", message=detail),
        headers=headers,
    )
```

## routes.py PATCH route (consolidated, all round-1/2 fixes inline)

```python
import json
from fastapi import Request

# In make_router(runs_root, labelset, reviewer=None):
#   - REMOVE the line: `del reviewer`  (T7 placeholder)
#   - Add the PATCH route BEFORE the /{name}/{artifact} catch-all:

@router.api_route(
    "/api/runs/{name}/segments/{segment_id}",
    methods=["PATCH"],
)
async def patch_segment(
    name: str,
    segment_id: str,
    request: Request,
    r: RunsRepository = Depends(get_repo),
) -> Response:
    # Step 1: Content-Type (415). RFC 7231 case-insensitive.
    ct = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ct != "application/json":
        raise MimicAnnoHTTPError(
            status=415, code="unsupported_media",
            message="Content-Type must be application/json",
        )

    # Step 2: If-Match (428). RFC 7232 quote-strip; weak tags
    # (W/"...") fall through to the 412 mismatch on strict compare.
    if_match = request.headers.get("if-match", "")
    if not if_match:
        raise MimicAnnoHTTPError(
            status=428, code="etag_required",
            message="If-Match header is required",
        )
    if len(if_match) >= 2 and if_match[0] == '"' and if_match[-1] == '"':
        if_match = if_match[1:-1]

    # Step 3: Body parse + shape (400 invalid_body).
    try:
        raw_body = await request.body()
        body = json.loads(raw_body) if raw_body else None
    except json.JSONDecodeError as exc:
        raise MimicAnnoHTTPError(
            status=400, code="invalid_body",
            message=f"body must be valid JSON: {exc.msg}",
        )
    if (
        not isinstance(body, dict)
        or set(body.keys()) != {"phase"}
        or not isinstance(body.get("phase"), str)
    ):
        raise MimicAnnoHTTPError(
            status=400, code="invalid_body",
            message="body must be exactly {'phase': '<label_id>'}",
        )

    # Step 4: edit_repo.apply_edit + EditError → HTTP mapping.
    try:
        new_manifest = apply_edit(
            runs_root=r.root,
            name=name,
            segment_id=segment_id,
            new_phase=body["phase"],
            if_match=if_match,
            reviewer=reviewer,
            labelset=labelset.ls,
        )
    except RunNotFound:
        raise MimicAnnoHTTPError(
            status=404, code="run_not_found",
            message=f"run not found: {name!r}",
        )
    except EtagMismatch:
        raise MimicAnnoHTTPError(
            status=412, code="etag_mismatch",
            message="If-Match does not equal current manifest.run_hash",
        )
    except InvalidLabel:
        raise MimicAnnoHTTPError(
            status=400, code="invalid_label",
            message=f"phase {body['phase']!r} is not in the labelset",
        )
    except InvalidSegment:
        raise MimicAnnoHTTPError(
            status=400, code="invalid_segment",
            message=f"segment_id {segment_id!r} not found in annotation",
        )

    # Step 5: 200 + new ETag.
    new_run_hash = new_manifest["run_hash"]
    return Response(
        content=json.dumps(new_manifest).encode("utf-8"),
        media_type="application/json",
        headers={
            "ETag": f'"{new_run_hash}"',
            "Cache-Control": "no-cache",
        },
    )
```

## Test file (tests/server/test_routes_patch.py) — 15 tests

Fixtures: `tmp_runs_root_loadable`, `loadable_canonical_name`.

```python
def _client(tmp_runs_root_loadable, reviewer=None):
    app = create_app(
        runs_root=tmp_runs_root_loadable, cors_origins=[], reviewer=reviewer,
    )
    return TestClient(app)


def _snapshot(run_dir, runs_root):
    return (
        (run_dir / "annotation.json").read_bytes(),
        (run_dir / "manifest.json").read_bytes(),
        (runs_root / "index.json").read_bytes(),
    )


def _assert_unchanged(run_dir, runs_root, snap):
    assert (run_dir / "annotation.json").read_bytes() == snap[0]
    assert (run_dir / "manifest.json").read_bytes() == snap[1]
    assert (runs_root / "index.json").read_bytes() == snap[2]
```

| # | Test | spec §5.1 # |
|---|---|---|
| 1 | `test_patch_happy_path` — 200, new ETag, body = new manifest, all mutation fields | #1 |
| 2 | `test_patch_etag_correct_succeeds` — explicit "If-Match == current" → 200 | #2 |
| 3 | `test_patch_etag_stale_412` — `0...0` → 412 `etag_mismatch`, disk unchanged | #3 |
| 4 | `test_patch_if_match_absent_428` — no header → 428 `etag_required`, disk unchanged | #4 |
| 5 | `test_patch_invalid_body_missing_phase` — `{}` → 400 `invalid_body` | #5 |
| 6 | `test_patch_invalid_body_matrix` (parametrize 4): extra keys / non-str phase / empty body / non-JSON garbage → 400 `invalid_body` | #6 |
| 7 | `test_patch_invalid_label_400` — `{"phase":"foo"}` → 400 `invalid_label` | #7 |
| 8 | `test_patch_invalid_segment_400` — unknown segment_id → 400 `invalid_segment` | #8 |
| 9 | `test_patch_run_not_found_404` — unknown name → 404 `run_not_found` | #9 |
| 10 | `test_patch_unsupported_media_415` (parametrize 3): `text/plain` / 欠 / `Application/JSON` (mixed case) — first two 415, third 200 | #10 |
| 11 | `test_patch_on_artifact_path_405` — PATCH `/api/runs/<name>/manifest.json` → 405 + `Allow: GET, HEAD` header + envelope `error: http_405` | #11 |
| 12 | `test_patch_response_etag_header_matches_run_hash` | extra |
| 13 | `test_patch_response_cache_control_no_cache` | extra |
| 14 | `test_patch_if_match_with_quotes_works` — `If-Match: "sha256:..."` → 200 (quote stripped) | extra |
| 15 | `test_patch_reviewer_from_create_app` — `create_app(reviewer="alice")` → segment.reviewer_id == "alice" | extra |

Each 4xx test calls `_snapshot` pre and `_assert_unchanged` post.

## Spec §5.1 delegation map (18 total)

T8 owns #1-#11 + 4 extras. Earlier-task ownership:
- #12 reviewer encoding pinned hash → T6h ✅
- #14 smoothing_ops dedup → T6e ✅
- #15 non-target segments byte-identical → T6j ✅
- #17 GET /api/labelset ETag matches sha256 → T5 ✅

Later-task ownership:
- #13 race (uvicorn-in-process) → T11
- #16 annotate-overwrites-edit → T10b
- #18 collision-extended canonical_name → T10

## Procedure (TDD)

1. Write all 15 failing tests in `tests/server/test_routes_patch.py`
2. Confirm red (all 15 fail)
3. Edit `mimicanno/server/errors.py` (forward `exc.headers`)
4. Edit `mimicanno/server/routes.py` (remove `del reviewer`, add PATCH route)
5. Green
6. mypy --strict
7. commit `feat(phase5-b/T8): PATCH /api/runs/<name>/segments/<id>`

## Verify

```bash
uv run --extra server pytest tests/server/test_routes_patch.py -v
uv run --extra server pytest tests/server/ -q --tb=no   # full regression
uv run --extra server mypy mimicanno/server
```

## Risks

- **`Manifest.to_dict()` JSON-safety**: returns primitives (str/int/float/bool/list/dict/None) only, no datetime/Path/enum. Confirmed by Phase 5 A's existing `write_manifest_json` which dumps without serializer hooks.
- **errors.py header forwarding**: `tests/server/test_errors.py` does NOT assert header absence; safe to add. `exc.headers` is `None` on hand-raised HTTPException; the `if getattr(exc, "headers", None)` guard handles it.
- **`del reviewer` removal**: T7 placeholder; removing wakes up the closure binding. No test depends on it.
- **JSON arrays as top-level body**: `isinstance(body, dict)` rejects → 400 invalid_body. Good.
- **Empty string phase `""`**: `isinstance(str)` True → passes body check → `apply_edit` → InvalidLabel → 400. Different sub-code than `invalid_body` but acceptable per spec.

## 所要

~55 分:
- 15 tests: 20 分
- errors.py 1 行 + routes.py PATCH route: 15 分
- red→green debug: 10 分
- mypy + regression: 5 分
- commit: 2 分

## Out of scope

- T9 (`MIMICANNO_REVIEWER` env passthrough): separate task
- T10 (integration PATCH cycle): separate
- T10b (annotate overwrites): separate
- T11 (race): separate
