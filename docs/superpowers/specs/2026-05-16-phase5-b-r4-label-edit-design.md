# Phase 5 B r4 — Label-field edit design

**Date:** 2026-05-16  
**Status:** SPEC

## Scope

Allow users to edit `verb`, `object`, `target`, and `failure_flags` on a segment without changing its `phase`. Complements r1 (phase relabel), r2 (boundary drag), r3 (reviewed toggle).

## Out of scope

- Editing `phase` (r1), boundaries (r2), reviewed flag (r3)
- Bulk edits
- Free-form `evidence` editing
- `label_version` bumping

---

## API

```
PATCH /api/runs/{name}/segments/{segment_id}/labels
Content-Type: application/json
If-Match: "<run_hash>"
Body: {"verb": str|null, "object": str|null, "target": str|null, "failure_flags": list[str]}
```

### Request

All four fields **required** in body (no partial update — simpler, avoids partial-update ambiguity). Validation:
- `failure_flags` must be `list[str]` (not string, not null)
- `verb`, `object`, `target` must be `str | null`
- Extra keys → 400 `invalid_body`

### Response

**200 OK** — same shape as r1/r2/r3: new manifest JSON + `ETag: "<new_run_hash>"` + `Cache-Control: no-cache`

**400 no_change** — all four values equal current → `{"error": "no_change", "message": "..."}`

**400 invalid_body** — body shape wrong

**400 invalid_segment** — segment_id not found

**404 run_not_found**

**412 etag_mismatch** — If-Match ≠ manifest.run_hash

**415 unsupported_media** — Content-Type ≠ application/json

**428 etag_required** — If-Match header absent

### Segment mutations

On 200:
- `verb`, `object`, `target`, `failure_flags` updated
- `label_source` → `"human_edit"` (when any field differs from current)
- `reviewed` → `True`
- `reviewer_id` → `reviewer` (server-side config value)

---

## Hash derivation

```python
preimage = (
    "edit:labels:"
    + old_run_hash
    + ":"
    + segment_id
    + ":"
    + (verb or "")
    + ":"
    + (object_ or "")
    + ":"
    + (target or "")
    + ":"
    + ",".join(sorted(failure_flags))
    + ":"
    + (reviewer or "")
)
new_run_hash = "sha256:" + sha256_hex_of_str(preimage)
```

`"edit:labels:"[5]` == `'l'` — disjoint from r3 (`'r'`), r2 (`'b'`), r1 (`':'`).

---

## Frontend

### labelsClient.ts

```typescript
export type LabelsPatchResult =
  | { kind: "ok"; runHash: string; manifest: Manifest }
  | { kind: "conflict"; errorCode: string; serverMessage: string }
  | { kind: "no_change"; serverMessage: string }
  | { kind: "invalid"; errorCode: string; serverMessage: string }
  | { kind: "error"; httpStatus: number; errorCode: string | null; message: string };

export async function patchLabels(args: {
  apiBase: string;
  runName: string;
  segmentId: string;
  verb: string | null;
  object: string | null;
  target: string | null;
  failure_flags: string[];
  ifMatchRunHash: string;
  signal?: AbortSignal;
  timeoutMs?: number;
}): Promise<LabelsPatchResult>
```

URL: `/api/runs/${encodeURIComponent(runName)}/segments/${encodeURIComponent(segmentId)}/labels`

### SegmentTable.tsx

New prop:
```typescript
onLabelsEdit: (
  segmentId: string,
  labels: { verb: string | null; object: string | null; target: string | null; failure_flags: string[] },
) => Promise<LabelsPatchResult>;
```

Columns added to header: `verb`, `object`, `target`, `flags`

SegmentRow local state:
- `localVerb`, `localObject`, `localTarget`, `localFlags` (optimistic)
- `useEffect` to sync from props when segment changes (same pattern as `localPhase`, `localReviewed`)

When editable:
- `<input type="text">` for verb, object, target
- `<input type="text">` for failure_flags (comma-separated display)
- **On blur only** (not on keystroke): compare to current prop value; if changed → call `onLabelsEdit`
- Rollback on non-ok result

When not editable:
- Static text or `"–"` for null

### RunViewer.tsx

- `labelsPatchInFlight` state
- `onLabelsEdit` handler (same pattern as `onReviewedToggle`)
  - 200: update manifest + refetch annotation
  - 412: setStaleRun + toast
  - no_change: silent (no toast)
- Include `labelsPatchInFlight` in combined `editInFlight` passed to SegmentTable + TimelineRuler

---

## Tests

### Backend (tests/server/test_routes_patch_labels.py)

| # | Test | Expected |
|---|------|----------|
| 1 | 200 happy path: change verb | disk: verb updated, label_source="human_edit", reviewed=True, reviewer_id |
| 2 | 200: set all null + empty failure_flags | disk updated |
| 3 | 400 no_change: send same values as current | disk unchanged |
| 4 | 400 invalid_body: missing `verb` key | disk unchanged |
| 5 | 400 invalid_body: failure_flags is string | disk unchanged |
| 6 | 400 invalid_segment: unknown segment_id | disk unchanged |
| 7 | 404 run_not_found | |
| 8 | 412 etag_mismatch | disk unchanged |
| 9 | 415 unsupported_media | disk unchanged |
| 10 | 428 precondition_required | disk unchanged |
| 11 | hash disjoint: byte[5]='l' | |

### Frontend (frontend/src/__tests__/labels-edit.test.tsx)

| # | Test |
|---|------|
| 1 | blur with changed value → onLabelsEdit called |
| 2 | no change on blur → onLabelsEdit NOT called |
| 3 | editable=false → no inputs, static text |
| 4 | RunViewer 412 → conflict toast |
| 5 | no_change result → rollback |
