# U-A2 — Dataset Summary — sub-project design

Date: 2026-05-17
Author: U-A2 sub-Claude
Parent: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (master rev3)
Branch: `feat/ua-2-dataset-summary`

## 0. Parent reference

This spec implements **master spec rev3 §3.2 + §2.2**. The frozen §2.2 HTTP contract
is reproduced verbatim below. This file contains only U-A2-owned decisions; do NOT
change master §2.

## 1. Scope

**In scope:**

- Backend reader module: `mimicanno/server/dataset_summary.py`
  - Scans a single run_set for this dataset's annotated episodes
  - Reads `annotation.json` from each canonical dir
  - Aggregates: `label_distribution`, `segment_count_stats`, `reviewed_rate`, `per_episode`
- Backend route: `GET /api/datasets/{name}/summary?run_set=<rs>`
  - Added to `mimicanno/server/catalog_routes.py` (new inner route in `make_catalog_router`)
  - Registered BEFORE the catch-all route in app.py (already the case, since it's part of catalog_router which is included first)
- Frontend API client: `frontend/src/lib/datasetSummaryClient.ts`
- Frontend dashboard tab: added to `frontend/src/pages/DatasetsPage.tsx`
  - Summary section rendered inline when a dataset row is expanded (below the episode table)
  - Run_set selector allows switching between available run_sets
  - Bar chart (simple HTML/CSS, no chart library) of label distribution
  - Per-episode stats table

**Out of scope:**

- Writes back to runs/ (read-only)
- Touching `/api/datasets` or `/api/datasets/{name}` (already shipped by U-A1)
- RunViewer / VideoPlayer / mask routes / VLM panel / jobs (other sub-projects)
- Listing available run_sets (the run_set selector uses data already in the episode table)

## 2. HTTP contract (frozen master §2.2, reproduced for reference)

```
GET /api/datasets/{name}/summary?run_set=<rs>   // run_set optional, defaults to most recent
→ 200 application/json
{
  "run_set": "so101_phase4_v5",
  "ep_count": 33,
  "annotated_ep_count": 17,
  "label_distribution": { "approach_object": 42, "grasp": 17, ... },
  "segment_count_stats": { "mean": 4.5, "min": 2, "max": 9 },
  "reviewed_rate": 0.18,
  "per_episode": [
    { "idx": 0, "canonical": "...", "segment_count": 5, "reviewed_count": 5, "label_diversity": 4 },
    ...
  ]
}
```

## 3. U-A2 semantic clarifications (not in master §2)

### 3.1 `annotated_ep_count` semantics in summary context

Master §2.0 defines `annotated_ep_count` in `/api/datasets` as the union across ALL run-sets.
In `/api/datasets/{name}/summary` (scoped to ONE run_set), `annotated_ep_count` is:
**the number of episodes within this run_set that have at least one canonical annotation**.
This is the count of entries in `index.json` for the chosen run_set (deduplicated by episode_id).

### 3.2 `label_diversity` definition

**`label_diversity` = number of distinct `phase` values in that episode's segments.**

Rationale:
- `phase` is the primary label for a manipulation segment (approach_object, grasp, place_object, etc.)
- `verb` and `object` are secondary/optional and often null (especially in degraded path)
- Distinct phases per episode gives the clearest read on how "varied" an episode is
- Unlabeled segments (phase="unlabeled") are counted as a distinct value (does NOT exclude them)

### 3.3 `label_distribution` definition

Key = segment `phase` value (string, e.g. "approach_object", "unlabeled").
Value = total count of segments with that phase across all annotated episodes in the run_set.

### 3.4 `segment_count_stats` definition

Stats computed over annotated episodes only (episodes that appear in `index.json`).
- `mean` = float (average segment count per annotated episode)
- `min` = int (minimum segment count in any annotated episode)
- `max` = int (maximum segment count in any annotated episode)
- If `annotated_ep_count == 0`: all three are 0 (not null).

### 3.5 `reviewed_rate` definition

Total reviewed segments / total segments across all annotated episodes in the run_set.
Float in [0.0, 1.0]. If no segments: 0.0.

### 3.6 `ep_count` in summary

`ep_count` = total episodes in the dataset (from `data/{name}/meta/info.json`), same as
reported by `/api/datasets`. NOT the run_set count.

### 3.7 Run_set resolution (most recent default)

When `run_set` query param is omitted: the run_set whose `index.json` has the **latest mtime**
is selected. `__legacy__` is eligible (its "index.json" is at `runs_root/index.json`).
If no run_sets exist at all → return 200 with empty data (ep_count from info.json, all
aggregates zeroed, per_episode=[]).

### 3.8 `per_episode` ordering

Sorted ascending by `idx` (episode index, parsed from episode_id).

### 3.9 `canonical` in per_episode

The canonical dir name for this episode in this run_set. If an episode has multiple
canonicals (re-runs within same run_set), use the one with the latest `generated_at`.

## 4. Architecture

### 4.1 Backend reader: `mimicanno/server/dataset_summary.py`

Key function:
```python
def compute_summary(
    dataset_name: str,
    data_root: Path,
    runs_root: Path,
    run_set: str | None = None,  # None → most recent
) -> dict[str, Any]:
    ...
```

Internal steps:
1. Read `data/{name}/meta/info.json` → `ep_count`
2. Resolve `run_set` (or find most recent by index.json mtime)
3. Load `index.json` for the run_set → list of (episode_id, canonical)
4. For each canonical, find and read `annotation.json`
5. Aggregate segment stats, reviewed counts, phase distribution
6. Build response dict

### 4.2 Backend route (in `catalog_routes.py`)

Added as a new inner function inside `make_catalog_router`:

```python
@router.get("/api/datasets/{name}/summary")
def get_dataset_summary(name: str, run_set: str | None = Query(default=None)) -> Response:
    ...
```

Must be registered before `GET /api/datasets/{name}` to prevent FastAPI route shadowing.
(FastAPI routes match first-wins; `/summary` as a literal segment after `{name}` won't shadow
`{name}` itself, but placing it higher in the router definition is safer.)

### 4.3 Frontend client: `frontend/src/lib/datasetSummaryClient.ts`

```typescript
export interface DatasetSummary { ... }
export async function fetchDatasetSummary(name: string, runSet?: string): Promise<DatasetSummary>
```

### 4.4 Frontend component: inline in `DatasetsPage.tsx`

Adds a "Summary" tab to the expanded dataset detail panel. The existing detail panel
shows episodes; clicking "Summary" tab shows:
- Run_set selector (dropdown of known run_sets from episode.runs[].run_set across all episodes)
- Label distribution bar chart (simple CSS bars, sorted descending by count)
- Per-episode stats table: idx, canonical (truncated), segment_count, reviewed_count, label_diversity

## 5. Test strategy

### 5.1 Backend: `tests/server/test_dataset_summary.py`

~11 tests:

**Reader module tests (directly test compute_summary):**
- `test_happy_path_aggregation` — 2 eps, known segments → assert all fields
- `test_empty_run_set` — run_set with 0 annotated eps → zeros
- `test_malformed_annotation_graceful` — annotation.json is invalid JSON → ep skipped
- `test_label_distribution_counts_phases` — verify phase-count aggregation
- `test_segment_count_stats_math` — mean/min/max correct
- `test_reviewed_rate_math` — fraction correct
- `test_per_episode_order` — sorted by idx ascending
- `test_most_recent_run_set_default` — 2 run_sets with different mtimes → picks latest

**Route tests (via TestClient):**
- `test_route_200_happy` — GET /api/datasets/{name}/summary → 200 + valid shape
- `test_route_default_run_set_most_recent` — no run_set param → most recent selected
- `test_route_404_dataset_unknown` — name not in data_root → 404
- `test_route_legacy_run_set` — run_set=__legacy__ works

### 5.2 Frontend: `frontend/src/lib/__tests__/datasetSummaryClient.test.ts`

~2 vitest cases:
- Happy path: mock fetch → assert parsed response
- Error: non-200 response → rejects with error message

### 5.3 Frontend: `frontend/src/__tests__/datasets-page-summary.test.tsx`

~5 vitest cases:
- Renders summary tab button in expanded dataset row
- Summary tab renders run_set selector
- Summary tab renders label distribution bars
- Summary tab renders per-ep table rows
- Empty state (no annotated eps) shows "No annotations"

## 6. Exit criteria

1. `GET /api/datasets/{name}/summary` returns §2.2 shape for SO101 (or any dataset with run data)
2. Backend tests pass (≥11 new tests)
3. Frontend summary tab renders bar chart + per-ep table
4. Frontend tests pass (≥7 new vitest cases)
5. `uv run mypy --strict mimicanno/` passes (no new errors)
6. Existing backend tests: no regression (5 pre-existing vlm_dumps failures are pre-existing, not ours)
7. PR opened against main; not merged.

## 7. Open risks

- Per-ep table performance for 100+ episodes: table is rendered as-is; no pagination. For
  typical MimicAnno datasets (< 500 eps), this is acceptable. Add pagination as a follow-up if needed.
- Run_set selector UX: we derive available run_sets from episode.runs in the detail response.
  If the user hasn't expanded the episode table yet, we have no run_set list. We trigger
  a summary fetch with no run_set (→ most recent) on tab click, then show run_sets from the
  summary response's `run_set` field alone. User can type a run_set manually if needed.
  Better UX (dropdown of all run_sets) would need a separate /api/datasets/{name}/run_sets endpoint.
- Label_distribution sort order: sorted descending by count in the frontend, alphabetical as tiebreak.

## 8. §2 contract changes proposed

None. `label_diversity` definition (distinct `phase` values per episode) is a U-A2-internal
decision documented here. It does not change the master §2.2 field names or shapes.
The master spec leaves `label_diversity` undefined; we define it here without requiring a spec freeze update.
