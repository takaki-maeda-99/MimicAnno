# Phase 5 B r1 — UI smoke verification plan

**Date:** 2026-05-14
**Mode:** manual browser verification (no new feature code)
**Operator:** user (takaki) drives the browser; assistant captures findings and writes fix commits
**Test branch:** `smoke/all-pr-merged` (local-only, throwaway — never pushed; rebuilt by cherry-picking the three PR branches together so a single browser session can exercise everything that will exist post-merge)

Phase 5 B r1's automated coverage is complete (Python 1152 / frontend 54 / curl status-code matrix). What's missing is a browser-driven walk-through that verifies the optimistic edit loop *feels* right and exposes integration gaps between the three PRs that unit tests can't see (URL preservation, video MIME, dev proxy, focus / disabled / reload UX).

This plan is **verification only**. It does not introduce new spec scope. Any fix discovered during the walk-through is classified (§3) and routed to the appropriate PR branch (§4); it is NOT silently appended to the test branch.

---

## 1. Why a separate plan

After the user surfaced two bugs during ad-hoc smoke (`?api=1` getting dropped on navigation; video 404 over `/api`), it became clear the smoke phase deserves the same discipline as feature work:

- **Plan before action** — exit criteria stated up front, not invented mid-session.
- **Branch up front** — fixes go to pre-decided branches, not whichever branch happens to be checked out.
- **Findings recorded** — each interaction's expected vs. actual is written down so we can tell "tested and works" from "didn't test."

Without this, fixes accumulate on whichever branch the assistant typed `git commit` against and post-hoc scope-classification has to happen (which is what triggered the recent revert + 3-branch split).

## 2. Scope

In scope:
- Browser walk-through of every URL contract documented in `frontend/README.md`.
- `?api=1` mode happy path: load run list → click a row → ViewRunner renders → edit a phase → see persistence.
- `?api=1` mode error paths: 412 conflict (forced via two tabs), 415 (unreachable via UI by design), 400 invalid_label (unreachable via UI by design — dropdown is constrained to labelset), forced 5xx via mid-PATCH backend kill.
- Static mode (no `?api=1`) backward compatibility: regression check that the unmodified viewer still works for a `runs/index.json` that exists at repo root.
- **Server bugs surfaced through UI ARE in scope to fix** — routed per §4 (PR1 for Phase 5 A contract, PR2 for Phase 5 B r1 contract). What's out of scope is *new server features*, not bugs that the manual smoke happens to expose.

Out of scope (do NOT investigate during this smoke):
- r2+ features (boundary drag, reviewed toggle independent of phase, object/target edit, bulk, undo, object track switching).
- Phase 5 D / 5 E.
- *New* server-side capabilities or contract changes beyond fixing what r1 / 5 A already promise.
- Cross-browser / mobile (Chromium-class browser only).
- Auth, multi-user (Phase 6+).

## 3. Finding classification

Each finding gets exactly one tag:

| Tag | Meaning | Action |
|---|---|---|
| **BLOCKER** | r1's spec contract is wrong or unusable (e.g., PATCH 200 but cell doesn't update; 412 loop unbreakable). | Per exit criterion §6 #2: write reproduction + identify target PR (§4); fix-and-test inline if ≤ 1h, otherwise spawn a separate fix plan and leave smoke session for the user. r1 cannot ship until cleared. |
| **R1-FOLLOWUP** | r1 works but dev UX is broken (e.g., navigation drops `?api=1`, video MIME). | Fix on PR3 (`fix/phase5-b-r1-dev-followup`) or PR1 (`fix/phase5-a-video-streaming`) depending on subsystem. r1 still ships; the followup PR catches the gap. |
| **TEST-GAP** | Behaviour is correct but no automated test would have caught a regression. | Add a unit/integration test on the same PR that owns the behaviour (no code fix needed). Does not block r1 — but a finding tagged ONLY `TEST-GAP` is still actionable. |
| **DEFER-R2+** | Real issue, but outside r1 scope. (e.g., "can't move a boundary"). | Record in this plan only. Open as r2 spec input later. |
| **WAI** | Working-as-intended; the operator's mental model was off. | Record in this plan + clarify in README if the doc was ambiguous. |

