# Phase 5 B r1 — T13 sub-plan: frontend phase dropdown + PATCH client

**Date:** 2026-05-14
**Branch:** `feat/phase5-b-r1-relabel`
**Prerequisites:** T1–T12 shipped (server PATCH route live; ApiToggleContext wired).
**Scope:** add a segment table beneath the Timeline that, in `?api=1` mode, lets a reviewer change a segment's `phase` via a `<select>` and persists it through the FastAPI PATCH endpoint with `If-Match` optimistic locking. Static-mode (`?api` absent) renders the same table read-only.

Out of scope (per spec §1.4 / r2+):
- Boundary drag editing
- `reviewed` toggle independent of phase change
- Object label editing
- Bulk multi-segment edits
- Undo / history navigation
- Object track switching

---

## 1. Decisions pinned (with rationale)

### 1.1 UI placement: new `<SegmentTable>` below `<Timeline>` inside `RunViewer`

- **Why not embed `<select>` inside Timeline's SVG `<g>`?** SVG-embedded form controls are awkward (`foreignObject` quirks, hit-testing pain). Timeline is a visualisation; segment editing is data work — they should be sibling components sharing state through props.
- **Why a table rather than a side panel?** 23 segments per SO101 ep0 fits comfortably in a vertical list; a panel would force segment selection state we don't need in r1.
- Columns: `#`, `segment_id` (short), `start–end (s)`, `phase` (select or text), `conf`, `reviewed` (✓/–), `source`.

### 1.2 Editability gating: `apiEnabled` from `useApiToggle()`

- When `apiEnabled === false`, the phase cell renders `<span>{phase}</span>` (no fetch, no PATCH). This keeps the static `?api` rollout safe — static viewer cannot accidentally try to PATCH a file:// URL.
- When `apiEnabled === true`, the phase cell renders `<select>` populated from the labelset cache (§1.4).

### 1.3 PATCH client: a single `patchSegmentPhase()` helper in `frontend/src/lib/editClient.ts`

Signature:
```ts
export type PatchResult =
  | { kind: "ok"; runHash: string; manifest: Manifest }
  | { kind: "conflict"; errorCode: string; serverMessage: string }   // 412
  | { kind: "invalid"; errorCode: string; serverMessage: string }    // 400 invalid_label / invalid_segment / invalid_body
  | { kind: "not_found"; errorCode: string; serverMessage: string }  // 404 run_not_found
  | { kind: "error"; httpStatus: number; errorCode: string | null; message: string };

export async function patchSegmentPhase(args: {
  apiBase: string;            // e.g. "/api/runs/"
  runName: string;            // canonical name from manifest URL path
  segmentId: string;
  newPhase: string;
  ifMatchRunHash: string;     // bare hash, helper adds the quotes
  signal?: AbortSignal;
}): Promise<PatchResult>;
```

- The helper wraps the quoting (`"sha256:..."`) so callers can't forget RFC 7232 quotes.
- Returns a tagged union — no thrown exceptions on HTTP failure; only thrown errors come from network/JSON-parse layer (caught by caller).
- **Reads the `ETag` header from a 200 response**, strips quotes, validates `sha256:` prefix, returns it as `runHash`.
- **Response body is the new MANIFEST** (per `routes.py:170-176`), not a segment. The helper returns it as `manifest: Manifest`. The CALLER (RunViewer) is responsible for re-fetching `annotation.json` to pick up the server-recomputed `overall_confidence` and the new `smoothing_ops`/`reviewer_id`/`reviewed` fields — we cannot derive `overall_confidence` client-side without duplicating the smoother formula. Re-fetch is one cheap round-trip (annotation.json is small; manifest just landed so it's hot in OS cache).
- All non-200 paths carry both the server's `error` code (stable, for tests + dev log) and `message` (human-readable, for toast UI).
- 400 sub-codes the server emits today (`routes.py` + `edit_repo.py`): `invalid_label`, `invalid_segment`, `invalid_body`. The client treats all three as `kind:"invalid"`; tests cover each.

### 1.4 Labelset fetch + cache: one-shot module-scoped Promise inside RunViewer effect

- `frontend/src/lib/labelsetClient.ts` exports `loadLabelset(apiBase: string): Promise<LabelSetDoc>` with **module-level memoisation keyed by `apiBase`** (a `Map<string, Promise<LabelSetDoc>>`).
- Cache is process-lifetime (no TTL on the client; the server already sets `Cache-Control: public, max-age=300`).
- `LabelSetDoc` type (snake_case on the wire AND on the TS type — no transformer needed):
  ```ts
  export interface LabelSetEntry { id: string; requires_object: boolean; }
  export interface LabelSetDoc { labels: LabelSetEntry[]; labels_yaml_sha256: string; }
  ```
- 404 from `/api/labelset` → return `{ kind: "error", ... }` so the table can render phase cells as **read-only** with a banner ("label catalog unavailable; edit disabled") rather than blowing up the whole page.

### 1.5 Local state update strategy: optimistic with rollback, **single in-flight edit at a time**

**Concurrency model:** at most ONE PATCH in flight at a time. While `editInFlight === true`, all `<select>` elements are disabled. This eliminates the self-ETag race: edit B cannot fire with edit A's old `run_hash` because B's `<select>` is disabled until A's response lands and `manifest.run_hash` is updated.

- Rejected alternative: per-edit queue / mutex — adds complexity for r1's ~23-segment use case; the user rarely edits faster than the ~50 ms round trip anyway.
- Rejected alternative: allow concurrent edits, retry on 412 with the new run_hash — auto-retry would silently re-apply an edit on top of unrelated changes the server made, which is exactly the optimistic-locking guarantee we want to preserve.

On `<select>` change:
1. Capture `oldPhase`, set `editInFlight = true` (disables ALL selects via prop), mark this row as `pending`.
2. Call `patchSegmentPhase()`.
3. On `ok`:
   - Update `manifest.run_hash` in RunViewer state to the value from the response's `ETag` header (so the next edit's `If-Match` uses the fresh hash).
   - Update the cached `manifest` to the server's returned manifest (covers `edited_at`, etc.).
   - **Re-fetch `annotation.json`** (server recomputed `overall_confidence` + appended `smoothing_ops:"edited"` + set `reviewed=true` + stamped `reviewer_id`; we cannot derive these client-side). On re-fetch success, replace the segments array. Re-fetch uses `fetchRetry` and is GET-idempotent so safe to retry.
   - Drop `editInFlight` and `pending`. **No toast on success.**
