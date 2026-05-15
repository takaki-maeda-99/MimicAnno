# Phase 5 B r4 — Label-field edit implementation plan

**Date:** 2026-05-16  
**Status:** PLAN

## Tasks

| # | Task | File(s) | Status |
|---|------|---------|--------|
| T1 | Branch | — | TODO |
| T2 | `labels_repo.py` | `mimicanno/server/labels_repo.py` | TODO |
| T3 | Route | `mimicanno/server/routes.py` | TODO |
| T4 | `labelsClient.ts` | `frontend/src/lib/labelsClient.ts` | TODO |
| T5 | `SegmentTable.tsx` | `frontend/src/components/SegmentTable.tsx` | TODO |
| T6 | `RunViewer.tsx` | `frontend/src/components/RunViewer.tsx` | TODO |
| T7 | Backend tests | `tests/server/test_routes_patch_labels.py` | TODO |
| T8 | Vitest tests | `frontend/src/__tests__/labels-edit.test.tsx` | TODO |
| T9 | All tests green | — | TODO |
| T10 | Gate | — | TODO |
| T11 | Commit + merge | — | TODO |
| T12 | Smoke test | — | TODO |
| T13 | Docs + memory | — | TODO |

## T2 — labels_repo.py

Follow `reviewed_repo.py` exactly.

```python
class LabelsNoChange(Exception): ...

def derive_labels_run_hash(old_rh, seg_id, verb, object_, target, failure_flags, reviewer) -> str:
    preimage = "edit:labels:" + old_rh + ":" + seg_id + ":" + (verb or "") + ":" + (object_ or "") + ":" + (target or "") + ":" + ",".join(sorted(failure_flags)) + ":" + (reviewer or "")
    return "sha256:" + sha256_hex_of_str(preimage)

def patch_labels(*, runs_root, name, segment_id, verb, object_, target, failure_flags, if_match, reviewer) -> dict:
    # Lock → load → no-op check → mutate → write
```

## T3 — routes.py

Add `PATCH /api/runs/{name}/segments/{segment_id}/labels` **before** `PATCH /api/runs/{name}/segments/{segment_id}`.

Body shape check: `{"verb": str|None, "object": str|None, "target": str|None, "failure_flags": list[str]}` — extra keys → 400 invalid_body.

## T4 — labelsClient.ts

Clone of `reviewedClient.ts` with:
- URL: `.../segments/{segmentId}/labels`
- Body: `JSON.stringify({ verb, object, target, failure_flags })`
- `LabelsPatchResult` type

## T5 — SegmentTable.tsx

- New prop `onLabelsEdit`
- New columns in header
- Local state: localVerb, localObject, localTarget, localFlags with useEffect sync
- onBlur handlers that only fire if value changed
- failure_flags: join with ", " for display, split on blur

## T6 — RunViewer.tsx

- Import `patchLabels`
- `labelsPatchInFlight` state
- `onLabelsEdit` handler
- Pass to SegmentTable + include in combined in-flight
