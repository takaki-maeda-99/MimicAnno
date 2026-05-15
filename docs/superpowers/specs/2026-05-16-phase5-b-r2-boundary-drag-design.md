# Phase 5 B (release 2) — phase 境界ドラッグ編集

Date: 2026-05-15
Status: draft
Author: Claude (Opus 4.7) on `feat/phase5-b-r2-boundary-drag`
Sub-project: Phase 5 B (Edit UI) **release 2**: 隣接 2 segment の共有境界 (start/end frame) を frame-snap 単位で人手で動かせるようにする。Phase / object/target / reviewed 単独トグルは別 release。

Related:
- Predecessor: [`2026-05-13-phase5-B-edit-relabel-design.md`](./2026-05-13-phase5-B-edit-relabel-design.md) — r1 で確立した PATCH + If-Match + edit-derived run_hash + 永続化順序 (annotation → manifest → index) をそのまま継承
- Parent: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) §15 #17 (Phase 5 exit criterion), §4.4 (publish lock)
- Phase 5 A read-only: [`2026-05-12-phase5-A-persistence-backend-design.md`](./2026-05-12-phase5-A-persistence-backend-design.md)
- Schema: `mimicanno/schema.py::SubtaskSegment` (start_frame/end_frame/start_time/end_time/start_boundary/end_boundary/boundary_confidence)

---

## 1. Motivation

r1 で phase ラベルの人手修正経路が通った。次に潰すべき誤ラベルパターンは
**境界 (segment 同士の切れ目) の数フレームずれ** で、これは Phase 4 ZC
detector + smoother で出した自動境界が「だいたい合っているが 5〜20 frame
ずれる」というケースが SO101 ep0 smoke でも観察されている。

label を直す前に境界を直したい場面 (例: idle → approach の遷移が遅れて
検出され、approach 区間が短すぎる) が r1 smoke で複数あった。

r2 はその最小実装として「**隣接 segment の共有境界 1 本を、frame 単位で
ドラッグして移動**」できるようにする。両側 segment が同時に変更されるが、
**1 つの atomic PATCH** で表現する (UI 操作 1 回 = サーバ書き込み 1 回)。

## 2. Scope

In scope:
- **新 endpoint** `PATCH /api/runs/<canonical_name>/boundaries/<boundary_id>`
  with body `{"frame": <int>}` — 境界フレーム (= 右側 segment の
  `start_frame`、左側 segment の `end_frame + 1` ※半開区間想定。§3.3 で
  pin) を 1 つの整数フレームに移動する。
- `boundary_id` の規約: 右側 segment の `segment_id`。境界はその右側
  segment の "leading edge" として一意に同定できる (§3.1)。
- `If-Match: "<run_hash>"` 必須 / 412 / 428 / 415 / 400 / 404 / 405 は r1
  と同一エラーモデル。新エラーコード:
  - `400 invalid_boundary` — boundary_id が timeline 端点 (segment 0 の
    start, segment N-1 の end) を指す / 該当 segment が存在しない
  - `400 invalid_frame` — 新 frame が `prev.start_frame < new_frame <
    next.end_frame` を満たさない、隣接 segment が `MIN_SEGMENT_FRAMES`
    (=1, §3.3) を割る、または `[0, n_frames)` の外側
- 両 segment への mutation (1 つの annotation.json 書き換え):
  - 左側 segment: `end_frame = new_frame - 1`, `end_time = frame_to_time(new_frame - 1)`,
    `end_boundary = BoundaryRef(candidate_id=None, time=..., sources=["human_edit"], score=1.0)`
  - 右側 segment: `start_frame = new_frame`, `start_time = frame_to_time(new_frame)`,
    `start_boundary = BoundaryRef(candidate_id=None, time=..., sources=["human_edit"], score=1.0)`
  - 両 segment 共通: `smoothing_ops += ["edited"]` (dedup, r1 と同じ規約),
    `reviewed = true`, `reviewer_id = <env or None>` (上書き、r1 と同じ
    挙動)
  - 両 segment 共通: `boundary_confidence` 再計算 = `min(start_boundary.score,
    end_boundary.score)` (新規ヘルパーで両 BoundaryRef から算出、§3.4 で
    pin)
  - 両 segment 共通: `overall_confidence` は r1 と同じく
    `_recompute_confidence` を再構築 SubtaskSegment に適用
  - `phase` / `verb` / `object` / `target` / `failure_flags` /
    `object_track_ids` / `evidence` などラベル系フィールドは **触らない**
