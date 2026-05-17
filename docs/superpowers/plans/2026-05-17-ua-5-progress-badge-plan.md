# U-A5 — Progress badge implementation plan

Date: 2026-05-17
Spec: `docs/superpowers/specs/2026-05-17-ua-5-progress-badge-design.md`

## Steps

### Step 1 — jobsBadgeClient.ts

Create `frontend/src/lib/jobsBadgeClient.ts`:
- Export `fetchRunningCount(): Promise<number>`
- Calls `GET /api/jobs?status=running`; on error returns 0

Write tests at `frontend/src/lib/__tests__/jobsBadgeClient.test.ts` (2 cases).

### Step 2 — JobsBadge.tsx component

Create `frontend/src/components/JobsBadge.tsx`:
- `useEffect` → fetchRunningCount on mount + 4s interval
- count > 0: render anchor `data-testid="jobs-badge"` with text `N running` and `href="?page=jobs"`
- count === 0 or error: return null

Write tests at `frontend/src/components/__tests__/JobsBadge.test.tsx` (5 cases).

### Step 3 — App.tsx routing + header

Modify `frontend/src/App.tsx`:
- Read `params.get("page")` from URL
- Route `datasets` → `<DatasetsPage />`, `jobs` → `<JobsPage />`, else existing logic
- Wrap in `<div>` with header bar containing `<JobsBadge />`

Write App integration test at `frontend/src/__tests__/App.badge.test.tsx` (1 case).

### Step 4 — Verify

Run `cd frontend && npm test` and confirm all tests pass with 0 regressions.

### Step 5 — Spec + plan git add -f and commit

Commit in order:
1. `test(ua-5):` test files
2. `feat(ua-5):` implementation files
3. `docs(ua-5):` spec + plan (git add -f)

Push and open PR.
