# U-A5 — Site-wide progress badge design

Date: 2026-05-17
Author: U-A5 sub-Claude
Parent spec: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` §3.5 + §2.3

## 0. Goal

Add a persistent header badge visible across all app pages that shows the current count of running annotation jobs.  Clicking the badge navigates to the Jobs page (`?page=jobs`).  When no jobs are running the badge is hidden.

## 1. Scope

**In scope:**
- `frontend/src/components/JobsBadge.tsx` — polling badge component
- `frontend/src/lib/jobsBadgeClient.ts` — thin fetcher for running-job count
- App.tsx — mount badge in header, wire `?page=` routing so DatasetsPage and JobsPage are reachable

**Out of scope:**
- Modifying the `/api/jobs` endpoint (U-A1 territory, already shipped)
- JobsPage / DatasetsPage body changes
- Error toasts, richer notifications
- RunViewer, VideoPlayer, mask routes (other sub-projects)

## 2. HTTP contract (frozen, §2.3 of master spec)

```
GET /api/jobs?status=running
→ 200 application/json  [JobSummary, ...]
```

The badge calls this endpoint, counts the array length, and displays N if N > 0.

No contract changes needed.  §2 contract changes proposed: **none**.

## 3. Component design

### `jobsBadgeClient.ts`

```typescript
fetchRunningCount(): Promise<number>
```

Calls `GET /api/jobs?status=running`, returns `data.length`.  On error returns 0 (fail-silent; badge just hides rather than showing an error).

### `JobsBadge.tsx`

Props: none (self-contained).

Behaviour:
- On mount, calls `fetchRunningCount()` immediately.
- Sets up a `setInterval` (~4 s) to re-poll.
- Clears interval on unmount.
- If count > 0: renders `<a href="?page=jobs" data-testid="jobs-badge">N running</a>` styled as a pill badge.
- If count === 0 or fetch error: renders nothing (`null`).

### App.tsx routing extension

Current URL routing uses `?run=`, `?hand=`, `?run_set=`, `?api=` params.  
Add `?page=` routing:

| `?page=` | Component shown |
|----------|-----------------|
| `datasets` | `<DatasetsPage />` |
| `jobs`     | `<JobsPage />`     |
| _(any other / absent)_ | existing logic (`RunList` / `RunViewer` / `HandViewer`) |

Header chrome wraps the active page and always renders `<JobsBadge />` in a top bar.

## 4. TDD slices (8 vitest cases)

### Slice 1 — `jobsBadgeClient.ts` (2 cases)
- Fetch success → returns correct count
- Fetch error → returns 0

### Slice 2 — `JobsBadge.tsx` (5 cases)
- Initial render shows nothing until fetch resolves
- Fetch returns N > 0 → badge visible with "N running" text
- Fetch returns 0 → badge hidden
- Fetch error → badge hidden (fail-silent)
- Click badge → href is `?page=jobs`

### Slice 3 — App integration (1 case)
- App renders with `?page=jobs` (mocked `JobsPage`) — badge is present in DOM

## 5. Exit criteria

- All 8 new vitest cases pass
- Existing tests continue to pass (no regression)
- No §2 contract changes
- Branch pushed, PR opened
