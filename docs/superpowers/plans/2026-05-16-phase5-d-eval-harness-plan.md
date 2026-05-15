# Phase 5 D — Evaluation harness — implementation plan

Date: 2026-05-15 (revised 2026-05-16 → rev3 2026-05-16 late+1h)
Status: draft, rev-3
Spec: [`../specs/2026-05-16-phase5-d-eval-harness-design.md`](../specs/2026-05-16-phase5-d-eval-harness-design.md) (rev3)
Branch: `feat/phase5-d-eval-harness` (rebased onto `main` @ `29f0032`)

## Revision log

**rev 3 (2026-05-16, late+1h)** — Opus reviewer の Blocker + Should-fix
を反映:

- **B1**: T5 / T5.5 / T5.6 の説明で `manifest.edited_at` の取り扱いを明示
  (`_now_iso()` のまま、`event.ts` ではない)。
- **B2**: T5 説明と spec §3.1 pseudocode を現コードの `replace()` パターンに
  揃え (in-place mutation 表記を排除)。
- **S2**: T2.5 の test 入力に **`Z` suffix の `prior_generated_at`** を必須
  ケースとして追加。
- **S3**: T2.5 の「実装制約」を明示: `mimicanno/server/history_event.py`
  は `mimicanno.schema` + stdlib のみ import (`edit_repo` / `boundary_repo`
  / `reviewed_repo` を import しない)。
- **S4**: B r3 テスト件数を pin: **`tests/server/test_routes_patch_reviewed.py`
  = 11 cases** (本リビジョンで確認済 — 実装着手前に追加検証不要)。
- **S8**: T13 smoke threshold を 0.8 → **0.6** に変更 + 操作手順
  ("click select, wait, choose; don't tab through") を明記。
- **N4**: T11 vitest case 2 として「change → blur 順」で duration capture
  を assert するケース追加。
- **N6**: T10 CLI で `--schema-version` の default を `v2.x` prefix
  parse 明記。

**rev 2 (2026-05-16, late)** — B r2 (boundary drag, `9c25b87`) と B r3
(reviewed toggle, `14eb192`) が main にマージ済みのため、`EditEvent`
emit 対象を 3 つの write path に拡張する rev2 spec に追随。

主な差分:

