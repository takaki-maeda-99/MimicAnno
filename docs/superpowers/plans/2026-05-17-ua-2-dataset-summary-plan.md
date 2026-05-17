# U-A2 — Dataset Summary — implementation plan

Date: 2026-05-17
Branch: `feat/ua-2-dataset-summary`
Spec: `docs/superpowers/specs/2026-05-17-ua-2-dataset-summary-design.md`

## TDD slices (order matters)

### Slice 1 — Inspect annotation.json schema [~0 tests]
DONE during spec phase. Key findings:
- segments[].phase: string e.g. "approach_object", "place_object", "unlabeled"
- segments[].reviewed: bool
- segments[].verb, .object, .target: strings or null
- label_diversity = distinct phase values per episode

### Slice 2 — Backend reader module [~8 tests]

**File:** `mimicanno/server/dataset_summary.py`
**Test:** `tests/server/test_dataset_summary.py` (reader section)

Steps:
1. Write failing tests for compute_summary (happy, empty, malformed, stats math)
2. Implement compute_summary:
   a. Parse info.json for ep_count
   b. Discover run_sets (reuse catalog.py pattern)
   c. Resolve run_set (param or most-recent by index.json mtime)
   d. Load index.json → (episode_id → canonical) mapping
   e. Read each canonical's annotation.json (best-effort, skip on error)
   f. Aggregate: phase counts, segment counts, reviewed counts
   g. Compute stats and build response dict
3. Run tests, iterate

### Slice 3 — Backend route [~4 tests]

**File:** `mimicanno/server/catalog_routes.py` (new route inside make_catalog_router)
**Test:** `tests/server/test_dataset_summary.py` (route section)

Steps:
1. Write failing route tests
2. Add route to catalog_routes.py (before /api/datasets/{name} for safety)
3. Run tests

### Slice 4 — Frontend client [~2 tests]

**File:** `frontend/src/lib/datasetSummaryClient.ts`
**Test:** `frontend/src/lib/__tests__/datasetSummaryClient.test.ts`

Steps:
1. Write failing vitest tests
2. Implement client
3. Run tests

### Slice 5 — Frontend dashboard tab [~5 tests]

**File:** `frontend/src/pages/DatasetsPage.tsx`
**Test:** `frontend/src/__tests__/datasets-page-summary.test.tsx`

Steps:
1. Write failing vitest tests
2. Add SummaryTab component + state management + mock integration
3. Run tests

### Slice 6 — mypy + regression check

Run: `uv run mypy --strict mimicanno/`
Run: `uv run pytest tests/server/ -q`

### Slice 7 — Commit + push + PR

```
git add -f docs/superpowers/specs/2026-05-17-ua-2-dataset-summary-design.md
git add -f docs/superpowers/plans/2026-05-17-ua-2-dataset-summary-plan.md
git add mimicanno/server/dataset_summary.py
git add mimicanno/server/catalog_routes.py
git add tests/server/test_dataset_summary.py
git add frontend/src/lib/datasetSummaryClient.ts
git add frontend/src/lib/__tests__/datasetSummaryClient.test.ts
git add frontend/src/pages/DatasetsPage.tsx
git add frontend/src/__tests__/datasets-page-summary.test.tsx
git push -u origin feat/ua-2-dataset-summary
gh pr create ...
```
