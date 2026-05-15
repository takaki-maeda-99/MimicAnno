# Phase 5 B r3 — Reviewed Toggle: Design Spec

**Date:** 2026-05-16  
**Author:** Claude (autonomous)  
**Sub-project:** Phase 5 B (Edit UI) release 3  
**Scope:** `reviewed` フラグを phase 変更なしで単独にトグルする。

---

## 1. 目的・背景

r1 (phase relabel) と r2 (boundary drag) では phase / frame を変更すると
`reviewed=True` も自動で立つ。しかし **「位置・ラベルは正しいが reviewed を明示的に
立てたい（あるいは取り消したい）」** というユースケースが想定される。

B r3 ではこの操作を単独の PATCH エンドポイントとして実装し、
SegmentTable の `reviewed` 列をクリッカブルなチェックボックスにする。

---

## 2. 変更スコープ

### In scope
- `PATCH /api/runs/{name}/segments/{segment_id}/reviewed` エンドポイント
- `reviewed_repo.py` — hash 導出 + 原子書き込み
- `reviewedClient.ts` — typed fetch wrapper
- SegmentTable の `reviewed` セル → `<input type="checkbox">` (editable mode)
- RunViewer の `onReviewedToggle` ハンドラ + 412 conflict toast

### Out of scope
- `reviewed=False` 時の `reviewer_id` 以外のフィールドのクリア
- verb / object / target / failure_flags の edit (r4)
- bulk reviewed 更新

---

## 3. API 仕様

### §3.1 エンドポイント

```
PATCH /api/runs/{name}/segments/{segment_id}/reviewed
Content-Type: application/json
If-Match: "<current_run_hash>"
Body: {"reviewed": bool}
```

- `{name}` — run canonical name（URL エンコード済み想定）
- `{segment_id}` — segment_id

### §3.2 成功レスポンス (200)

```json
{
  "run_hash": "<new_run_hash>",
  "manifest": { ...new manifest... }
}
```

ETag ヘッダ: `"<new_run_hash>"`

### §3.3 エラーレスポンス

| 状況 | HTTP | error code |
|------|------|------------|
| Content-Type が application/json でない | 415 | `unsupported_media_type` |
| If-Match ヘッダ欠如 | 428 | `precondition_required` |
| Body に `reviewed` キーなし or 型誤り | 400 | `invalid_body` |
| すでに同じ値 | 400 | `no_change` |
| run が存在しない | 404 | `run_not_found` |
| segment_id が存在しない | 400 | `invalid_segment` |
| If-Match と現在の run_hash が不一致 | 412 | `etag_mismatch` |

### §3.4 状態変化

操作後にセグメントに以下が適用される:

- `seg.reviewed = new_value`
- `reviewed=True` → `seg.reviewer_id = reviewer` (env var 由来、None 可)
- `reviewed=False` → `seg.reviewer_id = None`
- run_hash, manifest.edited_at が更新される
- phase / frame / confidence は変更なし
- `smoothing_summary` は前の値を引き継ぐ（relabel なし）

### §3.5 hash 導出

```
preimage = (
    "edit:reviewed:"          # 固定プレフィックス
    + old_run_hash            # e.g. "sha256:abc..."
    + ":" + segment_id
    + ":" + str(reviewed).lower()   # "true" or "false"
    + ":" + (reviewer or "")
)
new_hash = "sha256:" + sha256(preimage.encode("utf-8")).hexdigest()
```

byte[5] の確認:
- `"edit:reviewed:"[5]` = `'r'`
- r1 `"edit:"[5]` = `':'` → 不一致 ✓
- r2 `"edit:boundary:"[5]` = `'b'` → 不一致 ✓
- pipeline auto (no prefix) → byte[5] がそもそも別 ✓

---

## 4. バックエンド設計

### §4.1 新規ファイル: `reviewed_repo.py`

```python
class ReviewedNoChange(Exception): ...

def derive_reviewed_run_hash(old_run_hash, segment_id, reviewed, reviewer) -> str: ...

def patch_reviewed(
    *, runs_root, name, segment_id, reviewed, if_match, reviewer
) -> dict:  # → new manifest dict
    # file_lock → load → EtagMismatch check → find seg →
    # ReviewedNoChange check → mutate → write_run_atomically
```