- run_hash 派生 (r1 と disjoint な subspace、§3.5):
  ```
  new_run_hash = "sha256:" + sha256_hex(
      "edit:boundary:" + old_run_hash + ":" + boundary_id + ":" +
      str(new_frame) + ":" + (reviewer_id or "")
  )
  ```
  `"edit:boundary:"` literal prefix で (i) auto-pipeline (`"edit:"` を
  含まない) と (ii) r1 phase relabel (`"edit:" + old_hash + ":" + seg_id +
  ":" + phase + ":" + reviewer`、3 つ目の `:` 後の token が segment_id で
  始まる) の双方と disjoint
- Manifest / index への影響は r1 と同じ: `manifest.edited_at = now_iso()`、
  `manifest.run_hash = new_run_hash`、`generated_at` 不変、
  `runs/index.json` 行 upsert
- 永続化順序 r1 と同一 (annotation.json → manifest.json → index.json、各
  tmp + atomic replace、`runs/index.json.lock` 配下)
- フロントエンド (`?api=1` 時のみ):
  - 既存セグメントテーブルの両側に **timeline ruler** を 1 段追加。
    各内側境界 (= 右側 segment.segment_id) に対しドラッグ可能なハンドル
  - frame 単位 snap (drag 中の hover でフレーム番号 + 時間を表示)
  - drop で PATCH 発火、200 で manifest 更新、412 で r1 と同じ
    staleRun フラグ + reload button、4xx で error code を toast
  - r1 の single-in-flight ポリシを継続 (PATCH 中は全 edit control を
    disable)
  - **ネットワーク stuck 防止**: PATCH 呼び出しは `AbortController` +
    10 秒タイムアウト (r1 client の既存パターンが timeout を持つなら
    流用、無ければ r2 で導入)。タイムアウト → 元位置へ spring back +
    toast "サーバ応答なし、再試行してください"。これがないと PATCH 中
    全 control disable が永久ロックになる
  - 端点 (segment 0 の start / segment N-1 の end) はハンドルを描かない
  - r1 で導入済の phase `<select>` 列は変更なし
- **TimelineRuler のサイズ規約 (scope 制御)**:
  - 1 段の高さは固定 32 px、横幅は親 (RunViewer detail カラム) いっぱい
  - 1 frame 未満の解像度には ピクセル幅を圧縮、最小 4 px/frame を切ったら
    ruler 全体を横スクロールにせず、まずは単純に潰す (r2 では拡大表示を
    入れない、別 release 候補)
  - キーボード操作: ハンドル focus 中に ← / → で 1 frame nudge、Shift+
    ← / → で 5 frame nudge、Enter で commit。ホイール/ピンチ等のリッチ
    操作は r2 out
  - アクセシビリティ: ハンドルに `role="slider"`, `aria-valuemin/max/now`
    を付ける程度に留める (full ARIA は別 release)
  - フレーム→ピクセル変換は `useRef(HTMLDivElement)` 経由で
    `getBoundingClientRect().width` を再計算、resize observer は使わず
    drag 開始時に snapshot するだけ (シンプル化)
- テスト:
  - server unit (新規 17 ケース、§5.1)
  - server integration (実 `runs/so101_phase4_v5/ep0` で drag → reload
    cycle、§5.2)
  - frontend vitest (drag interaction + 412/error path、§5.3)

Out of scope (別 release / 別 spec):
- 同時複数境界の bulk drag — 1 操作 1 PATCH のまま
- 隣接でない segment にまたがる境界の追加/削除 (= segment split / merge) —
  別 release (r5 候補)
- start_frame だけ動かす / end_frame だけ動かす の独立操作 (= 隣接
  segment と切り離して片側を縮める) — 上記 split / merge と合わせて r5
- reviewed=true を phase 変更なしで単独に立てる — r3
- object / target / verb / failure_flags の edit — r4
- 認証・マルチ reviewer 履歴 — Phase 6+
- 自動再 smoothing (edit 後の neighbor 滑らかさ補修) — フットガン回避、
  人手の意図を上書きしない原則は r1 と同じ
- Undo / history — client-side stack のみ (r5+)
- MimicRec (E) からの境界編集 — E の spec で同じ shape を再利用

