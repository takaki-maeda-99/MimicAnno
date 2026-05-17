# U-A1: Catalog + Job Kick — implementation plan

Date: 2026-05-17
Spec: `docs/superpowers/specs/2026-05-17-ua-1-catalog-jobs-design.md`
Branch: `feat/ua-1-catalog-jobs`

## Execution order (TDD: tests first, then impl)

### Phase 1 — Backend catalog (B1, B2)

1. Write `tests/server/test_catalog_datasets.py` — B1 + B2 tests (skeleton, all XFAIL)
2. Write `mimicanno/server/catalog.py` — scan_datasets + get_dataset_detail
3. Write `mimicanno/server/catalog_routes.py` — GET /api/datasets + GET /api/datasets/{name}
4. Wire into `app.py` (no CORS change yet); run B1+B2 tests GREEN

### Phase 2 — Backend jobs persistence (B3)

5. Write `tests/server/test_job_store.py` — B3 tests
6. Write `mimicanno/server/job_store.py` — JobRecord dataclass + JobStore
7. B3 GREEN

### Phase 3 — Backend POST /api/jobs + query (B4, B7 partial)

8. Write `tests/server/test_job_routes.py` — B4 + B7 tests (GET /api/jobs, GET /api/jobs/{id}, GET /api/jobs/{id}/log, DELETE)
9. Add routes to `catalog_routes.py`
10. B4 + B7 GREEN

### Phase 4 — Job runner subprocess (B5)

11. Write `tests/server/test_job_runner.py` — B5 tests (mock Popen)
12. Write `mimicanno/server/job_runner.py` — JobQueue + async runner
13. B5 GREEN

### Phase 5 — Progress markers (B6)

14. Write `tests/server/test_progress_marker.py` — B6 tests
15. Patch `scripts/batch_annotate_4B.py` — emit marker
16. Patch `mimicanno/cli.py` annotate command — emit marker
17. B6 GREEN

### Phase 6 — SSE (B8)

18. Write `tests/server/test_job_sse.py` — B8 tests
19. Implement SSE route in `catalog_routes.py`
20. B8 GREEN

### Phase 7 — Server restart reclassification (B9)

21. Write `tests/server/test_job_restart_reclass.py` — B9 tests
22. Implement startup hook in `app.py`
23. B9 GREEN

### Phase 8 — CORS + `--jobs-dir` CLI (B10)

24. Write `tests/server/test_catalog_cors.py` — B10 tests
25. Update `app.py` CORS allow_methods
26. Update `mimicanno/cli.py` serve command for `--jobs-dir`
27. B10 GREEN

### Phase 9 — mypy + lint pass

28. `uv run mypy --strict mimicanno/`
29. Fix all type errors

### Phase 10 — Frontend (F1, F2, F3)

30. Inspect `frontend/src/App.tsx` for router setup
31. Write `frontend/src/pages/DatasetsPage.test.tsx` — F1+F2
32. Write `frontend/src/pages/DatasetsPage.tsx`
33. Write `frontend/src/pages/JobsPage.test.tsx` — F3
34. Write `frontend/src/pages/JobsPage.tsx`
35. Register routes in App.tsx
36. `cd frontend && npm test` GREEN

### Phase 11 — Full regression + PR

37. `uv run pytest tests/server/ -v` — all tests GREEN (≥ 252 existing + new)
38. `uv run mypy --strict mimicanno/`
39. `cd frontend && npm test`
40. `git add -f docs/superpowers/` + commit all changes
41. Push branch, create PR

## File changes summary

### New files
- `mimicanno/server/catalog.py`
- `mimicanno/server/catalog_routes.py`
- `mimicanno/server/job_store.py`
- `mimicanno/server/job_runner.py`
- `tests/server/test_catalog_datasets.py`
- `tests/server/test_job_store.py`
- `tests/server/test_job_routes.py`
- `tests/server/test_job_runner.py`
- `tests/server/test_progress_marker.py`
- `tests/server/test_job_sse.py`
- `tests/server/test_job_restart_reclass.py`
- `tests/server/test_catalog_cors.py`
- `frontend/src/pages/DatasetsPage.tsx`
- `frontend/src/pages/DatasetsPage.test.tsx`
- `frontend/src/pages/JobsPage.tsx`
- `frontend/src/pages/JobsPage.test.tsx`
- `docs/superpowers/specs/2026-05-17-ua-1-catalog-jobs-design.md`
- `docs/superpowers/plans/2026-05-17-ua-1-catalog-jobs-plan.md`

### Modified files
- `mimicanno/server/app.py` — CORS, `--jobs-dir`, startup hook, include catalog_router
- `mimicanno/cli.py` — annotate progress marker, serve `--jobs-dir`
- `scripts/batch_annotate_4B.py` — progress marker
- `frontend/src/App.tsx` (or router file) — add /datasets, /jobs routes
