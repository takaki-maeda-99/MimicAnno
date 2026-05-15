# Phase 5 B r3 — Reviewed Toggle: Ship Results (2026-05-16)

## Summary

B r3 (reviewed フラグ単独トグル) を 2026-05-16 に main マージ・スモーク完了。

## What shipped

### Backend

| File | 内容 |
|------|------|
| `mimicanno/server/reviewed_repo.py` | `patch_reviewed` + `derive_reviewed_run_hash` |
| `mimicanno/server/routes.py` | `PATCH /api/runs/{name}/segments/{segment_id}/reviewed` 追加 |

### Frontend

| File | 内容 |
|------|------|
| `frontend/src/lib/reviewedClient.ts` | `patchReviewed` + `ReviewedPatchResult` union |
| `frontend/src/components/SegmentTable.tsx` | `reviewed` 列 → editable 時は `<input type="checkbox">` |
| `frontend/src/components/RunViewer.tsx` | `onReviewedToggle` handler + `reviewedPatchInFlight` state |

### Tests

- `tests/server/test_routes_patch_reviewed.py` — 11 tests
- `frontend/src/__tests__/reviewed-toggle.test.tsx` — 5 vitest

### Fixture fixes (side effect of T16 smoke)

T16 smoke が fixture ソース (`runs/so101_phase4_v5/episode_000000__*`) を書き換えたことで
既存テストが壊れていた。以下を修正:

- `tests/server/conftest.py`: fixture 構築時に `run_hash` を `compose_run_hash` で正規化
  → `test_edit_short_circuit` の auto-pipeline invariant を常に保証
- `test_routes_patch_boundary.py`: 境界フレーム定数を現状に合わせる (20→25, 49→54 等)
- `test_boundary_patch_concurrent.py`: concurrent race の frame を noop でない値に変更

## Hash space

```
"edit:reviewed:" → byte[5] = 'r'
"edit:boundary:" → byte[5] = 'b'
"edit:"          → 5 chars only (r1)
auto-pipeline    → no "edit:" prefix
```

## T12 Smoke results (2026-05-16)

- `PATCH seg0004 reviewed=True` → 200 ✓
- `PATCH seg0004 reviewed=False` → 200 ✓ (`reviewer_id` = None に戻る)
- `PATCH seg0004 reviewed=False` (no_change) → 400 `no_change` ✓

## Test counts at merge

- Python: 1242 passed, 6 skipped
- Vitest: 104 passed