4. On `conflict` (412): rollback the cell to `oldPhase`, set `staleRun = true`, toast `"<error_code>: <message> — reload to continue"`. All selects stay disabled (staleRun is sticky until reload).
5. On `invalid` / `not_found` / `error`: rollback the cell, drop `editInFlight`, toast `"<error_code>: <message>"` (auto-dismisses after 5 s).

**Why optimistic-with-rollback rather than pessimistic-blocking?** The PATCH round trip is ~50 ms locally; making the user wait an explicit modal cycle is overkill. Rollback is trivial since we keep `oldPhase`. Pessimistic UI (modal "confirm change?") was considered and rejected as friction for the bulk-relabel workflow.

**Why one global `staleRun` flag rather than per-cell ETag?** The server-side run_hash is whole-run — a 412 on any segment means the entire annotation file is one revision ahead. Continuing to edit other segments would just trigger more 412s. The 23-segment-per-ep0 use case doesn't need cleverness here.

**Re-fetch failure handling:** if the annotation re-fetch after a successful PATCH fails (network blip), the local segment state is briefly stale but `manifest.run_hash` is fresh — the NEXT successful PATCH's re-fetch will reconcile. Toast `"sync warning: changes saved but local view may be stale"` and let the user continue.

### 1.6 Toast UX: minimal inline banner above the table, dismissable

- No third-party toast library — one `<div className="toast toast-{level}">` rendered at the top of `<SegmentTable>` when `toast !== null`.
- Auto-dismiss after 5 s for `error`/`invalid`; **no auto-dismiss for `conflict`** (the user needs to see and act on it — reload).
- A11y: `role="alert"` so screen readers announce it.

### 1.7 `runName` extraction

The server PATCH URL needs the canonical name (the directory under runs/). It's not in the annotation/manifest body — it's encoded in the URL. We already build `manifestUrl` via `resolveUrl(...)`. Extract `runName` by parsing the URL path:
```ts
function runNameFromManifestUrl(manifestUrl: string): string {
  // ".../api/runs/<name>/manifest.json" → "<name>"
  const u = new URL(manifestUrl);
  const m = u.pathname.match(/\/([^/]+)\/manifest\.json$/);
  if (!m) throw new Error(`cannot extract run name from ${u.pathname}`);
  return m[1];
}
```
- One unit test for this parser.

### 1.8 Reload-to-recover after 412

When `staleRun === true`, the table:
- disables all `<select>`s
- shows a persistent banner `"this view is stale — reload to continue editing"` with a `<button onClick={() => window.location.reload()}>reload</button>`

This is intentionally heavy-handed in r1. r2 may add live refresh.

---

## 2. Files touched

