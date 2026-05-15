# Phase 5 B (release 2) — 境界ドラッグ編集 — implementation plan

Date: 2026-05-16
Status: draft
Spec: [`../specs/2026-05-15-phase5-b-r2-boundary-drag-design.md`](../specs/2026-05-15-phase5-b-r2-boundary-drag-design.md)
(post 独立レビュー反映、MUST/SHOULD 全件取り込み済み)

Branch: `feat/phase5-b-r2-boundary-drag` (本 worktree。`origin/main`
`9f1dd06` から分岐済み — r1 SHIPPED commits 全取り込み済み)

---

## 0. ゴール

spec §6 exit criteria 10 項目すべて達成。要点:

1. PATCH `/api/runs/<name>/boundaries/<id>` happy path round-trip
   against `runs/so101_phase4_v5/`
2. +22 新規テスト全 green (17 server unit + 2 integration + 3 frontend)
3. status-code matrix 完備: 200 / 400 ×4 / 404 / 405 / 412 / 415 / 428
4. uvicorn-in-process race test 「正確に [200, 412]」
5. r1 / r2 / auto-pipeline hash 3 空間 disjoint pin
6. 既存 1170+ tests green (r1 PATCH route, `?api=1` UI 不変)
7. mypy --strict clean over `mimicanno/server` (新規 module 含む)
8. Frontend smoke: 内側境界 3 本を 5 frame ずつ drag → reload で persist
9. JSON schema 変更なし (構造不変)
10. notes `2026-05-16-phase5-b-r2-results.md` + memory 更新

---

## 1. 原則

- **TDD**: 各 task は失敗テスト → 実装 → green
- **1 task = 1 commit (PR-able)**
- **r1 契約踏襲**: lock / 書き込み順序 / If-Match / error envelope /
  reviewer DI / single-in-flight UX を一切壊さない
- **新規モジュール優先**: `boundary_repo.py` を `edit_repo.py` の隣に
  新設。共通化できる helper だけ抽出 (lock acquire / 3-file atomic write)
- **frontend は phase relabel UI と疎結合**: 既存 `<select>` 列に手を
  入れない。TimelineRuler はテーブル外の独立コンポーネント
- **検証は uv 経由** (`uv run pytest`, `uv run mimicanno serve`)
- **ブランチ衛生**: 着手時 `git branch -v` + `git log --oneline -10` で
  HEAD 確認 (memory `feedback_handoff_conflict_check`)

---

## 2. タスク分解