- **ヘルパー抽出**: rev1 の `edit_repo.py::_build_event` を新規モジュール
  `mimicanno/server/history_event.py::build_event` に移動。3 つの repo
  (`edit_repo` / `boundary_repo` / `reviewed_repo`) から共通利用。新規
  タスク **T2.5** (helper 抽出 + 単独 unit test #18) を T4 の前段に挿入。
- **B r2 patch_boundary 拡張**: 新規タスク **T5.5** で
  `boundary_repo.patch_boundary` に history append + tests #13, #14
  (boundary emit / 412 不変)。
- **B r3 patch_reviewed 拡張**: 新規タスク **T5.6** で
  `reviewed_repo.patch_reviewed` に history append + tests #15, #16
  (reviewed emit / 400 no_change 不変)。
- **混在 chain test**: 新規タスク **T6.7** で phase → boundary → reviewed
  の 3-PATCH chain test #17。
- **`label_agreement` field filter**: T8 の `compute_label_agreement(...)`
  に `event.field == "phase"` の事前フィルタを必須化。boundary / reviewed
  events は除外する旨を docstring と test #6 (confusion matrix) で
  明示。
- **`client_coverage_by_field`**: T8/T9 の集計に field ごとの
  `client_coverage` を追加 (phase: 約 1.0、boundary/reviewed: 0.0)。
- **既存テスト無修正 green の対象拡大**: B r1 の 38 ケースに加え、B r2
  (`tests/server/test_routes_patch_boundary.py` 28 + integration 2 +
  concurrent 1 = 31 ケース) と B r3 (`tests/server/test_routes_patch_reviewed.py` の
  全ケース、件数は実装時に確認) を **無修正 green** ガードに追加。
- **タスク数**: 16 → **20** (T2.5, T5.5, T5.6, T6.7 追加)。見積もり
  +0.5 日 (合計 2–2.5 日)。

**rev 1 (2026-05-16)** — reviewer Blocker + Should-fix を反映した差分のみ:

- **B1**: §1「B r1 を絶対に壊さない」節を 5 ファイル (38 ケース) 明示列挙に書き換え。§0 #12 と §4 検証表の数字を 18 → 38 に修正。T5 acceptance に「CI 実行ログで確認」を追加。
- **B2**: T3 を「schema bump 前に現行 literal を pin する regression test を追加」順序に変更、loader-side enforce は r1 対象外と明記。
- **B3**: 新タスク **T6.5** を追加。spec §5.1 #11 (`HISTORY_AHEAD_OF_MANIFEST` recovery) + #12 (`412 で history 不変`) の 2 ケース。タスク合計 15 → 16。T7 の依存元が T6 → T6.5 に。
- **S1**: T4 の `_build_event` 仕様に `pre_edit_overall_confidence` kwarg + first-event 判定ロジック追加。T5 で `apply_edit` が mutate 前に snapshot 退避する手順を明記。
- **S4**: T7-I2 の「force-reuse」を「`mimicanno annotate` overwrite 経路を直接呼ぶ」に書き換え (実在しない CLI フラグの誤参照を除去)。
- **S5**: T6 を「型違反 400、value 範囲違反 silent drop」と明確化。
- **S2**: T8 の 12 ケース内訳に「3-event chain (A→B→C→A) の confusion matrix + by_phase 判定」テストを含めることを明記 (後続 §3 T8 詳細で記述)。

---

依存先: **Phase 5 B r1 (SHIPPED `9f1dd06`)**、**B r2 (SHIPPED `9c25b87`)**、
**B r3 (SHIPPED `14eb192`)**。本計画は 3 つの write 経路:
- `mimicanno/server/edit_repo.py::apply_edit` (B r1)
- `mimicanno/server/boundary_repo.py::patch_boundary` (B r2)
- `mimicanno/server/reviewed_repo.py::patch_reviewed` (B r3)

をそれぞれ拡張する。B r4+ (object/verb edit 等) には依存しない (forward-compatible
— rev2 helper の `field` 引数は拡張可能)。

---

## 0. ゴール

spec §6 の exit criteria 18 項目全達成 (rev2):

1. `EditEvent` schema + `AnnotationResult.history` + `annotation.schema.json` v2.0 bump
2. `apply_edit` が PATCH ごとに 1 event 追加 (atomicity 保持)
3. `client_edit_duration_ms` end-to-end round-trip (UI → PATCH → history)
4. 不正な client duration 値の silent drop
5. server-side `server_inter_event_ms` + clipping flag
6. **un-edited run は byte-identical**:  conditional emit
7. hash chain `prev/new_run_hash` 連続性
8. `mimicanno eval` CLI (JSON + Markdown)
9. `human_edit_time` 計算 (§4.3 通り)
10. `label_agreement` 計算 (4 観点)
11. pre-D run の警告扱い
12. **(rev3)** 全 **33 新規テスト** (server unit 17 #1-#17 + helper 1 #18 + integration 3 + CLI 12) green。既存 PATCH-surface を無修正で全 green: **B r1 38 + B r2 31 + B r3 11 = 80 ケース**。repo 全体 1100+ ケース green
13. mypy --strict clean (`mimicanno/eval/`, 変更行のみ `edit_repo.py`)
14. frontend dropdown 計測 + vitest 追加
15. SO101 v5 手動 smoke で client_coverage (phase events) ≥ 0.8
16. **(rev2)** `boundary_repo.patch_boundary` / `reviewed_repo.patch_reviewed` も EditEvent emit (tests #13-#16)
17. **(rev2)** Mixed-field chain (phase → boundary → reviewed) で 3 events + hash chain intact (test #17)
18. **(rev2)** `mimicanno/server/history_event.py::build_event` が pure function、全 3 repo から呼ばれる (test #18)

---

## 1. 原則

- **TDD**: 各 task 「失敗するテスト → 実装 → green」。
- **1 task = 1 commit (PR-able)**。
- **B r1/r2/r3 の挙動を絶対に壊さない** (rev2 で対象拡大):
  - **B r1 既存 PATCH-surface 5 ファイル (合計 38 ケース) を一字も変更しない**:
    - `tests/server/test_edit_repo.py` (17)
    - `tests/server/test_routes_patch.py` (15)
    - `tests/server/test_routes_patch_cycle.py` (3)
    - `tests/server/test_patch_concurrent.py` (1)
    - `tests/server/test_edit_short_circuit.py` (2)
  - **(rev2) B r2 既存 PATCH-surface を一字も変更しない**:
    - `tests/server/test_routes_patch_boundary.py` (28)
    - `tests/server/test_boundary_integration.py` (2)
    - `tests/server/test_boundary_patch_concurrent.py` (1)
  - **(rev2/rev3) B r3 既存 PATCH-surface を一字も変更しない** (S4 fix で件数 pin):
    - `tests/server/test_routes_patch_reviewed.py` (**11 cases** — rev3 で確認済)
  - 全 gate (T5 / T5.5 / T5.6 / T12) で **無変更 green** を都度確認
  - 3 PATCH エンドポイントのレスポンス body / ETag は完全互換 (history は annotation.json 側のみ)
  - un-edited annotation.json が byte-identical (一文字違ったら fail)
- **`uv run`** 経由で検証 (`uv run pytest`, `uv run mimicanno eval ...`)。
- **branch 衛生** (memory `feedback_handoff_conflict_check`): 開始時に
  `git branch -v` + `git log --oneline -10` で HEAD を確認、worktree
  `feat/phase5-b-r2-boundary-drag` と衝突する変更 (edit_repo.py 同時
  編集) は早めに見つけて報告する。

---

## 2. タスク分解

| # | タスク | 出力 | 依存 | 性質 |
|---|---|---|---|---|
| T1 | `EditEvent` dataclass + JSON serializer 追加 + unit test (round-trip) | `mimicanno/schema.py`, test | - | schema |
| T2 | `AnnotationResult.history: list[EditEvent]` field 追加 + `to_dict()` の **conditional emit (空なら key 省略)** + 既存 fixture の byte-identical regression test | `mimicanno/schema.py`, test | T1 | schema |
| T3 | `annotation.schema.json` 更新 (`history` optional, `schema_version` → `"2.0"`) + `read_annotation` loader 拡張 + **B2 reviewer fix**: T3 着手前に `runs/so101_phase4_v5/` の現行 `schema_version` literal を読み出し pin する regression test を追加。その後に書き手 (`AnnotationResult.schema_version` default in `mimicanno/schema.py`) を一箇所だけ bump。loader-side enforce は r1 対象外と明記 (`mimicanno eval --schema-version` 側でのみ refuse) | `mimicanno/jsonschemas/annotation.schema.json`, `mimicanno/io.py`, `mimicanno/schema.py`, test | T2 | schema |
| T2.5 | **(rev2/rev3)** `mimicanno/server/history_event.py` 新規モジュール: `build_event(...)` pure function を抽出 + `_validate_client_duration(...)` + spec §5.1 #18 unit test。**rev3 制約**: import は `mimicanno.schema` + stdlib のみ (`edit_repo` / `boundary_repo` / `reviewed_repo` を import しない、cycle 防止)。**rev3 テスト追加**: `prior_generated_at` に `Z` 終端 ISO 文字列を渡して `_parse_iso` 経路が動くことを assert (S2 fix)。`field != "phase"` のとき `pec=None` 即返しを assert (S1 fix) | `mimicanno/server/history_event.py`, `tests/server/test_history_event.py` (新規) | T3 | server |
| T4 | `edit_repo.apply_edit` が `history_event.build_event` を呼んで `EditEvent(field="phase", ...)` を作るよう書き換え + `pre_edit_overall_confidence` 経路は T2.5 helper で完結 (rev2 で T4 は単なる caller refactor) | `mimicanno/server/edit_repo.py` | T2.5 | server |
| T5 | `apply_edit(...)` 拡張 (rev3 B2 fix): kwargs `client_edit_duration_ms=None` 追加 + **S1**: mutate 前に `old_overall_confidence = old_seg.overall_confidence` 退避 (replace パターンに合わせて `old_seg` 命名で統一) + `build_event` へ thread + `new_annotation = replace(annotation, segments=segments, run_hash=new_run_hash, history=annotation.history + [event])` で書き込み (immutable concat、in-place mutation しない) + `new_manifest = replace(manifest, run_hash=new_run_hash, edited_at=_now_iso())` (**B1 fix**: `_now_iso()` のまま、`event.ts` ではない、micro-drift 許容) + **B r1 既存 PATCH-surface 5 ファイル (38 ケース) 無修正 green を CI 実行ログで確認** | `mimicanno/server/edit_repo.py`, test | T4 | server |
| T5.5 | **(rev2) `boundary_repo.patch_boundary` 拡張**: mutate 後の `segments` 構築前後に `event = build_event(field="boundary", from_value=<old start_frame: int>, to_value=<new_frame: int>, segment_id=<right segment id>, client_edit_duration_ms=None, pre_edit_overall_confidence=None, ...)` を生成 → `new_annotation = replace(annotation, segments=..., history=annotation.history + [event], run_hash=new_run_hash)` で書き込み + spec §5.1 #13, #14 実装 (TDD) + **B r2 既存テスト 31 ケース無修正 green 確認** | `mimicanno/server/boundary_repo.py`, `tests/server/test_edit_history.py` (追記) | T5 | server |
| T5.6 | **(rev2) `reviewed_repo.patch_reviewed` 拡張**: 同様に `build_event(field="reviewed", from_value=<old bool>, to_value=<new bool>, ...)` を append + spec §5.1 #15, #16 実装 + **B r3 既存テスト 無修正 green 確認** | `mimicanno/server/reviewed_repo.py`, `tests/server/test_edit_history.py` (追記) | T5.5 | server |
| T6 | PATCH route body validator 拡張 (phase endpoint のみ): `client_edit_duration_ms: float \| None` を許可 (型違反は 400、value 範囲違反 = NaN / inf / 負 / >1h は **silently drop** = `build_event` 内で None 化、spec §3.3) + spec §5.1 #1–#10 全ケース実装 (TDD)。**S5 reviewer fix**: 400 vs drop の境界をテストコメントで明示。**注**: boundary/reviewed endpoint の body schema は変更しない (rev2 §3.4) | `mimicanno/server/routes.py`, `tests/server/test_edit_history.py` | T5.6 | server |
| T6.5 | **B3 reviewer fix**: spec §5.1 #11 `HISTORY_AHEAD_OF_MANIFEST` テスト + #12 `412 で history 不変` テストを追加。#11 は `write_manifest_json` monkeypatch で annotation 後 manifest 前にクラッシュさせ on-disk 状態を作り、CLI が warning を返す経路を assert。#12 は B r1 `test_apply_edit_stale_etag_raises_and_disk_untouched` に依存しない独立 assertion | `tests/server/test_edit_history.py` | T6 | server |
| T6.7 | **(rev2) 混在 chain test #17**: 同じ run に対し phase → boundary → reviewed の順に 3 PATCH → `annotation.history` の長さ 3、fields = `["phase", "boundary", "reviewed"]`、`history[i].new_run_hash == history[i+1].prev_run_hash` で hash chain intact | `tests/server/test_edit_history.py` | T6.5 | server |
| T7 | server integration test 3 件 (spec §5.2): real disk PATCH (rev2 で 1 phase + 1 boundary + 1 reviewed の mix に更新) → CLI 呼び出しで `total_edits == 3`, `client_coverage_by_field` 確認 / **`mimicanno annotate` で history が消える** (S4 reviewer fix) / hash-chain 破壊で warning | `tests/server/test_edit_history_integration.py` | T6.7 | integration |
| T8 | `mimicanno/eval/` package 骨組み + `metrics.py` の pure 関数群 (collect events, confusion matrix, by_source, by_confidence_bucket, by_phase, human_edit_time aggregates) + **(rev2)** `compute_label_agreement(...)` で `field == "phase"` 事前フィルタ必須 + `client_coverage_by_field` 集計追加 + 12 unit test (spec §5.3、TDD、うち 1 ケースは boundary/reviewed event が label_agreement に混入しないことを assert) | `mimicanno/eval/__init__.py`, `mimicanno/eval/metrics.py`, `tests/eval/test_metrics.py` (新規) | T3 | eval |
| T9 | `mimicanno/eval/render.py` (Markdown renderer) + snapshot fixture (`tests/eval/fixtures/expected_report.md`) + **(rev2)** Markdown に `client_coverage_by_field` テーブル (phase / boundary / reviewed の coverage を per-row) を追加 | `mimicanno/eval/render.py`, fixture | T8 | eval |
| T10 | `mimicanno/eval/cli.py` (arg parse + orchestration) + `mimicanno/cli.py` に `eval` subcommand 追加 + smoke unit test (programmatic invocation, captured stdout)。**rev3 N6 fix**: `--schema-version` の default 値解釈は **prefix match**: `schema_version.startswith("v2.")` を accept、それ以外を `EVAL_SCHEMA_INCOMPATIBLE` で reject。`==v2.0` 等の厳密一致にはしない (将来の v2.1 bump で破綻するため) | `mimicanno/eval/cli.py`, `mimicanno/cli.py`, test | T9 | cli |
| T11 | frontend: phase `<select>` に `focusin`/`change` 計測 hook + PATCH body へ `client_edit_duration_ms` 載せ + 既存 vitest 3 ケースを壊さずに **2 ケース追加** (rev3 N4 fix): (a) `focus → change → blur` の順で fetch mock の PATCH body に `client_edit_duration_ms` が含まれる (`performance.now` mock 0→1234.5)、(b) `focus → blur (no change)` で次回 `change` 時に duration が None (前回 t0 がリセット済) | `frontend/src/`, vitest | T6 | frontend |
| T12 | mypy --strict (`mimicanno/eval`, `mimicanno/server/edit_repo.py` の touch 行) + 全 regression confirm (1100+ tests) | テスト結果 | T11 | gate |
| T13 | 手動 smoke: `runs/so101_phase4_v5/` で `mimicanno serve` → UI 経由で **phase 5 edits + boundary 1 drag + reviewed 1 toggle** (合計 7 events) → `uv run mimicanno eval runs/` → `total_edits == 7`、`client_coverage_by_field.phase ≥ 0.6` (**rev3 S8 fix**: 0.8 → 0.6、UI race を許容)、`client_coverage_by_field.boundary == 0.0`、`client_coverage_by_field.reviewed == 0.0`、Markdown 100 char wrap 検査。**操作手順 (rev3)**: phase edit は「dropdown を **click** → 1 秒待つ → 値を click」 (Tab キーで通過しない、focus event を確実に発火させる) | smoke notes | T12 | gate |
| T14 | docs: top-level `README.md` `## Eval` section + `mimicanno/server/README.md` の history 追記 + `mimicanno/eval/README.md` 新設 | docs | T13 | docs |
| T15 | notes `2026-05-15-phase5-d-eval-results.md` + memory 更新 (`project_phase5_status.md`、新 `project_phase5_d_shipped.md`) | notes, memory | T14 | docs |

合計: **20 tasks** (rev2 で T2.5 / T5.5 / T5.6 / T6.7 追加)、見積もり **2–2.5 日** (TDD で密度高め、frontend は軽量)。

---

## 3. 各タスクの詳細

### T1: `EditEvent` dataclass

`mimicanno/schema.py` に追加。場所は `SubtaskSegment` のすぐ下 (Phase 5 D
の history-related schema をまとめておく)。

```python
@dataclass
class EditEvent:
    event_id: str
    ts: str
    segment_id: str
    field: str           # Literal["phase","boundary","reviewed","object","verb","target"]
    from_value: Any      # str | int | bool | None
    to_value: Any
    reviewer_id: str | None
    prev_run_hash: str
    new_run_hash: str
    client_edit_duration_ms: float | None
    server_inter_event_ms: float | None
    clipped: bool
```

`to_dict` / `from_dict` を `_ALLOWED_FIELDS` 経由で書く (既存パターン
踏襲)。test = round-trip 1 ケース (`from_dict(to_dict(x)) == x`)。

### T2: `AnnotationResult.history` + conditional emit

```python
@dataclass
class AnnotationResult:
    ...  # 既存フィールド全部
    history: list[EditEvent] = field(default_factory=list)
```

`to_dict()` で:

```python
if self.history:
    d["history"] = [e.to_dict() for e in self.history]
# else: key を出さない
```

regression test = `tests/io/test_annotation_byte_identity.py` (新規 or
既存に追記): Phase 4 fixture を read → to_dict → bytes 比較。**1 byte
違ったら fail**。

### T3: JSON schema + loader

- `annotation.schema.json`: `properties.history = { type: "array", items: {ref EditEvent} }`、`schema_version` enum に `"2.0"` 追加。
- `read_annotation` (in `mimicanno/io.py`): `raw.get("history", [])` を
  パースして `EditEvent` のリストを構築。v1 fixture (history 無し) は
  空リストで通る。
- regression test: 既存 fixture 全てを validate して loader を通す。

### T4: `_build_event` helper (server only)

`mimicanno/server/edit_repo.py` に **private** function として配置。

```python
def _build_event(
    *,
    segment_id: str,
    field: str,
    from_value: Any,
    to_value: Any,
    reviewer_id: str | None,
    prev_run_hash: str,
    new_run_hash: str,
    client_edit_duration_ms: float | None,
    prior_history: list[EditEvent],
    prior_generated_at: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EditEvent:
    ...
```

`now` 注入で test から時刻固定。test 8 ケース:
1. prior_history 空 → `prior_generated_at` 基準で delta 計算
2. prior_history N 件 → 最後の event ts 基準で delta 計算
3. delta > 1h → clipped=True、3_600_000ms
4. delta < 0 (時刻巻き戻り) → 0ms、clipped=True
5. client = None → そのまま None
6. client = 1234.5 → そのまま 1234.5
7. client = -5 → None (drop)
8. client = NaN / inf / > 1h → None (drop)

### T5: `apply_edit` 拡張

既存 transaction の **lock 内、write 直前**:

```python
event = _build_event(
    segment_id=segment_id,
    field="phase",
    from_value=old_phase,
    to_value=new_phase,
    reviewer_id=reviewer,
    prev_run_hash=if_match,
    new_run_hash=new_run_hash,
    client_edit_duration_ms=client_edit_duration_ms,
    prior_history=annotation.history,
    prior_generated_at=manifest.generated_at,
)
annotation.history.append(event)
# その後で write_annotation → write_manifest → update_index (B r1 既存順序)
```

重要: **既存 18 unit test を一字も書き換えない**。それでも green でなければ
ならない。新フィールドはレスポンス body の `manifest` には現れない
(history は annotation.json 側のみ)、ETag も影響しないので可能。

### T6: PATCH body validator + 10 server unit tests

body 検証 (現状 `phase` のみ受け入れる) を:

```python
ALLOWED_KEYS = {"phase", "client_edit_duration_ms"}
if set(body.keys()) - ALLOWED_KEYS:
    raise InvalidBody(...)
if "phase" not in body:
    raise InvalidBody("missing phase")
client_dur = body.get("client_edit_duration_ms")
if client_dur is not None and not isinstance(client_dur, (int, float)):
    raise InvalidBody("client_edit_duration_ms must be number")
```

`apply_edit(..., client_edit_duration_ms=client_dur)` に forward。

test = spec §5.1 #1–#10、`tests/server/test_edit_history.py`。

### T7: integration 3 件

`tmp_runs_root_loadable` (B r1 で導入済) を使う。

- I1: 3 PATCH → CLI を `mimicanno.eval.cli.run(...)` で programmatic 呼び出し → JSON dict assert。
- I2: PATCH → `pipeline.publish` の force-reuse 経路 (T10b 流儀) → history が消えてることを assert。
- I3: history[1].prev_run_hash を hand-tamper → CLI が `HISTORY_CHAIN_BROKEN` warning を返す。

### T8: `mimicanno/eval/metrics.py` + 12 unit tests

純関数:

```python
def collect_events(runs: list[Path]) -> CorpusEvents: ...
def compute_human_edit_time(corpus, include_clipped: bool) -> HumanEditTime: ...
def compute_confusion_matrix(corpus) -> ConfusionMatrix: ...
def compute_by_source(corpus) -> BySource: ...
def compute_by_confidence_bucket(corpus) -> ByBucket: ...
def compute_by_phase(corpus) -> ByPhase: ...
def build_report(corpus, filters) -> EvalReport: ...
```

`EvalReport` も dataclass、`to_dict()` で spec §4.2 の JSON shape を出す。

test 12 ケースは spec §5.3 を 1:1 で実装。fixture は in-test construct
(`make_fake_run(...)` helper)。

### T9: Markdown renderer

`render_markdown(report: EvalReport) -> str`。100 char wrap、tabulate
or 手書きで揃え。snapshot test 1 件 (golden fixture と diff)。

### T10: CLI

`mimicanno/eval/cli.py::run(argv: list[str]) -> int`。`argparse`。
`mimicanno/cli.py` に subparser 追加 (既存 `serve` `annotate` `export`
パターン踏襲)。

test: `run(["runs/fixture/", "--format", "json"])` → stdout に valid JSON。

### T11: frontend

`frontend/src/components/RunViewer.tsx` (or where phase dropdown lives):

```tsx
const tFocusRef = useRef<number | null>(null);
<select
  onFocus={() => { tFocusRef.current = performance.now(); }}
  onChange={(e) => {
    const dur = tFocusRef.current
      ? performance.now() - tFocusRef.current
      : null;
    patchSegment(segId, { phase: e.target.value, client_edit_duration_ms: dur });
    tFocusRef.current = null;
  }}
  onBlur={() => { tFocusRef.current = null; }}
/>
```

vitest case: mock `performance.now` (0 → 1234.5)、change イベント発火、
fetch mock の PATCH body assert。

### T12: mypy + 全 regression

```
uv run mypy --strict mimicanno/eval mimicanno/server/edit_repo.py
uv run pytest
```

すべて green。

### T13: 手動 smoke

```
uv run mimicanno serve --runs-root runs/
# ブラウザで ?api=1、5 edits、reload で persist 確認
uv run mimicanno eval runs/so101_phase4_v5/ --format both --out /tmp/eval-smoke
cat /tmp/eval-smoke.md
```

Pass 条件:
- aggregate.client_coverage ≥ 0.8
- by_source table が 2 row 以上
- Markdown が ≤100 char (`awk 'length>100' /tmp/eval-smoke.md` 空)

### T14: docs

- `README.md` に `## Eval` section (使い方の最小例 + JSON/MD出力位置)
- `mimicanno/server/README.md` の `edit_repo.py` 行に "appends EditEvent
  to annotation.history[] (D r1)" 追記
- `mimicanno/eval/README.md` 新規 (metric の解釈、pre-D run 注意、
  confidence bucket の approximation footnote)

### T15: notes + memory

- `docs/superpowers/notes/2026-05-15-phase5-d-eval-results.md`: 結果
  サマリ、smoke 数値、open items (D r2 候補)
- memory:
  - `project_phase5_status.md`: D 行を SHIPPED に
  - 新規 `project_phase5_d_shipped.md`: human_edit_time の解釈、
    pre-D 警告の意味、frontend timing の限界

---

## 4. 検証ストラテジ

| layer | コマンド | 期待 |
|---|---|---|
| schema | `uv run pytest tests/io/ tests/test_schema.py -v` | 全 green、byte-identity test 含む |
| server helper | `uv run pytest tests/server/test_history_event.py -v` | 1 case green (#18) |
| server unit | `uv run pytest tests/server/test_edit_history.py -v` | rev2 で 17 cases green (#1-#17) |
| server regression (B r1) | `uv run pytest tests/server/test_edit_repo.py tests/server/test_routes_patch.py tests/server/test_routes_patch_cycle.py tests/server/test_patch_concurrent.py tests/server/test_edit_short_circuit.py -v` | 38 cases 全 green |
| server regression (B r2) | `uv run pytest tests/server/test_routes_patch_boundary.py tests/server/test_boundary_integration.py tests/server/test_boundary_patch_concurrent.py -v` | 31 cases 全 green |
| server regression (B r3) | `uv run pytest tests/server/test_routes_patch_reviewed.py -v` | 11 cases 全 green (rev3 S4 fix で件数 pin 済) |
| integration | `uv run pytest tests/server/test_edit_history_integration.py -v` | 3 cases green |
| eval unit | `uv run pytest tests/eval/ -v` | 12 cases green |
| frontend | `cd frontend && pnpm vitest` | 既存 3 + 新 1 = 4 cases green |
| mypy | `uv run mypy --strict mimicanno/eval mimicanno/server/edit_repo.py` | 0 errors |
| 全体 | `uv run pytest` | 1100+ cases 全 green |
| smoke | T13 参照 | client_coverage ≥ 0.8 |

---

## 5. ロールバック手順

各 task は単独 commit、PR レビュー対象。問題発生時:

- T1–T3 (schema): `mimicanno/schema.py`, `annotation.schema.json` を
  revert。既存 annotation.json は v1 のまま読める (D は loader 互換)。
- T4–T7 (server): edit_repo.py を revert。B r1 の挙動に戻る (PATCH は
  動作継続、history が積まれなくなる)。
- T8–T10 (eval CLI): `mimicanno/eval/` ディレクトリ削除 + cli.py から
  subparser を外す。他に影響なし。
- T11 (frontend): `RunViewer.tsx` の onChange を B r1 版に戻す。
- 重要: schema_version v2.0 で publish 済の annotation.json が既に
  あった場合、ダウングレード後の loader はそのファイルを v2.0 とみなして
  warning しか出さない (history を読み捨て)。実害なし。

---

## 6. open questions

- D の `mimicanno eval` を CI/cron で回す? → r1 では手動のみ。r2 で
  考える。
- multi-reviewer の集約 (Cohen's κ 等) → D r2 で別 spec。
- `client_edit_duration_ms` を超軽量データセットや視覚化に流す pipeline →
  Phase 6+ の話。

---

## 7. メモリ参照

- `project_phase5_status.md` (D = 未着手 → SHIPPED に更新予定)
- `project_phase5_b_r1_shipped.md` (B r1 の write 経路詳細、依存元)
- `feedback_handoff_conflict_check.md` (worktree 衝突の早期検知)
- `feedback_plan_before_implement.md` (TDD 順を守る)
