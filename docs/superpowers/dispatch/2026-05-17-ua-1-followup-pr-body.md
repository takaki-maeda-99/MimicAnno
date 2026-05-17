# U-A1 follow-up routing PR — manual creation

## URL

<https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-1-followup-routing>

Base: `main` / Compare: `feat/ua-1-followup-routing` (tip `0208f20`, includes `84034a9` routing commit)

## Title

```
feat(ua-1): wire ?page=datasets and ?page=jobs routing in App.tsx
```

## Body

```markdown
## Summary

Follow-up to U-A1 (PR #12). The original U-A1 shipped `DatasetsPage` and `JobsPage` components but `App.tsx` was not wired to surface them — both pages were orphaned and unreachable from the browser. This PR adds URL-param routing so they're accessible.

- Extended the existing `?run=` / `?hand=` / `?run_set=` URL-param dispatch with `?page=datasets` and `?page=jobs`.
- No new router library introduced (no `react-router-dom`). The convention matches `DatasetsPage.tsx`'s hardcoded `/?page=jobs` link.
- Priority order: `?hand=` > `?run=` > `?page=` > default `RunList`.
- Existing viewer URLs unaffected.

Touches master §2 contract: no

## Test plan

- [x] `cd frontend && npm test` — 141 vitest cases pass (was 136, +5 new in `app-routing.test.tsx`)
- [x] `?page=datasets` → DatasetsPage renders
- [x] `?page=jobs` → JobsPage renders
- [x] No `?page=` → RunList (default) renders
- [x] `?run=` alongside `?page=` → RunViewer wins per priority

## Known

- 7 pre-existing backend test failures on the original `feat/ua-1-catalog-jobs` base (`RunsRepository.read_merged_index` AttributeError). These predate this PR and are resolved by Phase 6's `read_merged_index` shipping in PR #13 (now on main). Rebase onto current main fixes them.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## After PR is created

Reply with the PR number to commander so TODO U-A1-followup status can be updated.