**New:**
- `frontend/src/lib/editClient.ts` — `patchSegmentPhase()` + `PatchResult` union
- `frontend/src/lib/labelsetClient.ts` — `loadLabelset()` + cache
- `frontend/src/components/SegmentTable.tsx` — table + dropdown + toast
- `frontend/src/lib/__tests__/editClient.test.ts` — PATCH client unit tests (T14 lands the 412 case here)
- `frontend/src/lib/__tests__/labelsetClient.test.ts` — cache test (T14)
- `frontend/src/components/__tests__/SegmentTable.test.tsx` — component tests (T14)

**Modified:**
- `frontend/src/components/RunViewer.tsx`
  - Add `<SegmentTable>` rendering when `annotation.kind === "ok"`
  - Add `staleRun` and `toast` state, plus an `onPhaseEdit(segmentId, newPhase, oldPhase)` callback that drives the optimistic flow
  - Update local segments state on PATCH success (immutable replace by `segment_id`)
  - Update local `manifest.run_hash` on PATCH success
- `frontend/src/lib/manifest.ts` — only if `Manifest` lacks an `edited_at` consumer; otherwise untouched
- `frontend/src/App.css` — minimal table + toast styles (kept under 30 lines)

**NOT modified (asserted):**
- Timeline.tsx (read-only consumer)
- WaveformView.tsx
- VideoPlayer.tsx
- Any backend file (T8–T11 are frozen)
- mimicanno/* (Python is frozen for T13)

---

## 3. TDD step order (each step ends with `pnpm test` green)

### T13.1 — `runNameFromManifestUrl` helper + unit test
- 4 cases: valid api path, valid static path, missing `/manifest.json`, missing leading slash → throws

### T13.2 — `patchSegmentPhase()` happy path
- vitest with mocked `fetch`. Assert request: method `PATCH`, URL `${apiBase}<name>/segments/<segmentId>`, headers `Content-Type: application/json`, `If-Match: "<run_hash>"`, body parsed as JSON equals `{"phase":"<new>"}` AND **`Object.keys(parsedBody).length === 1`** (server rejects extra keys per `routes.py` body validation).
- Mock 200 response with `ETag: "<new_hash>"` header + body = full Manifest object → result is `{kind:"ok", runHash: "<new_hash>" (quotes stripped), manifest: <body>}`. Helper validates the runHash starts with `sha256:`.

### T13.3 — `patchSegmentPhase()` 412 path
- Mock fetch returns 412 with body `{error:"etag_mismatch", message:"…"}` → result is `{kind:"conflict", errorCode:"etag_mismatch", serverMessage:"…"}`. No ETag header read (412 has no useful ETag).

### T13.4 — `patchSegmentPhase()` 400 / 404 paths (4 sub-cases)
- 400 `invalid_label` → `{kind:"invalid", errorCode:"invalid_label", serverMessage:…}`
- 400 `invalid_segment` → `{kind:"invalid", errorCode:"invalid_segment", …}`
- 400 `invalid_body` → `{kind:"invalid", errorCode:"invalid_body", …}`
- 404 `run_not_found` → `{kind:"not_found", errorCode:"run_not_found", …}`
- 500 (no envelope shape guaranteed) → `{kind:"error", httpStatus:500, errorCode:null, message:<best-effort>}`

### T13.5 — `loadLabelset()` + cache test
- First call: mock fetch responds 200 with `{labels:[...], labels_yaml_sha256:"…"}` → returns parsed.
- Second call with same `apiBase`: fetch is NOT called again (assert mock `callCount === 1`).
- Different `apiBase`: fetch called again.

### T13.6 — `SegmentTable` renders read-only in static mode
- Render with `apiEnabled=false`, 3 segments → 3 rows, phase cells are `<span>`, no `<select>` in DOM.

### T13.7 — `SegmentTable` renders dropdowns in api mode
- Render with `apiEnabled=true`, `labelset={labels:[{id:"idle",...},{id:"grasp_object",...}]}`, 3 segments → 3 `<select>`s, each with 2 `<option>`s, defaultValue matches segment phase.

### T13.8 — `SegmentTable` PATCH happy flow
- Render with mocked `onPhaseEdit` that resolves to `{kind:"ok", ...}`. User changes a `<select>`. Assert `onPhaseEdit` called once with `(segmentId, "grasp_object", "idle")`. Assert no toast appears.

### T13.9 — `SegmentTable` 412 flow → toast + stale state + rollback
- `onPhaseEdit` resolves to `{kind:"conflict", serverMessage:"…"}`. After settle:
  - The cell value is back to the old `phase` (rollback).
  - A `role="alert"` element contains "reload".
  - All `<select>` elements are disabled.
  - A `<button>reload</button>` is present.

### T13.10 — wire `<SegmentTable>` into `RunViewer`
- Add `<SegmentTable>` rendering, `staleRun`/`toast`/`editInFlight` state, the PATCH flow callback, and the post-success annotation re-fetch.

### T13.10.5 — RunViewer integration test (closes spec §5.3 #1 directly)
- Render `<RunViewer episodeId=... runHashShort=.../>` wrapped in `<ApiToggleProvider apiEnabled={true}>`. Mock `fetch` to return: index → manifest → annotation → labelset → (on PATCH) 200 with new manifest + new annotation re-fetch.
- User changes a `<select>` from `idle` to `grasp_object`.
- **Assert the captured PATCH request carries `If-Match: "<original_run_hash from manifest>"` and body `{"phase":"grasp_object"}`** — this proves the full end-to-end wiring (manifest → state → onPhaseEdit → patchSegmentPhase) carries the right ETag, not just the helper in isolation.
- Assert the post-PATCH annotation re-fetch was issued.

After T13.10.5: commit. T14 (formal spec §5.3 traceability) verifies the 3 spec §5.3 cases:
- §5.3 #1 (PATCH fires with right body+If-Match) → covered by T13.10.5 directly + T13.2 at the helper level
- §5.3 #2 (412 → toast + revert) → covered by T13.9
- §5.3 #3 (labelset fetch + cache) → covered by T13.5

---

## 4. Risk register

| Risk | Mitigation |
|------|-----------|
| React 19 strict-mode double-invocation triggers two PATCHes on one `<select>` change | onChange handlers don't run twice in strict mode (only effects do). Verified: no PATCH in an effect. |
| `<select>` controlled-vs-uncontrolled warning when we rollback after 412 | Use **controlled** `<select value={...}>` with state per-row. Rollback = setState(oldPhase). |
| AbortController on unmount cancels an in-flight PATCH after the server already committed | The server commit is atomic — if AbortController cancels the response, the edit still landed. The user just won't see the new `run_hash`. On next interaction we'd get a 412. We accept this and recover via the staleRun flag. |
| Labelset fetch races with first PATCH attempt | `<select>` doesn't render until labelset loads (suspense-style: show a skeleton row while `labelset.kind === "loading"`). PATCH only fires from a rendered `<select>` so the race is closed. |
| Module-scope cache leaks between tests | Tests import via dynamic `await import()` per-test and call `vi.resetModules()` in beforeEach, OR expose a `__resetLabelsetCacheForTests()` symbol guarded by `import.meta.env.MODE === "test"`. Pick the latter — clearer. |
| `runName` parser fails on URL with query string | `URL.pathname` excludes query string, so `?foo=bar` doesn't matter. Tests cover `?` and `#` suffixes. |
| 412 server message wording drift across r1 → r2 | Toast displays `"<error_code>: <message>"` — the `error` code is stable (server contract), `message` is human-readable. Client never hardcodes message strings; only the "reload to continue" suffix on conflict. |
| Quote-stripping mismatch (server sends `W/"…"` weak ETag) | The server never emits weak ETags on 200. If it ever did, our strip regex `/^W?\/?"(.+)"$/` would still extract the hash. Tests cover both. |
| **Self-ETag race on rapid edits to different segments** | At most ONE PATCH in flight at a time (§1.5): while `editInFlight === true`, all `<select>`s are disabled. Edit B cannot fire with edit A's stale `run_hash`. Tested in T13.10.5 by confirming the second `<select>` is disabled while the first PATCH is pending. |
| Annotation re-fetch after PATCH success races with another effect re-fetch | The re-fetch uses the same `AbortController` chain as the initial load (cancelled on unmount or episodeId change). Failure of the re-fetch leaves a sync warning toast but does not block further edits (next successful PATCH reconciles). |

---

## 5. Acceptance for T13 alone

- `pnpm test` green (32 → ~50+ tests).
- `pnpm build` clean (no new tsc errors).
- `?api=1` URL renders the table with editable dropdowns; static URL renders the same table read-only.
- A successful PATCH updates the cell in place without a page reload.
- A 412 (induced manually by reverting `manifest.run_hash` via a second tab) shows the toast + disables editing + offers reload.

T13 does NOT require running the server smoke — that's T16. T14 adds the 3 formal spec §5.3 vitest cases (already covered by T13.5/T13.8/T13.9 but T14 promotes them in the spec-traceability matrix).

---

## 6. Conventions reused (no new patterns introduced)

- `fetchRetry` for GET (labelset). PATCH does NOT retry (non-idempotent in the presence of optimistic locking — a retry could land after another editor's change and produce a misleading 412).
- `MimicAnnoHTTPError` envelope (`{error, message}`) matches server `errors.py`.
- Module-scoped Promise cache pattern is already used implicitly in browser DNS; not previously codified in this codebase but isomorphic to the `useRef` cache in `RunViewer`.
- Toast banner reuses existing `.error` styles + a `.toast` variant.