## 3. Design

### 3.1 boundary_id の規約と存在判定

境界は **右側 segment の `segment_id`** で同定する。

- 入力 `boundary_id = "seg_00007"` ⇒ "segment_id == seg_00007 の segment の
  start 側の境界"
- 左側 segment は annotation の順序付きリストにおける一つ前の segment
- 必要な前提:
  1. annotation.json の `segments` は `start_frame` 昇順で連続 (Phase 4
     smoother の invariant、`smoother.py` で保証)
  2. 隣接 segment 間で `prev.end_frame + 1 == next.start_frame` (半開
     区間 = `[start_frame, end_frame]` inclusive を採用、`schema.py` の
     既存値踏襲。spec §3.3 で再 pin)

存在判定:
- `boundary_id` が `segments[0].segment_id` のときは「左側 segment 無し =
  timeline 開始端」⇒ 400 `invalid_boundary`
- `boundary_id` が存在しない segment_id を指すとき ⇒ 400 `invalid_boundary`
  (NOT 404、URL レベルは正しく run は存在するため; r1 の
  `invalid_segment` と同じ分類)
- timeline 終端 (= `segments[-1].segment_id` を boundary_id にしても、
  それは「左側 segment は最後から 2 つ目、右側 segment は最後」の有効な
  内側境界なので OK。"最後の segment の end_frame" を動かす操作は r2 で
  サポートしない (= 端点固定)

### 3.2 半開 / 閉区間と frame ↔ time 変換

既存 schema は `start_frame, end_frame` を **inclusive** で持っている
(Phase 4 / r1 観察)。境界 frame を **新右側 segment の start_frame** と
定義する → 左側 segment は `end_frame = new_frame - 1`。

`frame_to_time(f) = f / manifest.fps`。`manifest.fps` は `Manifest`
dataclass に既存 (`schema.py:368`)。PATCH 時はサーバが manifest を読んで
fps を取得 → time を再計算 (クライアント計算は信頼しない)。

`end_time` は `(new_frame - 1) / fps`、`start_time` は `new_frame / fps`。
丸めは IEEE 754 / float 自然変換 (既存パイプラインと同じ)。

### 3.3 制約

- `MIN_SEGMENT_FRAMES = 1` (= 1 frame ≤ segment)。Phase 4 smoother の
  最終出力は最短 ≥ 1 frame なので妥当
- `new_frame` invariant (no-op の扱いは下記注を参照):
  - `prev.start_frame + MIN_SEGMENT_FRAMES <= new_frame`
    (= 左 segment が最低 1 frame 残る)
  - `new_frame + MIN_SEGMENT_FRAMES - 1 <= next.end_frame`
    (= 右 segment が最低 1 frame 残る ⇒ `new_frame <= next.end_frame`)
  - `0 <= new_frame < manifest.frame_count` ※ `frame_count` フィールドは
    現状 manifest に無く、`annotation.fps` + 各 segment の最大 end_frame
    から推定。具体的には `episode_n_frames = max(seg.end_frame for seg in
    segments) + 1` (Phase 1 で `unlabeled` がエピソード全体を覆う invariant)
    を使う。**plan で `n_frames` を manifest に格上げするか調査** (r2 中
    では現状の派生で十分、追加コスト無し)
- 上記いずれかに違反 → 400 `invalid_frame` (message に違反内容を含める)
- new_frame が現在の boundary frame と同一 → **クライアント側で送信
  しない** (drop と原位置の差分=0 なら PATCH を発火しない)。サーバが
  万一受け取った場合は 400 `invalid_frame` (`message: "no-op"`) で弾く
  → run_hash が無意味に進むのを防ぐ。UX として 400 toast は出さず、
  サーバ防衛のための最終的安全網として扱う (フロントは§3.7 でガード)

### 3.4 mutation 詳細

`boundary_confidence` と `overall_confidence` の再計算は r1 が既に呼んで
いる **`mimicanno.smoother._recompute_confidence(seg) -> SubtaskSegment`**
(smoother.py:46-63) をそのまま再利用する。これは
`replace(seg, boundary_confidence=min(start.score, end.score),
overall_confidence=...)` を一発で行うので、新規ヘルパーは追加しない。

```python
from dataclasses import replace
from mimicanno.smoother import _recompute_confidence, _dedup_consecutive

i = index_of_segment(segments, boundary_id)   # right side
left = segments[i - 1]
right = segments[i]

new_end_time = (new_frame - 1) / fps
new_start_time = new_frame / fps
left_edited = replace(
    left,
    end_frame=new_frame - 1,
    end_time=new_end_time,
    end_boundary=BoundaryRef(
        candidate_id=None, time=new_end_time,
        sources=["human_edit"], score=1.0,
    ),
    smoothing_ops=_dedup_consecutive(list(left.smoothing_ops) + ["edited"]),
    reviewed=True,
    reviewer_id=reviewer,
)
right_edited = replace(
    right,
    start_frame=new_frame,
    start_time=new_start_time,
    start_boundary=BoundaryRef(
        candidate_id=None, time=new_start_time,
        sources=["human_edit"], score=1.0,
    ),
    smoothing_ops=_dedup_consecutive(list(right.smoothing_ops) + ["edited"]),
    reviewed=True,
    reviewer_id=reviewer,
)
segments[i - 1] = _recompute_confidence(left_edited)
segments[i] = _recompute_confidence(right_edited)
```

`_recompute_confidence` 内部で `boundary_confidence = min(start.score,
end.score)` が走るので、片側 edge を 1.0 に更新した場合の新値は
`min(1.0, 反対 edge の元 score) = 反対 edge の元 score` となる
(テスト §5.1 #1 で明示 assert)。

`label_source` は **触らない**。`"human_edit"` は LabelSource Literal に
存在するが (`schema.py:124-129`)、それを立てるとラベルが「人手再ラベル」
と解釈され parquet export 側で意味が変わる。境界ドラッグはラベルを変えて
いないので `vlm_with_object_state` / `signals_only` 等の元値を保持。

`BoundaryRef.sources` で `"human_edit"` を立てるのが境界レベルの
"人手由来" 標識。これは spec §6.1 の `BoundaryRef.sources` に対する
追記契約 (新値の追加であり既存値を上書きするものではない、Phase 4
boundaries.json の sources も同じく open enum)。

### 3.5 run_hash 派生

```python
new_run_hash = "sha256:" + sha256_hex_of_str(
    "edit:boundary:" + old_run_hash + ":" + boundary_id + ":" +
    str(new_frame) + ":" + (reviewer_id or "")
)
```

**disjoint 性 (preimage の byte index による):**
- byte index 0..4 (`"edit:"`) は両 release 共通
- byte index 5: r1 は `'s'` (続く `old_run_hash` が必ず `"sha256:"` で
  始まるため、JSON Schema の pattern `^sha256:[0-9a-f]{64}$` で強制 ⇒
  manifest.run_hash は必ずこのリテラル接頭)。r2 は `'b'` (リテラル
  `"boundary:"`)。**preimage byte 5 で完全 disjoint**、segment_id の
  命名規約 (`seg_NNNNN`) には依存しない
- vs auto-pipeline: auto は `compose_run_hash(config_hash, input_hash)`
  = `sha256(config_hash || input_hash)` (`config.py:835`)、preimage に
  `"edit:"` リテラルを含まない (config_hash / input_hash は 32 byte
  binary をそのまま連結)。byte 0..4 で disjoint
- 結論: SHA-256 collision を除いて r1 / r2 / auto-pipeline の 3 空間は
  互いに disjoint。テスト #14 で 3 つの pre-computed hex を pin

### 3.6 endpoint co-existence / 登録順

`make_router` 内の登録順 (r1 で確立):

1. `PATCH /api/runs/{name}/segments/{segment_id}` (r1)
2. **NEW**: `PATCH /api/runs/{name}/boundaries/{boundary_id}` (r2)
3. `GET /api/labelset` (r1)
4. `GET/HEAD /api/runs/{name}/{artifact}` (catch-all)

PATCH ルートは catch-all の前に登録。`/boundaries/...` は `/{artifact}`
と path 形が異なるため (`boundaries` は allowlist `artifact` 集合に無い)
405 contract: GET `/api/runs/<name>/boundaries/<id>` は 405 with
`Allow: PATCH` を返す。テスト #11 (r2 新規) で pin。

### 3.7 frontend (release 2 minimum)

- 既存の `SegmentTable`/`RunViewer` の上 (または下) に **TimelineRuler**
  コンポーネントを 1 段追加 (新規 `frontend/src/components/TimelineRuler.tsx`)
- ルーラーは `[0, episode_n_frames)` を pixel domain に線形射影。各
  segment を色帯 (phase 色) で描画、内側境界をドラッグハンドル (≥ 8 px
  幅、左右両方向に snap) として描画
- ドラッグ中:
  - mouse move を pixel→frame に逆射影 → snap (整数 frame)
  - § 3.3 の invariant をクライアント側でも先取り計算し、無効領域では
    cursor を変更 + drop しても fire しない (= サーバ往復を節約)
  - hover で frame 番号と HH:MM:SS.mmm を tooltip 表示
- mouse up (= drop) で PATCH。If-Match は `manifest.run_hash`。Body は
  `{"frame": <int>}`
- 200 → 新 manifest で local state 更新、ETag 進める、`?hash` URL も
  r1 の `history.replaceState` パス (r1 BLOCKER fix `2b71741` 流用) で
  更新
- 412 → r1 同様 staleRun フラグ + reload button、ハンドルは元位置に
  spring back
- 4xx (`invalid_frame` 含む) → toast + spring back
- r1 の single-in-flight: drag 中以外の `<select>` も含む全 edit control
  を disable (drag commit までは select 等を触れない)
- mobile / touch サポートは r2 では out (pointer events を使うが、テスト
  は mouse 系のみ)

### 3.8 reviewer / audit

- r1 §3.6 の `create_app(reviewer=...)` 経路をそのまま流用 (再実装不要)
- サーバログ (INFO):
  `edit-boundary: <old_run_hash> → <new_run_hash>, boundary=<id>, frame=<new_frame>, reviewer=<id>`
- 両 segment の `smoothing_ops += ["edited"]` で監査痕跡

## 4. Backward compatibility

- 既存 read endpoint / r1 PATCH endpoint は完全に不変
- `LabelSource = "human_edit"` Literal は既に schema にある (枠だけ存在、
  実際にこの値で書き出すルートは r2 でも増やさない)
- `BoundaryRef.sources` への `"human_edit"` 追記は open enum 拡張なので
  既存 boundaries.json / annotation.json の reader を壊さない
- `boundary_confidence` の per-segment 値が drag 後に変わる可能性 — これ
  は Phase 4 smoother spec §3.5 の
  "boundary_confidence は更新可能" 規約 (spec の "preserve_sources" 派
  以来) と consistent
- annotation.json / manifest.json schema 構造は変えない (新 field なし)
- `mimicanno annotate` を r2 edit 後に流したら r1 と同じく上書きされる
  (`run_hash` が edit-derived のため reuse short-circuit が当たらない)。
  これは設計通り
- **parquet export 影響 (consumer 通知用)**: `SubtaskSegment.to_sidecar_row`
  (schema.py:212-249) は `BoundaryRef.sources` を
  `boundary_source_start` / `boundary_source_end` 列に流す。r2 edit 後の
  parquet にはこれら列に `"human_edit"` が現れる (新値、既存値の
  上書きではない open enum 拡張)。MimicRec / D の eval consumer はこれを
  人手境界の signal として活用可

## 5. Test plan

### 5.1 Server unit (`tests/server/test_routes_patch_boundary.py`)

Count = 17。

1. PATCH happy path (内側境界を 1 frame 前へ) → 200, 新 ETag, manifest
   レスポンス。両 segment の start_frame/end_frame/start_time/end_time/
   start_boundary/end_boundary が期待通り。`smoothing_ops` 末尾
   `"edited"`, `reviewed=True`, `reviewer_id` 反映。**`boundary_confidence`
   再計算**: 編集側 edge.score = 1.0、反対 edge は元値保持 ⇒ 新
   `boundary_confidence == min(1.0, 反対 edge 元 score) = 反対 edge 元 score`
   を明示 assert (両 segment について)。`overall_confidence` は
   `_recompute_confidence` の規則 (phase∈reserved→0, vlm_conf None→bc,
   else→sqrt(bc·vlm)) に従うことを assert
2. happy path (内側境界を 5 frame 後ろへ): #1 と対称
3. If-Match stale → 412 `etag_mismatch`
4. If-Match absent → 428 `etag_required`
5. Content-Type 不正 → 415 `unsupported_media`
6. invalid_body matrix (parametrized: missing `frame` / extra keys /
   non-int / float / negative / string) → 各 400 `invalid_body`
7. invalid_boundary: `boundary_id == segments[0].segment_id` → 400
   `invalid_boundary`
8. invalid_boundary: 存在しない segment_id → 400 `invalid_boundary`
9. invalid_frame: `new_frame <= prev.start_frame` → 400 `invalid_frame`
10. invalid_frame: `new_frame > next.end_frame` → 400 `invalid_frame`
11. invalid_frame: `new_frame == current boundary frame` (no-op) → 400
    `invalid_frame`
12. invalid_frame: `new_frame >= n_frames` または `< 0` → 400
    `invalid_frame`
13. `MIN_SEGMENT_FRAMES` boundary: `new_frame = prev.start_frame + 1`
    (= 左 segment が 1 frame、許容) → 200 ; 一つ内側 (`prev.start_frame`)
    は 400 ; パラメ化
14. **run_hash disjoint test**: 同じ tmp run に対し
    (a) r1 PATCH (phase relabel) と (b) r2 PATCH (boundary drag) を
    順に流し、生成される 2 つの `run_hash` が異なること、かつどちらも
    `compose_run_hash(config_hash, input_hash)` の結果と異なることを
    アサート (3 つの pre-computed hex 定数で pin)
15. PATCH on `manifest.json` or `boundaries/<id>` via GET → 405 with
    `Allow: PATCH` ヘッダ
16. concurrent PATCH race (r1 と同じ uvicorn-in-process 構造で、同一
    boundary に 2 並列 PATCH) → 正確に [200, 412]。実装上の注意:
    `concurrent.futures.ThreadPoolExecutor(max_workers=2)` で 2 つの
    `httpx.Client` インスタンスから **同じ ETag** を持って PATCH を
    submit する。test thread から逐次呼び出すと serialize されて race
    が起きないので、必ず executor で並列発火させる (r1 plan #T11 と同じ
    pattern を踏襲)
17. **r1 と r2 PATCH の冪等的混在**: phase relabel → boundary drag →
    phase relabel の 3 連 PATCH を同一 segment に対し正しい ETag chain で
    流して全部 200。最終 annotation が「最新 phase + 最新 boundary +
    `smoothing_ops=["edited"]` (dedup されて 1 件)」になることを確認

不変条件 (test helper として #1/#2/#13 内で assert):
- 非対象 segment は byte-identical
- `phase` / `verb` / `object` / `target` / `failure_flags` /
  `object_track_ids` / `evidence` / `label_source` は対象 2 segment でも
  変わらない
- `start_boundary.sources` および `end_boundary.sources` のうち編集側
  edge は `["human_edit"]`、もう一方の edge は元値保持

### 5.2 Server integration

- 実 `runs/so101_phase4_v5/episode_000000__*` で内側境界を 3 frame
  前後に動かし、re-GET annotation.json が反映していること
- cycle: drag → GET → drag (新 ETag) → 元 ETag が 412 を返す

### 5.3 Frontend interaction (vitest + testing-library)

- TimelineRuler に hands-rendered のフェイクデータを流し、内側ハンドルを
  `pointerDown` → `pointerMove(+12px)` → `pointerUp` し、PATCH が呼ばれ
  body が `{"frame": <expected>}` であること
- 412 path: mock 412 → staleRun フラグ + ハンドルが元位置に戻ること
- 端点ハンドル (= 最初/最後の境界相当 = `segments[0].segment_id`) が
  描画されていないこと

### 5.4 mypy + regression

- `uv run --extra server mypy mimicanno/server`
- `uv run pytest tests/ -q` (regression: r1 1170+ tests green)
- `cd frontend && pnpm test`

## 6. Exit criteria

1. PATCH happy path round-trip end-to-end against `runs/so101_phase4_v5/`
2. 全列挙ケース green (§5.1=17, §5.2=2, §5.3=3 ⇒ +22 tests)
3. Status-code matrix: 200 / 400 (×4: `invalid_body`, `invalid_boundary`,
   `invalid_frame`, `invalid_name`) / 404 / 405 / 412 / 415 / 428 全て
   assertable + assert 済
4. Race test (§5.1 #16) が uvicorn-in-process で実 concurrency
5. r1 hash と r2 hash が disjoint subspace から出ることをテストで pin
   (§5.1 #14)
6. r1 既存 1170+ tests green (regression なし、特に r1 PATCH route と
   `?api=1` UI の挙動が変わっていない)
7. `mypy --strict` clean over `mimicanno/server` (新規ファイル含む)
8. Frontend 手動 smoke: `?api=1` で SO101 ep0 を開き、内側境界を 3 本
   それぞれ 5 frame 程度動かして reload → 反映、reviewer_id, edited_at,
   smoothing_ops に痕跡が残っていることを目視確認
9. JSON schema 変更なし (annotation/manifest 構造を変えていないので、
   `mimicanno/jsonschemas/*.schema.json` への手当て不要、CI fixture も
   不変)
10. notes `2026-05-15-phase5-b-r2-results.md` に curl + UI スクショ

## 7. Risks & follow-ups

- **n_frames の派生**: §3.3 で `max(seg.end_frame)+1` を採用したが、
  Phase 4 smoother で末尾 segment が削れる構造変化が将来入ると壊れる。
  Plan で manifest に `episode_n_frames` を昇格させるかを別チケットで
  検討 (r2 中では入れない)
- **boundary_confidence 再計算の意味論**: `min(start, end)` を採用したが、
  Phase 4 smoother spec §3.5 では複数 source を集約する別ロジックがあった
  可能性。実装時に smoother のヘルパー存否を確認、無ければ新規
  `mimicanno/schema.py::recompute_boundary_confidence(seg)` を立てて
  両所から呼ぶ
- **隣接 segment 越境**: 1 frame 動かしただけで「左 segment が
  `phase=approach` で 1 frame しか残らない」のような非現実的形状になり
  得る。r2 では人手の意図を尊重して通す。Phase 4 smoother を再走させる
  オプションは入れない (footgun、r1 と同じ原則)
- **frontend test の pointer event**: jsdom は pointer events を扱える
  が、`elementsFromPoint` 等の geometry 計算は脆い。テストはモック
  `getBoundingClientRect` で確定座標を返す pattern を採る
- **MimicRec (E) との契約**: 境界 drag PATCH の shape (boundary_id =
  右 segment_id, body = `{"frame": int}`) を E のリプレイ UI でも同じく
  使えるよう keep stable

## 8. Implementation order (for the plan)

1. **schema / helper** — r1 既存の `mimicanno.smoother._recompute_confidence`
   をそのまま再利用 (新規ヘルパー追加なし、r1 が既に `edit_repo.py:39` で
   import 済)。`BoundaryRef.sources` への `"human_edit"` 追記の open enum
   拡張は docstring のみ更新 (コード変更不要)
2. **`mimicanno/server/boundary_repo.py`** (新規モジュール、~200 LOC):
   - `runs/index.json.lock` を取得
   - reread manifest + annotation, If-Match 検証
   - §3.3 の制約検証 → 該当エラー
   - §3.4 の mutation を両 segment に適用、`overall_confidence` 再計算
   - run_hash 派生 (§3.5)
   - annotation → manifest → index の atomic write (r1 と同じ順序、共通化
     できる箇所は `mimicanno/server/edit_repo.py` から helper を抽出)
3. **`mimicanno/server/routes.py`**:
   - 新 PATCH route 登録 (catch-all 前、r1 PATCH と並列)
   - 既存の error envelope ヘルパーをそのまま使用 (`server/errors.py`)
4. **server unit tests (§5.1)** — TDD で red → green、17 ケース
5. **server integration test** (§5.2): 既存 `tmp_runs_root` fixture を
   流用
6. **frontend**:
   - `frontend/src/components/TimelineRuler.tsx` 新規
   - `frontend/src/lib/boundaryClient.ts` 新規 (PATCH 呼び出し + 412 ハンドリング)
   - `RunViewer.tsx` / `SegmentTable.tsx` に TimelineRuler を組み込み、
     `?api=1` 時のみハンドルを enable
7. **frontend tests (§5.3)** (vitest + testing-library)
8. **manual smoke** against `runs/so101_phase4_v5/` (ep0, 5 segments,
   3 本の境界を drag)
9. **docs**:
   - `mimicanno/server/README.md` に PATCH boundary endpoint と
     crash-recovery (r1 と同じ順序) を追記
   - 既存 README server section に "境界編集" 1 段落
10. **notes** `2026-05-15-phase5-b-r2-results.md`、memory 更新
    (`project_phase5_b_r2_shipped.md`)
