# Phase 5 B r2 — Boundary Drag Edit: Ship Results (2026-05-16)

## Summary

B r2 (境界ドラッグ編集) を実装・テスト・main マージ・スモーク完了。

## What shipped

### Backend (Python)

| File | 内容 |
|------|------|
| `mimicanno/server/boundary_lookup.py` | `resolve_boundary` / `validate_new_frame` — boundary ID 解決 + フレーム値検証 |
| `mimicanno/server/boundary_repo.py` | `patch_boundary` — ファイルロック下で annotation/manifest/index を原子的更新 |
| `mimicanno/server/write_txn.py` | `write_run_atomically` — B r1 の edit_repo と B r2 が共用する 3-file 書き込みトランザクション |
| `mimicanno/server/routes.py` | `PATCH /api/runs/{name}/boundaries/{boundary_id}` 追加 |
| `mimicanno/server/edit_repo.py` | `write_run_atomically` を使うようリファクタ（ロジック変更なし） |

### Frontend (TypeScript / React)

| File | 内容 |
|------|------|
| `frontend/src/lib/boundaryClient.ts` | `patchBoundaryFrame` — tagged union result type |
| `frontend/src/components/TimelineRuler.tsx` | 32px ルーラー、inner boundary ハンドル、drag + keyboard nudge |
| `frontend/src/components/RunViewer.tsx` | `onBoundaryDragCommit` handler、412 → staleRun conflict toast |

### Tests

- `tests/server/test_routes_patch_boundary.py` — 28 tests (27 spec §5.1 + T9 hash disjoint)
- `tests/server/test_boundary_integration.py` — 2 integration tests (drag cycle + stale ETag chain)
- `tests/server/test_boundary_patch_concurrent.py` — 1 concurrent race test (Barrier + ThreadPoolExecutor)
- `frontend/src/__tests__/timeline-ruler.test.tsx` — 6 vitest tests (drag commit, 412 toast, endpoint handles)

## Key design decisions

- **`useRef` for drag state** — pointer event handlers close over the ref and always see current value; no stale-closure problem between `pointerDown` / `pointerMove` / `pointerUp`.
- **`widthPx` prop as rect width** — jsdom's `getBoundingClientRect().width` returns 0; component uses the prop directly. Only `.left` comes from the DOM.
- **`Number.isFinite` guard in `clampFrame`** — `PointerEvent.clientX` is `undefined` in jsdom; `NaN !== null` is true, so NaN would silently pass the null check without this guard.
- **`boundary_id` = right segment's `segment_id`** — the segment whose `start_frame` is the boundary being moved.
- **Hash prefix** — `"edit:boundary:"` (byte[5]='b') disjoint from r1's `"edit:"` (byte[5]='s') and auto-pipeline (no prefix).
- **`MIN_SEGMENT_FRAMES = 1`** — both left and right segments must keep ≥ 1 frame after the move.

## T16 Smoke results (2026-05-16)

Real SO101 ep0 data, `MIMICANNO_REVIEWER=takaki`.

Starting state: 5 segments, inner boundaries at frames 20, 50, 88, 99.

| Drag | → frame | HTTP |
|------|---------|------|
| seg0001 boundary | 20 → 25 | 200 |
| seg0002 boundary | 50 → 55 | 200 |
| seg0003 boundary | 88 → 93 | 200 |

Final disk state verified:
- `manifest.edited_at` populated ✓
- `reviewer_id = "takaki"` on edited segments ✓
- `start_boundary.sources = ["human_edit"]` on moved boundaries ✓
- index.json: 1 ep0 row (deduped) ✓
- ETag chains correctly across sequential PATCHes ✓

## Test counts at merge (main, 9c25b87)

- Python: 354 passed
- Vitest: 88 passed
