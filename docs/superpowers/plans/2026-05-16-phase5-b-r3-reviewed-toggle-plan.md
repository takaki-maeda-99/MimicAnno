# Phase 5 B r3 — Reviewed Toggle: Implementation Plan

**Date:** 2026-05-16  
**Spec:** `docs/superpowers/specs/2026-05-16-phase5-b-r3-reviewed-toggle-design.md`  
**Branch:** `feat/phase5-b-r3-reviewed-toggle`

---

## タスク一覧

### T1 — Branch 作成
- `git checkout -b feat/phase5-b-r3-reviewed-toggle`

### T2 — `reviewed_repo.py` 新規作成
- `derive_reviewed_run_hash(old_run_hash, segment_id, reviewed, reviewer) -> str`
  - preimage: `"edit:reviewed:" + old + ":" + seg_id + ":" + str(reviewed).lower() + ":" + (reviewer or "")`
- `class ReviewedNoChange(Exception): pass`
- `patch_reviewed(*, runs_root, name, segment_id, reviewed, if_match, reviewer) -> dict`
  - `file_lock` → load annotation/manifest → `EtagMismatch` check → find seg →
  - `ReviewedNoChange` if seg.reviewed == reviewed → mutate → `write_run_atomically`
  - `seg.reviewer_id = reviewer if reviewed else None`

### T3 — `routes.py` — reviewed PATCH ルート追加
- `PATCH /api/runs/{name}/segments/{segment_id}/reviewed` を r1 ルートの直前に追加
- CT check (415), If-Match check (428), body `{"reviewed": bool}` (400 invalid_body)
- `asyncio.to_thread(patch_reviewed, ...)` 呼び出し
- 例外マッピング: `ReviewedNoChange` → 400 `no_change`、`InvalidSegment` → 400 `invalid_segment`、`EtagMismatch` → 412、`RunNotFound` → 404

### T4 — `reviewedClient.ts` 新規作成
- `ReviewedPatchResult` union type (ok / conflict / no_change / invalid / error)
- `patchReviewed(args) -> Promise<ReviewedPatchResult>`
- URL: `${apiBase}/api/runs/${encodeURIComponent(runName)}/segments/${encodeURIComponent(segmentId)}/reviewed`
- 10s timeout (AbortController)

### T5 — `SegmentTable.tsx` 更新
- `SegmentTableProps` に `onReviewedToggle` を追加 (optional — editable=false 時は省略可)
- `SegmentRow` props に追加: `onReviewedToggle`
- `localReviewed` state + `useEffect` で segment.reviewed 変化に追従
- `reviewed` セル: editable && onReviewedToggle あり → `<input type="checkbox">` / else → "✓"/"–"
- `handleToggle`: optimistic 反転 → await → non-ok なら戻す

### T6 — `RunViewer.tsx` 更新
- `import { patchReviewed } from "../lib/reviewedClient"`
- `reviewedPatchInFlight` state
- `onReviewedToggle` ハンドラ (r1 の `onPhaseEdit` と同パターン)
  - 200 → manifest 更新 + annotation 再取得
  - 412 → setStaleRun conflict toast
- `<SegmentTable ... onReviewedToggle={onReviewedToggle} />`
- `editInFlight={editInFlight || boundaryPatchInFlight || reviewedPatchInFlight}`

### T7 — Backend tests: `test_routes_patch_reviewed.py`
- 11 テスト (spec §6.1 + hash disjoint)
- fixture: `tmp_runs_root_loadable` (既存共用 fixture)

### T8 — Frontend vitest: `reviewed-toggle.test.tsx`
- 5 テスト (spec §6.2)
- `vi.mock("../lib/reviewedClient", ...)`

### T9 — 全テスト green 確認
- `uv run pytest tests/ -x -q`
- `npm run test` (または `npx vitest run`)

### T10 — Gate (T9 通過後)
- Python 354+ passed, vitest 93+ passed

### T11 — Merge to main
- `finishing-a-development-branch` skill

### T12 — T16 Manual smoke
- サーバー再起動 → `reviewed=True` PATCH → `reviewed=False` PATCH → disk 確認

### T13 — Docs + Memory
- `docs/superpowers/notes/2026-05-16-phase5-b-r3-results.md`
- `memory/project_phase5_b_r3_shipped.md` 新規
- `memory/project_phase5_status.md` 更新

---

## 依存関係

```
T1 → T2 → T3 → T7
T1 → T4 → T5 → T6 → T8
T7, T8 → T9 → T10 → T11 → T12 → T13
```

`write_txn.py` は B r2 で既存 → T2 は import するだけ。