`write_run_atomically` は B r2 で作成した `write_txn.py` を共用。

### §4.2 既存ファイル: `routes.py`

`PATCH /api/runs/{name}/segments/{segment_id}/reviewed` ルートを追加。
`PATCH /api/runs/{name}/segments/{segment_id}` (r1) の直前に配置（パス優先順を確保）。

例外マッピング:
- `RunNotFound` → 404
- `EtagMismatch` → 412
- `InvalidSegment` → 400 `invalid_segment`
- `ReviewedNoChange` → 400 `no_change`

---

## 5. フロントエンド設計

### §5.1 `reviewedClient.ts`

```typescript
export type ReviewedPatchResult =
  | { kind: "ok"; runHash: string; manifest: Manifest }
  | { kind: "conflict"; errorCode: string; serverMessage: string }
  | { kind: "no_change"; serverMessage: string }
  | { kind: "invalid"; errorCode: string; serverMessage: string }
  | { kind: "error"; httpStatus: number; errorCode: string | null; message: string };

export async function patchReviewed(args: {
  apiBase: string;
  runName: string;
  segmentId: string;
  reviewed: boolean;
  ifMatchRunHash: string;
  signal?: AbortSignal;
}): Promise<ReviewedPatchResult>
```

URL: `${apiBase}/api/runs/${encodeURIComponent(runName)}/segments/${encodeURIComponent(segmentId)}/reviewed`

### §5.2 SegmentTable

`SegmentRow` に `onReviewedToggle` prop を追加:

```typescript
onReviewedToggle: (
  segmentId: string,
  newReviewed: boolean,
) => Promise<ReviewedPatchResult>;
```

`reviewed` セル:

```tsx
// editable && !disabled の時
<input
  type="checkbox"
  checked={localReviewed}
  disabled={disabled}
  aria-label={`reviewed for ${segment.segment_id}`}
  onChange={(e) => handleToggle(e.target.checked)}
/>
// read-only
{segment.reviewed ? "✓" : "–"}
```

楽観的更新: `localReviewed` を先に反転、non-ok なら戻す。

### §5.3 RunViewer

- `reviewedPatchInFlight` state 追加
- `onReviewedToggle` ハンドラ: r1 の `onPhaseEdit` と同パターン
  - 200 → manifest 更新 + annotation 再取得
  - 412 → `staleRun` conflict toast
- SegmentTable に `onReviewedToggle` を渡す
- `editInFlight={editInFlight || boundaryPatchInFlight || reviewedPatchInFlight}` に拡張

---

## 6. テスト計画

### §6.1 Backend route tests (T5)

`tests/server/test_routes_patch_reviewed.py` — 約 10 件:

| # | テスト内容 |
|---|-----------|
| 1 | 200: `reviewed=True` happy path → 値確認 |
| 2 | 200: `reviewed=False` happy path → reviewer_id=None |
| 3 | 400 `no_change`: すでに reviewed=True で True を送る |
| 4 | 400 `invalid_body`: body なし |
| 5 | 400 `invalid_body`: `reviewed` が文字列 |
| 6 | 400 `invalid_segment`: segment_id が存在しない |
| 7 | 404 `run_not_found` |
| 8 | 412 `etag_mismatch` |
| 9 | 415 `unsupported_media_type` |
| 10 | 428 `precondition_required` |
| 11 | hash disjoint: byte[5]='r' != 's','b' |

### §6.2 Frontend vitest (T14相当)

`frontend/src/__tests__/reviewed-toggle.test.tsx` — 約 5 件:

| # | テスト内容 |
|---|-----------|
| 1 | checkbox checked=false → onChange → `onReviewedToggle("seg-b", true)` |
| 2 | `editable=false` → checkbox なし (read-only "✓"/"–") |
| 3 | `disabled=true` → checkbox disabled |
| 4 | 412 → conflict toast in RunViewer |
| 5 | `no_change` 400 → rollback (localReviewed が元に戻る) |

---

## 7. 除外・制約

- `reviewed=False` 時に他フィールドをリセットしない (`phase` 等は変更しない)
- bulk toggle は対象外
- `smoothing_ops` / `dedup_consecutive` は呼ばない (relabel なし)
- 既存の r1 / r2 ルートは変更しない