A finding may carry multiple tags (e.g., `BLOCKER` + `TEST-GAP`) when the fix also exposes a missing test. The §4 routing applies to whichever tag(s) require a commit.

## 4. Branch routing

Pre-decided so the assistant doesn't have to ad-hoc judge mid-fix:

| Subsystem of the fix | Target PR / branch |
|---|---|
| Phase 5 A server contract (allow-list, MIME, headers) | **PR1** `fix/phase5-a-video-streaming` — additional commit |
| Phase 5 B r1 spec contract (PATCH semantics, optimistic locking, ETag handling, server-side validation) | **PR2** `feat/phase5-b-r1-relabel` — additional commit (a contract bug means the spec isn't met) |
| Phase 5 B r1 frontend behaviour bug (rollback, toast, disabled state, optimistic update) | **PR2** `feat/phase5-b-r1-relabel` — additional commit |
| Dev UX / nav / proxy / SPA routing | **PR3** `fix/phase5-b-r1-dev-followup` — additional commit |
| Anything outside the above (e.g., spec gap requiring new feature work) | Stop, open new spec/plan, do NOT add to existing PRs |

`smoke/all-pr-merged` receives commits **only for the purpose of testing the combined behaviour**. It is rebuilt from scratch each session as `git checkout fix/phase5-b-r1-dev-followup && git checkout -b smoke/all-pr-merged && git cherry-pick <video-streaming-tip>`. Any fix that lands on smoke/ must be cherry-picked / re-applied onto its proper PR branch before that PR branch is pushed. **`smoke/all-pr-merged` is never pushed; never the source of truth for any commit.**

## 5. Test matrix

Drive the browser through these interactions in order. Each row produces a finding (`OK` / `BLOCKER` / `R1-FOLLOWUP` / `DEFER-R2+` / `WAI`).

### 5.1 Navigation (the recently-broken path)

| # | Action | Expected | Tag |
|---|---|---|---|
| N1 | Open `http://localhost:5123/?api=1` | RunList renders ~39 rows for SO101 v5 | |
| N2 | Click episode_000000 row | URL becomes `?run=episode_000000&hash=<short>&api=1`; RunViewer loads | |
| N3 | Inspect the link's `href` in DevTools before clicking | `href` ends with `&api=1` (proves param is in the rendered anchor, not appended at click time) | |
| N4 | Open ep32 directly: `?run=episode_000032&hash=834aa84279bd&api=1` | RunViewer loads | |
| N5 | Drop `&api=1` from the same URL by hand → reload | Static mode error or works depending on `runs/index.json` at repo root. **Expected: 404 in this dev environment because the dev server has no repo-root index.json. Document as WAI.** | |
| N6 | From the RunList while in `?api=1`, right-click → "Open Link in New Tab" on an episode | The new tab opens with `&api=1` preserved | |
| N7 | When an episode has multiple runs, change the ChooserBanner dropdown | URL updates with new hash AND `&api=1` retained | |

### 5.2 Video playback (was code 4 before video.mp4 allow-list)

| # | Action | Expected | Tag |
|---|---|---|---|
| V1 | Open ep0 in `?api=1` mode | `<video>` element renders without "video playback failed (code N)" | |
| V2 | Hit play | Video plays at 30 fps, audio (or silence) doesn't block | |
| V3 | Seek to mid-clip | Server serves a Range: response; no full re-download | |
| V4 | Network tab: confirm video request | URL is `/api/runs/<name>/video.mp4`, status 200, `content-type: video/mp4` | |
| V5 | Open ep with degraded pipeline (manifest.pipeline_status.degraded_from_phase != null) | Banner shows + video still plays | |

### 5.3 Phase dropdown — happy path

| # | Action | Expected | Tag |
|---|---|---|---|
| D1 | Open ep0 in `?api=1` | SegmentTable appears below Timeline, dropdown column populated | |
| D2 | Compare dropdown options vs `curl /api/labelset` | All labels present, IDs match | |
| D3 | Change seg-000's phase from `approach_object` → `idle` | While PATCH in flight: every `<select>` disabled (incl. other rows). After 200: cell shows `idle`, `reviewed=✓`, `reviewer_id` cell shows the env value | |
| D4 | Refresh the page | Edit persists | |
| D5 | Change the same seg back to `approach_object` | Successive edits work; `smoothing_ops` still contains a single `edited` (deduped) | |
| D6 | Open a second segment, change its phase | Same flow; both edits land independently | |

### 5.4 Phase dropdown — error paths

| # | Action | Expected | Tag |
|---|---|---|---|
| E1 | Open the same run in two tabs both with `?api=1` | Both render fine | |
| E2 | In tab A, change seg-000 → wait for green state | Tab A reflects new state | |
| E3 | In tab B (still showing the old `run_hash`), change seg-001 | PATCH from tab B fires with stale `If-Match` → 412. Tab B: cell rolls back, alert toast contains `etag_mismatch:`, every `<select>` disabled, `reload` button present | |
| E4 | Click `reload` in tab B | Page reloads; new `run_hash` adopted; selects re-enabled | |
| E5 | Try editing during `editInFlight` (rapid double-click on a different select while first PATCH pending) | Second select is disabled — no second PATCH fires | |
| E6 | Kill the backend mid-PATCH (`kill <be.pid>` and immediately change a select) | Error toast appears (network/timeout); selects re-enabled (finally clause); state is consistent. **After E6: restart backend before any further test row.** | |
| E7 | **Forced 5xx (server-side error code propagation, spec §3.5):** corrupt `manifest.json` for the open run (e.g., truncate the file mid-JSON) so the next PATCH triggers an internal server error with the `{error: "internal", message: …}` envelope, then change a select. Confirm the toast displays `"internal: <message>"` (or whichever code the server emits) — the assertion is specifically that the server's `error` field surfaces verbatim in the toast, NOT that an error toast appears. **A timeout-only test (e.g., `kill -STOP`) does NOT count: it never carries the server envelope and would conflate with E6.** Restore the file before continuing. | |

### 5.5 Static mode regression

| # | Action | Expected | Tag |
|---|---|---|---|
| S1 | Generate a temp `runs/index.json` at repo root: `cp runs/so101_phase4_v5/index.json runs/index.json` and adjust manifest URLs OR mount a real run at `runs/<name>/` | Static viewer should at least load | |
| S2 | Open `http://localhost:5123/` (no `?api=1`) | Static viewer renders; no PATCH UI; no dropdown | |
| S3 | Confirm no `/api` requests in Network tab | Static mode is fully offline-of-server | |

(S1 might require fixture setup that exceeds smoke scope. If unfeasible without writing setup code, mark the entire 5.5 group as DEFER-R2+ "regression covered by 27 existing unit tests")

## 6. Exit criteria

This smoke phase exits when **all of**:

1. Every row in §5.1–§5.4 has a tag (no "skipped" rows). §5.5 may be a single combined deferral.
2. Every `BLOCKER` finding has:
   - **2a (always):** a written reproduction (paste the steps + observed behaviour into the Findings Summary §end) AND an identified target PR branch (§4).
   - **2b (in-session if cheap):** a commit on the target PR branch fixing it, with a test added to the relevant test file. Applies when scope is bounded — concretely, when (i) the operator believes the fix is ≤ 1 hour of work AND (ii) the fix doesn't require new spec discussion. Otherwise, **stop the smoke session for this BLOCKER**, leave the reproduction in §end, and spawn a separate fix plan (`docs/superpowers/plans/2026-05-14-phase5-b-r1-blocker-<topic>-plan.md`) per the standard plan-before-implement discipline.
3. Every `R1-FOLLOWUP` finding has a commit on PR1 or PR3 as appropriate; same fix-and-test discipline applies, but a R1-FOLLOWUP exceeding the in-session budget can stay open as a new branch-tracked task without blocking r1.
4. Every `DEFER-R2+` finding has one paragraph in this plan describing the deferred work.
5. Every `TEST-GAP` finding has either (a) a commit adding the test on its owning PR branch, or (b) one line in §end stating "test added in follow-up" plus a tracking issue / file path noted.
6. A summary section is appended to this plan with the final tag tally and the commit SHAs for any fixes that landed.

Re-running `cd frontend && pnpm test && pnpm build` plus `uv run --extra server pytest tests/server -q` produces green at the end of the session on every branch that received a commit.

## 7. Operator handoff at end

After this plan exits:
1. Force-push the PR branches that received fix commits (`git push --force-with-lease`).
2. Delete `smoke/all-pr-merged` locally.
3. Append a Findings Summary to this plan (overwritten by assistant at end of session).
4. Hand back to user with the tally + next-step recommendation (merge order).

## 8. Risks

| Risk | Mitigation |
|------|-----------|
| Operator and assistant diverge on what counts as `BLOCKER` vs `R1-FOLLOWUP` | The router table in §4 is the tiebreaker. If a finding doesn't fit any row, the assistant stops and asks. |
| Assistant accidentally commits a fix on `smoke/all-pr-merged` and forgets to re-apply on the proper PR branch | Before declaring done, run BOTH (a) `git log <PR-branch>..smoke/all-pr-merged --oneline` to catch SHA mismatches AND (b) `git cherry -v <PR-branch> smoke/all-pr-merged` to catch patch-equivalence drift (e.g., if a commit was squashed or its message edited). Cherry's `+` prefix marks commits unique to smoke/. |
| User does another N-tab interaction the matrix doesn't cover and finds a surprise | The matrix is a floor, not a ceiling. Add a row, tag it, fix or defer. |
| 412 path requires two tabs and an SSH tunnel — fragile | Pre-flight test that both tabs see `?api=1`. If tunnel drops mid-test, restart and resume from §5.4 only. |
| **Vite HMR / stale module state causes false-positive BLOCKER** | Before tagging any §5.3 or §5.4 row as `BLOCKER`, hard-reload both tabs (`Ctrl+Shift+R` / `Cmd+Shift+R`) and re-run the row. If the symptom disappears, retag as `WAI` and note "HMR stale-state false alarm." Same applies after editing any frontend file mid-session. |
| **Backend process state drift between tests (E6 kills the backend)** | E6 explicitly requires restarting the backend before E7 / D-row repeats. Before each §5.x section, verify `curl -fsS http://127.0.0.1:8765/healthz | grep -q ok` returns 0. If not, restart with the documented command before continuing. |
| Time sink on §5.5 (static-mode regression) — needs fixture setup | Allowed deferral: §5.5 may be marked DEFER-R2+ in one line if it requires creating a synthetic index.json. Unit tests + 5423467 commit's app/RunList tests cover static-mode wiring at the code level. |

---

## Findings Summary

**Session dates:** 2026-05-14 → 2026-05-15
**Operator:** takaki (browser), assistant (capture + fixes)
**Test branch:** `smoke/all-pr-merged` (deleted at session end)

### Tag tally

| Tag | Count | Notes |
|---|---|---|
| **OK / WAI** | 13 | §5.1 N1-N6, §5.2 V1-V4, §5.3 D1-D6 (after fixes), §5.4 E1-E4 (after fixes), §5.4 E5/E6 (WAI) |
| **BLOCKER** | 4 | All four fixed in-session per exit criterion §6 #2b (≤ 1h, no spec discussion required) |
| **R1-FOLLOWUP** | 1 | Back link |
| **TEST-GAP** | 1 | Closed by added unit test |
| **DEFER-R2+** | 1 | §5.5 static-mode regression (per §8 risk allowance — needs synthetic `runs/index.json` fixture) |
| **skip** | 2 | N7 (no multi-run episode), V5 (no degraded-pipeline episode) |

### BLOCKER findings + fixes

| # | Finding | Root cause | Target PR | Fix commit |
|---|---|---|---|---|
| **V1 (initial)** | `?api=1` mode video failed (code 4) — `<video src>` got 404 because `/api/runs/<name>/video.mp4` wasn't in the artifact allow-list | Phase 5 A contract written before Phase 5 B r1's `?api=1` toggle; video was static-only by design | PR1 `fix/phase5-a-video-streaming` | `3df4361` — add `"video.mp4"` to `ARTIFACT_ALLOWLIST`, suffix-based `media_type` in routes.py |
| **D4** | After successful PATCH, reload of the same URL → "no run for episode_id=X hash=<old>" because URL bar still carried the pre-edit short hash while `index.json` got rewritten | Frontend updated `manifest.run_hash` in state but never touched `window.location` | PR2 `feat/phase5-b-r1-relabel` | `2b71741` — `history.replaceState` rewrites `?hash` after 200, no history entry pushed so browser back still works |
| **E4** | After 412 in tab B, the "reload" button hit the same "no run for hash=<stale>" error because it called `window.location.reload()` with the stale `?hash` still in the URL | `staleRun` by definition = hash is behind; reload should drop the hash and let selectRun fall back to latest | PR2 `feat/phase5-b-r1-relabel` | `9944b44` — reload button strips `?hash` and navigates to the URL without it |
| **E7** | Toast on generic 5xx was `"HTTP 500: <message>"` instead of `"<error_code>: <message>"`, violating spec §3.5 ("toast must surface the server's `error` code") | The `kind:"error"` branch in `onPhaseEdit` formatted differently from the 412 / 400 / 404 branches | PR2 `feat/phase5-b-r1-relabel` | `8ab858d` — toast prefix uses `errorCode` when non-null, falls back to `HTTP <status>` only when the envelope is missing |

Verified manually with `internal: unexpected error` toast after corrupting `ep32/manifest.json` (restored immediately).

### R1-FOLLOWUP findings + fixes

| # | Finding | Target PR | Fix commit |
|---|---|---|---|
| §5.1 N2 follow-up | Browser back works but there's no in-page "back to run list" cue | PR3 `fix/phase5-b-r1-dev-followup` | `22053cd` — RunViewer renders `← runs` link at top, also preserving `?api=1` |

### TEST-GAP findings + closures

| # | Finding | Closure |
|---|---|---|
| E6 (deferred from manual) | No automated test covered "fetch rejects → editInFlight clears in finally + error toast appears" | Added an integration test in `RunViewer.integration.test.tsx` mocking `fetch` to reject, asserting toast text + select re-enable — shipped with `8ab858d` |

### WAI findings

| # | Finding | Justification |
|---|---|---|
| N5 | `/?run=...&hash=...` without `&api=1` shows "runs/index.json not reachable (HTTP 404)" in this dev environment | Repo root has no `runs/index.json`; static viewer was always served against a per-project `runs/` containing one. Documented as `?api=1` mode being mandatory for `runs/so101_phase4_v5/` style serving. |
| E5 | Rapid-fire double-edit fundamentally not manually testable on localhost (PATCH round trip ≪ human click interval) | Covered by existing `SegmentTable.test.tsx` "disables all selects while editInFlight=true (self-ETag race guard)". |

### DEFER-R2+

§5.5 (static-mode regression) — would require creating a synthetic `runs/index.json` at repo root and tracking down a static run dir to point at. Static-mode rendering is wholly covered by the 27 pre-existing unit/component tests on the static path (RunList, RunViewer's static branch in `RunViewer.integration.test.tsx`), so manual regression has no incremental signal. If a future PR refactors the URL plumbing, re-running the §5.1 navigation rows is sufficient.

### Branch routing audit (per §8 risk mitigation)

Final state at session end:

```
git cherry -v feat/phase5-b-r1-relabel smoke/all-pr-merged
+ <PR3's vite proxy>          (lives on PR3, not r1 — correct)
+ <PR3's preserve ?api=1 nav> (lives on PR3, not r1 — correct)
+ <PR3's back link>           (lives on PR3, not r1 — correct)
+ <PR1's video allow-list>    (lives on PR1, not r1 — correct)
- <r1's replaceState URL>     (patch-equivalent to PR2's 2b71741)
- <r1's reload strips hash>   (patch-equivalent to PR2's 9944b44)
- <r1's toast prefix>         (patch-equivalent to PR2's 8ab858d)
```

All BLOCKER fixes were correctly mirrored to PR2 (`feat/phase5-b-r1-relabel`) before session end. One near-miss caught: the toast-prefix fix initially landed only on `smoke/all-pr-merged`; the `git log <PR>..smoke` check from §8 caught it within minutes and it was cherry-picked back to PR2 as `8ab858d`. The `git cherry -v` augmentation added to §8 in the re-review pass would have caught the same case faster.

### Test totals at session end

- `feat/phase5-b-r1-relabel`: **59 frontend tests passing** (was 54 at start of smoke session; +5 for the three BLOCKER fixes' integration tests).
- `fix/phase5-b-r1-dev-followup`: 55 + 1 = **56** at the time of the back-link commit; will need a rebase onto post-merge `main` (which carries PR2's 5 new tests) for a final total of ~60.
- `fix/phase5-a-video-streaming`: 43 backend tests passing on its branch alone (no frontend impact).

### Trivia (carried over from session notes)

- **N4 URL space encoding**: the operator pasted `?ru   n=episode_000032&...` (with three literal spaces inside the param name) into the address bar and the page still loaded the right episode. Mechanism: the browser percent-encoded the spaces to `%20` so the actual request URL became `?ru%20%20%20n=episode_000032&...`. Vite ignored the `ru%20%20%20n=` param (no match for `run=`), so RunList rendered. RunList then ran with `episodeId=null` and showed the list view — the operator visually mistook this for "the episode loaded." Not a finding, but kept here so a future operator doesn't claim "spaces in URL work."

### Disk-state hygiene at session end

The user made several real-data edits on `runs/so101_phase4_v5/`. Final hashes at session end:
- `episode_000000__e35061106394`: run_hash = `sha256:1e099678cb86...` (edited)
- `episode_000032__834aa84279bd`: run_hash = `sha256:d528f2a48f8f...` (edited)
- `episode_000032/manifest.json` was corrupted in-session for E7 and restored before session end.

These edits are real and intended (matching the audit trail: `smoothing_ops: ["edited"]`, `reviewer_id: "takaki"`). If a future test suite that hard-codes the original auto-pipeline hashes runs (e.g., `tests/server/test_edit_short_circuit.py::test_edited_run_hash_disjoint_from_auto_pipeline_hash` — burned us earlier this session), revert via the same procedure as 2026-05-14 (restore each ep's `run_hash`, `phase`, `reviewed`, `reviewer_id`, `smoothing_ops`, plus the matching `index.json` entry). Or just regenerate via `mimicanno annotate`.

### Operator handoff per §7

1. ✅ All BLOCKER / R1-FOLLOWUP fixes pushed to their target PR branches (force-push needed once for PR2 since amended branch had been pushed earlier; safe because no reviewer has touched it yet).
2. `smoke/all-pr-merged` to be deleted locally at end of session.
3. Findings Summary written (this section).
4. **Next-step recommendation (merge order):**
   - **PR1** `fix/phase5-a-video-streaming` first (independent, smallest).
   - **PR2** `feat/phase5-b-r1-relabel` second (r1 contract + 3 in-smoke BLOCKER fixes).
   - **PR3** `fix/phase5-b-r1-dev-followup` last — rebase onto post-PR2 main first; this branch's back-link integration test will need its expected URL to match the URL produced by the now-on-r1 `replaceState` (no conflict expected since the test asserts on `← runs` href in static state, not post-PATCH state).