| # | タスク | 出力 | 依存 | 性質 |
|---|---|---|---|---|
| T0 | 着手前 audit: (a) r1 fixture `real_so101_run` (または同等) が `tests/server/conftest.py` に存在するか確認、無ければ T7 着手時に新設すべき rsync fixture の scaffold を**この task で**追加 (空 body)、(b) r1 `editClient` 系 fetch mock の手法 (`vi.fn` vs `msw`) を確認 — 結果を本 plan §3 T11/T14 に追記 | 確認メモ ($ git status は変更なし or fixture scaffold 1 commit) | - | audit |
| T1 | 共通 write helper の抽出: `edit_repo.py` から annotation+manifest+index の 3-file atomic write を `mimicanno/server/write_txn.py` (新規) に移管。シグネチャは `write_run_atomically(*, runs_root, canonical_name, annotation, manifest, index_row, lock_timeout=30.0)` — **index.json upsert もここで担う** (r1 既存挙動踏襲)。`edit_repo.py` は薄い wrapper で再 import。**T1 acceptance: 既存 r1 unit/integration test 全 green + `uv run --extra server mypy mimicanno/server` strict clean** (mypy を T15 まで遅延しない) | `mimicanno/server/write_txn.py`, `mimicanno/server/edit_repo.py`, 既存 test 全通, mypy clean | T0 | refactor |
| T2 | spec §3.1 boundary 同定ヘルパー `mimicanno/server/boundary_lookup.py` 新規: `resolve_boundary(segments, boundary_id) -> (left_idx, right_idx)` 関数 + `BoundaryNotFound` / `BoundaryIsTimelineEdge` 例外。unit test (segment_id=0番目→edge, 不在→notfound, 通常→対) | `mimicanno/server/boundary_lookup.py`, test | T1 | server |
| T3 | spec §3.3 frame invariant validator: `validate_new_frame(left, right, new_frame, n_frames) -> None` を boundary_lookup.py 内に追加。違反は `InvalidFrame(reason)` 例外。`n_frames = max(s.end_frame for s in segments) + 1` 導出関数も同 module。unit test (上下端, no-op, 1 frame min, 範囲外) | 同上拡張, test | T2 | server |
| T4a | **hash 派生 helper のみ先行 (pure function)**: `mimicanno/server/boundary_repo.py` に `derive_boundary_run_hash(old_run_hash: str, boundary_id: str, new_frame: int, reviewer: str \| None) -> str` を export。preimage は spec §3.5 通り `"edit:boundary:" + old_run_hash + ":" + boundary_id + ":" + str(new_frame) + ":" + (reviewer or "")`。**T9 はこの関数を直接呼んで定数を生成** (= 手計算 hex を plan に書かない) | helper + unit test (T9 で再利用) | T3 | server |
| T4b | `boundary_repo.patch_boundary(...)` の本体 (~180 LOC): lock + reread + `resolve_boundary` / `validate_new_frame` / `replace` mutation + `_recompute_confidence` + T4a の hash helper 呼び出し + `write_run_atomically` (T1) 呼び出し。**index_row は r1 と同形** で構築して渡す。FastAPI import 無し。unit test (`tmp_runs_root_loadable` fixture、4 ケース: happy / 412 / invalid_boundary / invalid_frame) | `mimicanno/server/boundary_repo.py`, test | T4a | server |
| T5 | PATCH route `/api/runs/{name}/boundaries/{boundary_id}` 登録: r1 PATCH route の直後 (catch-all より前) に挿入。body validation (`{"frame": int}` のみ受理、他キーは 400 invalid_body)。エラー envelope は r1 共通 helper を流用。**405 wiring も同 task 内で確認**: GET `/boundaries/<id>` が 405 + `Allow: PATCH` を返すこと。catch-all は `artifact` allowlist (`manifest.json`, `annotation.json`, ...) に `boundaries` を含まないので素通り、FastAPI default 405 が当たる想定。route 単体 17 ケース (TDD、spec §5.1 #1–#17) を `tests/server/test_routes_patch_boundary.py` に書き下ろし | `mimicanno/server/routes.py`, `tests/server/test_routes_patch_boundary.py` | T4b | server |
| T7 | server integration: 実 `runs/so101_phase4_v5/episode_000000__*` で drag → re-GET → drag (新 ETag) → 元 ETag 412 を pytest fixture で書く (spec §5.2 の 2 ケース)。T0 で確認した fixture を使う (無ければここで rsync fixture を実装) | `tests/server/test_boundary_integration.py` (+ 必要なら `tests/server/conftest.py`) | T5 | integration |
| T8 | race test: uvicorn-in-process pattern を r1 `test_patch_concurrent.py` から拝借し `test_boundary_patch_concurrent.py` を新規作成。`concurrent.futures.ThreadPoolExecutor(max_workers=2)` で同一 ETag 2 並列 PATCH → 結果集合が `{200, 412}` であることを assert (spec §5.1 #16) | `tests/server/test_boundary_patch_concurrent.py` | T7 | integration |
| T9 | r1 ↔ r2 ↔ auto-pipeline hash disjoint pin: **T4a の `derive_boundary_run_hash` と r1 `edit_repo` の hash helper を直接呼び**、(a) r1 hash, (b) r2 hash, (c) `compose_run_hash(config_hash, input_hash)` の 3 値が異なること、かつ preimage byte 0..5 が spec §3.5 の通り (auto: 32-byte 連結, r1: `"edit:" + "sha256:<hex>..."` で byte[5]=`'s'`, r2: `"edit:boundary:..."` で byte[5]=`'b'`) であることを assert。**preimage を手計算 hex で plan に書かず、helper の出力で pin** | `tests/server/test_routes_patch_boundary.py::test_hash_disjoint` | T8 | integration |
| T10 | frontend deps: `pointer-events-polyfill` (jsdom が pointer events を扱えるか確認。扱えない場合のみ追加)、`framer-motion` 等は **入れない** (spring back は CSS transition で済ます)。`frontend/package.json` 更新は最小限 | `frontend/package.json` (必要時) | - | frontend |
| T11 | `frontend/src/lib/boundaryClient.ts` 新規: PATCH 呼び出し + `AbortController` + 10s timeout + 412 handler。r1 の `editClient.ts` (相当) の構造を踏襲。**fetch mock 手法は T0 で確認した r1 流儀をそのまま使う** (T0 で結論を本 plan §3 に追記) | `frontend/src/lib/boundaryClient.ts`, unit test | T10 | frontend |
| T12 | `frontend/src/components/TimelineRuler.tsx` 新規: spec §3.7 のサイズ規約 (32 px 高、4 px/frame min)、内側境界のみハンドル描画、`role="slider"` + ←→ keyboard nudge、`pointerDown/Move/Up` で drag。`getBoundingClientRect` snapshot は drag 開始時のみ | `frontend/src/components/TimelineRuler.tsx` | T11 | frontend |
| T13a | **`RunViewer.tsx` の state-lift refactor**: 現状 `PhaseSelect` 内に閉じている in-flight 状態を `RunViewer` に巻き上げ、`pendingPatch: Promise<...> \| null` を `PhaseSelect` と (T13b で) `TimelineRuler` の双方に props で配る。**この task の vitest: phase PATCH 中に他の `<select>` も disabled** を assert (新 regression test) | `frontend/src/components/RunViewer.tsx`, test | T12 | frontend |
| T13b | `<TimelineRuler>` を SegmentTable 上に 1 段挿入 (`?api=1` 時のみ)、T13a の `pendingPatch` を共有して boundary drag commit 中も既存 `<select>` を disable。PATCH 成功時に local state 更新 + `history.replaceState` で `?hash` 同期 (r1 fix `2b71741` helper 再利用) | `frontend/src/components/RunViewer.tsx` | T13a | frontend |
| T14 | frontend vitest 3 ケース (spec §5.3): drag interaction → 正しい PATCH body、412 → spring back + staleRun フラグ、端点ハンドル非表示。`getBoundingClientRect` mock で確定座標、fetch / 412 mock は **boundaryClient 境界** (実装詳細に縛られないよう ク ライアント関数を vi.mock する)。T0 で r1 が msw を採用していたら msw 側に揃える | `frontend/src/__tests__/timeline-ruler.test.tsx` | T13b | frontend |
| T15 | gate: `uv run --extra server mypy mimicanno/server` clean + `uv run pytest tests/ -q` regression (期待 ~1190 passed) + `cd frontend && pnpm test` (~63 passed) | テスト結果 | T14 | gate |
| T16 | 手動 smoke: `MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve --runs-root /misc/dl00/gayagaya/MimicAnno-phase5b-r2/runs/so101_phase4_v5 --cors-origin http://localhost:5173` + `pnpm dev` + `?api=1&hash=<ep0>`、内側境界 3 本を 5 frame 程度ずつ drag → reload → annotation.json / manifest.json に痕跡確認 (`smoothing_ops=["edited"]`, `reviewer_id=takaki`, `start_boundary.sources=["human_edit"]`, `manifest.edited_at`) | `docs/superpowers/plans/2026-05-16-phase5-b-r2-results.md` 着手 | T15 | gate |
| T17 | docs: `mimicanno/server/README.md` に PATCH boundary endpoint + crash-recovery + `?api=1` boundary drag を追記。trunk README server 節に 1 段落 | docs | T16 | docs |
| T18 | memory 更新: `project_phase5_b_r2_shipped.md` 新規、`phase-5-sub-project-status-2026-05-14` の B 行を r2 SHIPPED 反映 | memory | T17 | docs |

---

## 3. 各タスクの詳細

### T1 — write_txn 抽出 (refactor)

- 既存 `mimicanno/server/edit_repo.py` 内の "lock 取得 → tmp 書き → 順次
  replace" コードを `mimicanno/server/write_txn.py` に切り出す。シグネチャ:
  ```python
  def write_run_atomically(
      *, runs_root: Path, canonical_name: str,
      annotation: Annotation, manifest: Manifest,
      lock_timeout: float = 30.0,
  ) -> None: ...
  ```
- `edit_repo.py` はこの関数を呼ぶよう書き換え。**振る舞いは一切変えない**
- 既存 r1 全テスト ( `tests/server/test_routes_patch.py` 等) が green を
  維持することが本 task の合格基準
- mypy --strict も既存通り

### T2 — boundary_lookup (helpers)

- module: `mimicanno/server/boundary_lookup.py`
- public:
  ```python
  class BoundaryNotFound(LookupError): ...
  class BoundaryIsTimelineEdge(ValueError): ...
  def resolve_boundary(
      segments: list[SubtaskSegment], boundary_id: str,
  ) -> tuple[int, int]: ...   # (left_idx, right_idx)
  ```
- 仕様 (spec §3.1):
  - segments[0].segment_id == boundary_id → `BoundaryIsTimelineEdge`
  - boundary_id が segment_id に存在しない → `BoundaryNotFound`
  - それ以外 → (i-1, i)
- unit test: 上記 3 ケース + boundary_id == segments[-1].segment_id (有効)

### T3 — frame validator

- 同 module に追加:
  ```python
  class InvalidFrame(ValueError):
      def __init__(self, reason: str): self.reason = reason; super().__init__(reason)
  def derive_n_frames(segments) -> int: ...
  def validate_new_frame(
      left: SubtaskSegment, right: SubtaskSegment,
      new_frame: int, n_frames: int,
  ) -> None: ...
  ```
- 違反種別 (reason 文字列): `"new_frame <= left.start_frame"`,
  `"new_frame > right.end_frame"`, `"new_frame out of episode"`,
  `"no-op"`
- unit test: parametrize で各 reason をカバー、boundary 値 (= 1 frame
  min) で OK / 一つ内側で NG をペアで

### T4 — boundary_repo (write transaction)

- module: `mimicanno/server/boundary_repo.py`
- public 単一関数 `patch_boundary(...)`
- 内部フロー:
  1. lock 取得 (T1 の `write_run_atomically` を後段で使う、ここでは
     lock の外でリードはせず関数全体を lock 内側に置く構造を踏襲)
  2. manifest, annotation 再読 → expected_run_hash 比較 → 412
  3. `resolve_boundary` (T2) / `validate_new_frame` (T3) → 各種 400
  4. `replace(left, ...)` / `replace(right, ...)` + `_recompute_confidence`
     (smoother から import)
  5. new annotation, manifest 構築 (manifest.run_hash, edited_at 更新)
  6. spec §3.5 の hash 派生 (pure helper として export、T9 でテスト pin)
  7. `write_run_atomically` 呼び出し
  8. 戻り値: 新 manifest dict
- unit test (5 ケース): happy / If-Match 不一致 / boundary edge /
  invalid_frame / hash 派生 pin (1 ケース内で pre-computed hex 比較)

### T5 — PATCH route + 17 unit tests

- spec §3.6 の登録順を守る: r1 segment PATCH の **直後** に r2 boundary
  PATCH を register、`make_router` の構造を 1 行追加で済ます
- request body validation: `Content-Type != application/json` → 415、
  `frame` キー欠落 / 余分キー / int 以外 → 400 `invalid_body`
- 17 ケースは spec §5.1 を 1:1 で書き下ろす
- TDD: テストを 17 ケース先に書く (skip マーク) → boundary_repo 接続 →
  順に unskip して green

### T6 — 405 wiring

- 実装は `routes.py` 内で同 path に `methods=["PATCH"]` を持つ route と、
  catch-all の落とし方を確認。FastAPI は同じ path で異なる method の
  ハンドラを許す。`/boundaries/{id}` への GET は他に登録が無いので
  デフォルトで 405 を返す (r1 の `/segments/{id}` と同じ wiring)
- テスト #15 で pin、追加コードゼロで通る想定。通らなければ明示的に
  GET ハンドラを 405 emit で追加

### T7 — integration

- fixture: `runs/so101_phase4_v5/episode_000000__*` を tmp_path に
  rsync する pytest fixture を `tests/server/conftest.py` から流用 (r1
  で導入済の `real_so101_run` fixture 名で検索、無ければ新設)
- 2 ケース: drag cycle / stale ETag 412

### T8 — race test

- `tests/server/test_boundary_patch_concurrent.py` 新規
- r1 `test_patch_concurrent.py` から uvicorn-in-process boilerplate を
  そのまま再利用 (ready 判定 `/healthz` + `should_exit` teardown)
- 2 PATCH を `ThreadPoolExecutor(max_workers=2)` で submit、`as_completed`
  で集める。結果集合 = `{200, 412}` を assert

### T9 — hash disjoint pin

- 3 hex を `tests/server/test_routes_patch_boundary.py::test_hash_disjoint`
  に書く:
  ```
  AUTO   = sha256(<config_hash_bytes> || <input_hash_bytes>)
  R1     = sha256("edit:" + AUTO + ":seg_00007:approach_object:takaki")
  R2     = sha256("edit:boundary:" + AUTO + ":seg_00007:42:takaki")
  ```
- 3 つが全て異なること、かつ preimage の byte[0:5] / byte[5] が spec
  §3.5 の通りであることを assert

### T10–T14 — frontend

- TimelineRuler はテーブル外の独立コンポーネント、`RunViewer` に props
  経由で `segments`, `manifest`, `disabled`, `onCommit(boundaryId, frame)`
  を渡す。internal state はドラッグ中の pixel offset のみ
- single-in-flight gate: `RunViewer` 側で `useState(pendingPatch:
  Promise<...> | null)`、TimelineRuler と `<select>` の双方が disabled
  を共有
- 412 → spring back: drag commit 前の state を snapshot で持っておき、
  PATCH 失敗時に CSS transition (0.2s ease) で戻す
- vitest 3 ケース (§5.3 の通り)

### T15 — gate

- `uv run --extra server mypy mimicanno/server`
- `uv run pytest tests/ -q`
- `cd frontend && pnpm test`
- いずれか fail なら関連 task に戻る

### T16 — 手動 smoke

- ep0 で 3 本ドラッグ → reload で永続化、annotation.json を `jq` で
  確認:
  ```
  jq '.segments[].smoothing_ops' annotation.json   # ["edited"] が現れる
  jq '.segments[].start_boundary.sources' annotation.json
  jq '.segments[].reviewer_id' annotation.json
  jq '.edited_at' manifest.json
  ```
- 結果は `2026-05-16-phase5-b-r2-results.md` に貼る (curl 結果 + UI
  スクショ 2 枚程度)

### T17 — docs / T18 — memory

- r1 docs の形式を踏襲

---

## 4. 完了判定

spec §6 の 10 項目 + 本 plan §0 の 10 項目 (= 同等) すべて green。
特に T9 (3 空間 disjoint pin) と T8 (race) が release 2 の固有契約。

## 5. リスク・撤退判断

- **TimelineRuler が肥大化したら**: §3 の T12 が想定 (~300 LOC) を
  超えたら、まず spec §3.7 のキーボード操作と aria を別 release に
  逃がして PR を thin に保つ
- **n_frames 派生の弱さ**: spec §7 で言及、r2 中は `max(end_frame)+1` で
  進める。Phase 4 smoother で末尾切り詰めの構造変化が将来入ったら
  別 follow-up
- **race test の flakiness**: r1 で苦労した uvicorn ready 判定パターンを
  そのまま使うので、それより悪くはならないはず。flake 出るなら
  ThreadPoolExecutor の代わりに `multiprocessing` への切替を検討
