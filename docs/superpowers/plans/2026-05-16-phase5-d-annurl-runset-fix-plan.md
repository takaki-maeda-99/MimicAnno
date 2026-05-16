# Phase 5 D — annUrl runSet propagation fix plan

**Branch:** `feat/phase5-d-eval-harness` (continuing)  
**Scope:** Complete the 86c29b3 fix — 2 annUrl sites in RunViewer.tsx still miss `+ runSetQs`.  
**Estimated:** 2 lines + 1 commit.

---

## Bug

`frontend/src/components/RunViewer.tsx` has 4 annotation-refetch sites that run after a successful PATCH (one per edit type: phase / boundary / reviewed / labels). All four must append `runSetQs` to the URL so the refetch hits the correct run-set namespace; otherwise non-default run-sets get 404 on refetch and the displayed annotation silently goes stale until the user reloads.

Commit 86c29b3 fixed 2 of the 4 sites (phase: line 183, labels: line 450) but missed:
- Line 295 — boundary refetch
- Line 364 — reviewed refetch

Working tree currently carries the uncommitted 2-line patch that fixes both.

## Failure mode

1. User selects a non-default run-set in the switcher → `runSet="so101_phase4_v5"` etc., `runSetQs="?run_set=so101_phase4_v5"`.
2. User performs a boundary drag or reviewed-toggle PATCH → 200, server updates correctly.
3. Frontend refetches `annotation.json` WITHOUT `?run_set=...` → server looks under `runs_root` directly (not the run-set subdir) → 404.
4. `fetchRetry` fails silently; the displayed annotation never refreshes with server-recomputed fields (e.g. `boundary_confidence` after a drag).

The PATCH itself succeeds, so persisted state is correct; only the UI goes stale. User-perceptible symptom: drag a boundary, table doesn't reflect server-recomputed confidence until next manual reload.

## Fix

Two edits to `frontend/src/components/RunViewer.tsx`:

```diff
@@ line 295 (boundary refetch)
           const annUrl = resolveUrl(
             data.manifestUrl,
             artifactUrl(newManifest, "annotation"),
-          );
+          ) + runSetQs;

@@ line 364 (reviewed refetch)
           const annUrl = resolveUrl(
             data.manifestUrl,
             artifactUrl(newManifest, "annotation"),
-          );
+          ) + runSetQs;
```

These edits are already present in the working tree (uncommitted). Just stage and commit.

## Test coverage

Existing tests cover the 4 PATCH clients' URL construction (`boundaryClient.test.ts`, `reviewedClient.test.ts` add `?run_set=` cases). The annotation refetch URL composition inside `RunViewer.tsx` is NOT unit-tested — it lives in a useEffect-bound onClick handler that requires DOM + React Testing Library setup.

**Decision:** do NOT add a new test for this fix.

Reasoning:
- The fix completes a known pattern (`+ runSetQs` everywhere external resources are fetched), already established by 86c29b3 at 2 sister sites — line 183 and 450 have no tests either.
- Adding a refetch-URL test requires mocking `fetchRetry` + setting up the post-PATCH effect; high setup cost for a one-line completion.
- A regression here would be caught by manual smoke in a non-default run-set.
- The pre-existing vitest suite is currently red (58 failures on D branch, all pre-existing per earlier review) so adding one more test under that condition has low signal.

If future D r2 work touches refetch logic, an integration-level test should cover all 4 sites together.

## Verification

1. Run `cd /misc/dl00/gayagaya/MimicAnno-phase5d && npx --prefix frontend vitest run frontend/src/lib/__tests__/boundaryClient.test.ts frontend/src/lib/__tests__/reviewedClient.test.ts -- --reporter=verbose` — sanity-check that the client-level run_set tests still pass.
2. Run `cd /misc/dl00/gayagaya/MimicAnno-phase5d && uv run pytest tests/server/ -q` — confirm backend unaffected (should be — pure frontend change).
3. Optional manual smoke (defer to merge-time smoke): SO101 v5 run-set, boundary drag → refetch URL in browser DevTools network tab includes `?run_set=so101_phase4_v5`.

## Commit message

```
fix(frontend): complete runSet propagation on boundary/reviewed annotation refetch

Commit 86c29b3 fixed run_set query-string propagation for the 4 PATCH
clients but missed 2 of 4 annotation-refetch sites inside RunViewer.tsx
(boundary refetch at line 295, reviewed refetch at line 364). The phase
and labels refetches were correctly fixed in that commit.

Without this, a PATCH boundary-drag or reviewed-toggle in a non-default
run-set succeeds but the subsequent annotation refetch hits the
no-run_set URL → 404 → silent stale UI (server-recomputed fields like
boundary_confidence not reflected until manual reload).

2 lines, no new tests — same pattern already established at sister
sites 183 and 450, none of which have URL-composition coverage.
```

## Out of scope

- Adding test coverage for the 4 annotation-refetch sites (D r2 candidate, integration-level)
- Fixing the pre-existing 58 vitest failures (unrelated to D)
- Adding eslint / static check to enforce `runSetQs` on all artifact-fetch URLs (D r2 candidate)
