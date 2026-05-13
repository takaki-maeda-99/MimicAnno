# Phase 5 B (release 1) — phase relabel edit — implementation plan

Date: 2026-05-13
Status: draft
Spec: [`../specs/2026-05-13-phase5-B-edit-relabel-design.md`](../specs/2026-05-13-phase5-B-edit-relabel-design.md)
(post 4-round review, SPEC OK)

Branch: TBD (suggest `feat/phase5-b-r1-relabel`). Cut from current
`main` (`ee89335` or later) after Phase 5 A polish PR is merged.

---

## 0. ゴール

spec §6 の exit criteria 10 項目すべて達成:

1. PATCH happy path round-trip against `runs/so101_phase4_v5/`
2. 23 新規テスト全 green (18 unit + 2 integration + 3 frontend vitest)
3. 9 status codes 完備: 200 / 400 ×4 / 404 / 405 / 412 / 415 / 428
4. Race test (uvicorn-in-process) 「exactly 1 wins」
5. `MIMICANNO_REVIEWER` env passthrough + reviewer encoding pinned
6. 既存 1070+ tests green (no regression)
7. mypy --strict clean over `mimicanno/server`
8. Frontend `?api=1` smoke: 3 segments relabel + reload で persist
9. jsonschema validation: `manifest.schema.json` 更新後も既存 manifest
   が validate
10. notes `2026-05-13-phase5-b-r1-results.md`

---

## 1. 原則

- **TDD**: 各 task は「失敗するテスト → 実装 → green」の順。テストファース
  ト不可能な infrastructure task (configs, deps, lockfile) は明示する。
- **1 task = 1 commit (PR-able)**。
- **慎重に一個ずつ**: spec の B サブプロジェクトは多リリース展開なので、
  release 1 (phase relabel) で確立した契約を release 2+ が継承する。
  そのため r1 では契約面に時間を多めにかける。
- **既存挙動を絶対に壊さない**:
  - `[server]` extra 未取得時の既存 CLI 挙動完全保持
  - read endpoint (Phase 5 A) は touch しない
  - 既存の auto-pipeline 経路 (`mimicanno annotate`) は behavioural diff 無し
- **検証は uv 経由** (`uv run pytest ...`, `uv run mimicanno ...`)。
- **ブランチ衛生**: memory `feedback_handoff_conflict_check` の通り、
  作業開始時に `git branch -v` + `git log --oneline -10` を実行、
  HEAD が想定通りかを確認してから着手する。

---

## 2. タスク分解

| # | タスク | 出力 | 依存 | 性質 |
|---|---|---|---|---|
| T1 | `SmoothingOp` Literal + `_ALLOWED_SMOOTHING_OPS` に `"edited"` 追加 + **positive accept test** + 既存拒否テスト保持 | `mimicanno/smoother.py`, `mimicanno/schema.py`, test | - | schema |
| T2 | `Manifest` に `canonical_name` + `edited_at` field 追加 + `to_dict` conditional emit + unit test | `mimicanno/schema.py`, test | T1 | schema |
| T3 | `read_manifest` (io.py:150-199) の reader fallback + `manifest.schema.json` 拡張 + 既存 fixture 互換 test | `mimicanno/io.py`, `mimicanno/jsonschemas/manifest.schema.json`, test | T2 | schema |
| T4 | **4 つの Manifest construction sites** で `canonical_name` 対応: `publish.py` 内 (publish 内で resolve 後 upsert)、`pipeline.py:497/1068/1428` (None で構築 → publish が上書き) + 回帰テスト | `mimicanno/publish.py`, `mimicanno/pipeline.py`, test | T3 | writer |
| T4.5 | **`tests/server/conftest.py` `tmp_runs_root` を realistic に拡張**: 完全 manifest (`read_manifest` で load 可能)、本物 annotation.json (1 segment + boundaries 等)。Phase 5 A の bytes-passthrough テストは現状温存、新たに `tmp_runs_root_loadable` fixture を追加 | `tests/server/conftest.py` | T3 | fixture |
| T5 | `mimicanno/server/labelset.py` 新規 (`LabelSetCache` DI handle 含む) + `GET /api/labelset` endpoint + unit test #17 + Cache-Control consistency (`max-age=300`、A の `no-cache` とは別エンドポイント policy) | `mimicanno/server/labelset.py`, `mimicanno/server/routes.py`, test | T1 | server |
| T6 | `mimicanno/server/edit_repo.py` 新規 (write transaction、no FastAPI deps) + unit test (file-level、`tmp_runs_root_loadable` 使用) | `mimicanno/server/edit_repo.py`, test | T2, T4, T4.5 | server |
| T7 | `app.py` の **CORS `allow_methods` 拡張 + `create_app(reviewer=...)` parameter を先に**: routes が reviewer を使えるよう wiring を先行整備 (旧 T8 を前倒し) | `mimicanno/server/app.py`, test | T6 | server |
| T8 | PATCH route `/api/runs/{name}/segments/{segment_id}` + body validation + 18 ケース unit test (TDD)、reviewer は T7 で thread 済み | `mimicanno/server/routes.py`, `tests/server/test_routes_patch.py` | T7 | server |
| T9 | `cli.py serve_cmd` で `MIMICANNO_REVIEWER` env 読み + forward + **programmatic test** (monkeypatched env + `create_app` 直接呼び、subprocess は smoke のみ) | `mimicanno/cli.py`, test | T8 | cli |
| T10 | server integration test #1 (real disk PATCH cycle) + #2 (PATCH → re-GET 新 ETag、stale If-Match 412)。**#16 annotate-overwrites-edit は T10b として分離**: real Gemma/SAM3 を回さず、**`pipeline.publish` の reuse short-circuit 経路** を直接テスト (auto-derived hash vs edit-derived hash が disjoint なことを assert) | `tests/server/test_routes_patch.py` | T9 | integration |
| T10b | annotate-overwrites-edit short-circuit assertion (Gemma/SAM3 抜き、publish.py の `_existing_run_hash` 比較ロジック直撃) | `tests/server/test_routes_patch.py` | T10 | integration |
| T11 | race test #13 (uvicorn-in-process、別 module、`/healthz` ready 判定 + `should_exit` teardown) | `tests/server/test_patch_concurrent.py` | T10b | integration |
| T11.5 | **frontend testing deps install**: `@testing-library/react`, `@testing-library/dom`, `@testing-library/user-event`, `jsdom` を `frontend/package.json` `devDependencies` に追加 + `vitest.config.ts` の `environment: "jsdom"` 設定 | `frontend/package.json`, `frontend/vitest.config.ts` | T8 | frontend |
| T12 | frontend: `ApiToggleContext` + `lib/manifest.ts` ベース URL toggle + **`RunList.tsx` の `runs/index.json` fetch 切替** + `RunViewer.tsx` 配線 | `frontend/src/` | T11.5 | frontend |
| T13 | frontend: phase `<select>` + PATCH client (If-Match 付き) + 412/4xx toast + labelset cache (`ETag` keyed) | `frontend/src/` | T12 | frontend |
| T14 | frontend vitest 3 ケース + (T11.5 で integrated testing-library を使用) | `frontend/src/__tests__/` | T13 | frontend |
| T15 | mypy --strict (`mimicanno/server` scoped) + 全 regression confirm | テスト結果 | T14 | gate |
| T16 | 手動 smoke (`runs/so101_phase4_v5/`、必要なら `mimicanno annotate --force` で再 publish して新フィールド bake) + `2026-05-13-phase5-b-r1-results.md` | notes | T15 | gate |
| T17 | README + `mimicanno/server/README.md` 拡張 (PATCH + labelset + crash-recovery + ?api=1) | docs | T16 | docs |
| T18 | memory 更新 (`project_phase5_status.md`、新 `project_phase5_b_r1_shipped.md`) | memory | T17 | docs |

---

## 3. 各タスクの詳細

### T1: `SmoothingOp` Literal + allow-list 拡張

**目的**: spec §8 step 1 — `"edited"` を許容値に追加し、後続タスクが
`smoothing_ops.append("edited")` できるようにする。

**手順 (TDD)**:
1. `tests/unit/test_schema*.py` (`_ALLOWED_SMOOTHING_OPS` を扱う既存
   ファイル) に failing test 追加:
   - **positive**: `SubtaskSegment(... smoothing_ops=["merge_same_label",
     "edited"], ...)` が `ValueError` を raise しない
   - **negative 保持**: 知らない op (`"random_op"`) は依然 `ValueError`
2. **3 箇所** lockstep update:
   - `mimicanno/smoother.py:28` の `SmoothingOp` Literal に `"edited"` 追加
   - `mimicanno/schema.py:132` の `SmoothingOpName` Literal にも `"edited"`
     を追加 (`SmoothingOp` と並行する別 alias、mypy --strict 時に検出される)
   - `mimicanno/schema.py:133-135` の `_ALLOWED_SMOOTHING_OPS` set に
     `"edited"` 追加
3. test green、既存テスト regression なし

**Verify**:
```bash
uv run pytest tests/unit/test_smoother*.py tests/unit/test_schema*.py -q
```

### T2: `Manifest.canonical_name` + `edited_at` + `to_dict`

**目的**: spec §3.3 + §5c — schema fan-out の writer 側。

**手順 (TDD)**:
1. `tests/unit/test_schema_manifest.py` (新規 or 既存ファイルに追記)
   に failing test:
   - `Manifest(..., canonical_name="ep0__abc", edited_at="2026-...")
     .to_dict()` が両 key を含む
   - `Manifest(...).to_dict()` (両 field None) が両 key を **含まない**
     (conditional emit; 既存 v3/v4 manifest と byte-identical)
2. `mimicanno/schema.py:353` 付近の `Manifest` dataclass に追加:
   ```python
   canonical_name: str | None = None
   edited_at: str | None = None
   ```
3. `to_dict()` (schema.py:381-403) を `SmootherConfig.to_dict` の
   conditional-emit 流儀で拡張
4. green 確認

**Verify**: 同上 + 個別 test 名 grep

### T3: `read_manifest` fallback + jsonschema 更新

**目的**: spec §3.3 reader-side fallback、io.py:150-199 を更新。

**手順 (TDD)**:
1. failing test:
   - 既存の Phase 5 A pre-r1 manifest fixture (e.g.
     `runs/so101_phase4_v5/episode_000000__*/manifest.json`) を読んで、
     `manifest.canonical_name == "episode_000000__..."`
     (= dir name fallback) になる
   - 新規 manifest (両 field 持ち) を読んで、両 field が dataclass に
     正しく入る
2. `io.py:150-199` の `return Manifest(...)` 構築箇所に追加:
   ```python
   canonical_name=raw.get("canonical_name") or path.parent.name,
   edited_at=raw.get("edited_at"),
   ```
3. `mimicanno/jsonschemas/manifest.schema.json` の `properties` に追加
   (`required` には入れない):
   ```json
   "canonical_name": {"type": ["string", "null"]},
   "edited_at":      {"type": ["string", "null"]}
   ```
4. 既存 manifest fixture (`tests/exports/fixtures/...` 等) が
   `_validate("manifest", raw)` で通り続けることを確認

**Verify**:
```bash
uv run pytest tests/io/ tests/exports/ -q
```

### T4: 4 つの Manifest construction sites で `canonical_name` 対応

**目的**: spec §3.3 — `Manifest.canonical_name` を最終的に正しい値で
disk に書き込む。grep 確認: `Manifest(` の構築箇所は **4 つ**:

- `mimicanno/publish.py` 内 (resolve 後の name を持つ)
- `mimicanno/pipeline.py:497` (pre-publish)
- `mimicanno/pipeline.py:1068` (pre-publish)
- `mimicanno/pipeline.py:1428` (pre-publish)

**設計判断**: pipeline.py の 3 サイトは **collision suffix が決まる前** に
Manifest を構築するので、`canonical_name=None` で良い。publish.py が
名前を resolve した後で manifest.json に `canonical_name` を確定値で
書き込む。**upsert は `file_lock` ブロック内** (publish.py:129-189)、
具体的には locked reuse-recheck (~line 134) の **後** + tmp→final
rename (line 165) の **前** で実行する。これで:
- write_artifacts の hash assertion (publish.py:121) は変更されない
  (`canonical_name` は to_dict の conditional emit で hash 入力に
  含まれないため、bare hash と post-upsert hash が一致しないと困る
  ような状況は起きない — もし to_dict が `canonical_name` を含めた
  ら hash assertion が破綻するので、T2 の conditional emit 設計の
  重要性が確認される)
- crash recovery: lock の中で upsert + rename だから atomic に近い
  単位、`.tmp.<pid>/` orphan は既存の scavenger が回収

**手順 (TDD)**:
1. failing test: 既存 `tests/integration/test_publish*.py` (or
   `tests/exports/` 系) で `publish` を回した後の disk manifest.json
   を読み:
   - `canonical_name == <expected dir name>` を assert
   - **post-upsert tmp manifest の hash が `req.run_hash` と一致** を
     assert (conditional emit が `canonical_name` を除外している不変
     条件を pin。T2 で conditional emit が regress した瞬間にこの test
     が落ちる)
2. pipeline.py の 3 サイトで `Manifest(..., canonical_name=None, ...)`
   を渡す (default だが explicit に)
3. publish.py の resolve-name 直後で `manifest_dict["canonical_name"] =
   resolved_name` を tmp manifest.json に upsert してから final rename。
   **コード comment 追加**: 「# upsert canonical_name post-write_artifacts;
   hash invariant (publish.py:121) は to_dict が canonical_name を
   conditional-emit する前提で成立」と記す (次の reader が困惑しない
   ため)
4. snapshot/golden test が conditional emit のおかげで壊れていなければ
   触らない、壊れたら確認後 update

**Verify**:
```bash
uv run pytest tests/integration/ -q -k "publish"
uv run pytest tests/ -q                       # 全 regression
```

### T4.5: `tests/server/conftest.py` の fixture 拡張

**目的**: 既存 `tmp_runs_root` (Phase 5 A の bytes-passthrough 用) は
manifest が minimal placeholder で `read_manifest` の schema 要件
(`inputs`, `time_base`, `fps`, `duration_sec`, `pipeline_status`,
`compat`, `model_versions`, `pipeline_params`) を満たさない。B の
PATCH writer は本物の `read_manifest`/`SubtaskSegment` reconstruct を
回すので、フル schema fixture が要る。

**手順**:
1. `tmp_runs_root_loadable` 新 fixture を追加 (既存 `tmp_runs_root`
   は触らない、A のテストが壊れないため)。
2. 中身: フル schema を満たす `manifest.json` (canonical_name 含む)、
   1 segment を持つ realistic `annotation.json`、対応する
   `boundaries.json` / `signals.json` / `tracks.json` placeholder、
   `index.json`。
3. 既存の SO101 v5 run (`runs/so101_phase4_v5/episode_000000__...`)
   から **明示 allow-list でファイルをコピー** して fixture 化:
   - copy: `manifest.json`, `annotation.json`, `boundaries.json`,
     `signals.json`, `tracks.json`
   - **skip**: `video.mp4` (allow-list 対象外、test tree 肥大)、
     `_vlm_dumps/` (runs_root レベル/ep レベル両方、debug artifact)、
     その他 unknown ファイル
   - `manifest.artifacts` から video 行を削除

**Verify**:
```bash
uv run --extra server pytest tests/server -q   # 既存 fixture も新 fixture も両方 OK
```

### T5: `labelset.py` + `GET /api/labelset` endpoint

**目的**: spec §3.1 GET /api/labelset。

**手順 (TDD)**:
1. failing test (`tests/server/test_labelset.py` 新規):
   - `GET /api/labelset` → 200、shape `{labels: [{id, requires_object}],
     labels_yaml_sha256}`
   - `ETag` header == `labels_yaml_sha256` (spec §5.1 #17)
   - `Cache-Control: public, max-age=300` (spec §3.1)
2. `mimicanno/server/labelset.py` (~30 LOC):
   ```python
   from mimicanno.labelset import load_label_set, LabelSet

   class LabelSetCache:
       """DI handle. Loads once at create_app; tests inject a
       precomputed LabelSet without touching disk."""
       def __init__(self, ls: LabelSet) -> None:
           self.ls = ls
       @classmethod
       def from_path(cls, path: Path) -> "LabelSetCache":
           return cls(load_label_set(path))
   ```
3. `mimicanno/server/routes.py` に GET route 追加 (path prefix が違うので
   登録順問わずだが、PATCH の前に置くのが慣例)
4. `create_app(..., labelset: LabelSetCache | None = None)` 引数追加。
   None 時は `mimicanno/configs/labels/manipulation.yaml` を load。
5. Cache-Control: spec §3.1 のとおり `public, max-age=300` を返す。
   この endpoint だけ A の `no-cache` policy と異なるのは意図的
   (labelset は server 起動中 immutable、ETag/`labels_yaml_sha256` で
   再起動時にバストできる)。

**Verify**: テスト 3 件 + 既存 server tests regression

### T6: `edit_repo.py` (write transaction)

**目的**: spec §3.2 の transaction 本体を pure-Python 化、FastAPI 抜きで
unit testable に。

**重要**: PATCH writer は `publish.publish()` を呼ばないこと。
`publish.py:121` の `produced_hash == req.run_hash` assertion は
auto-pipeline 用で、edit-derived hash は通らない。直接 `file_lock`
+ tmp + atomic replace + `runindex.upsert_row` で書く (spec §3.2)。

**手順 (TDD)**:
1. failing test (`tests/server/test_edit_repo.py`):
   - 入力: `tmp_runs_root` + segment_id + new_phase + If-Match
   - 期待: annotation.json / manifest.json / index.json が指定通り書き
     換わる、new_run_hash が `"sha256:" + sha256_hex_of_str(...)`、
     `annotation.run_hash == manifest.run_hash`、`generated_at` 不変、
     `manifest.edited_at` セット、`smoothing_ops.append("edited")` deduped
   - エラーケース: stale If-Match → `EtagMismatch` exception (HTTP
     mapping は T7 で)、`InvalidLabel` exception、`InvalidSegment` exception
2. `mimicanno/server/edit_repo.py` 実装 (~150 LOC):
   ```python
   def apply_edit(
       runs_root: Path, name: str, segment_id: str,
       new_phase: str, if_match: str, reviewer: str | None,
       labelset: LabelSet,
   ) -> dict[str, Any]:  # new manifest dict
       with file_lock(runs_root / "index.json.lock", timeout_sec=30):
           ... reread, validate, mutate, write-annotation, write-manifest, upsert-index ...
       return new_manifest_dict
   ```
3. 例外型は spec §3.6 のコードと 1:1 マップ:
   `EtagMismatch`, `EtagRequired`, `InvalidLabel`, `InvalidSegment`,
   `RunNotFound`
4. `_recompute_confidence` を使うため `SubtaskSegment` を再構築 (spec
   §3.2 step 4)

**Verify**:
```bash
uv run pytest tests/server/test_edit_repo.py -q
```

### T7: CORS + `create_app(reviewer=...)` (PATCH の前置工事)

**目的**: spec §3.4.2 + §3.6. T8 PATCH route が reviewer + PATCH
methods を使うので、wiring を先行整備する (旧計画は T7/T8 逆だった —
レビュー #2 で指摘修正)。

**手順 (TDD)**:
1. failing test: OPTIONS preflight from `Origin: http://localhost:5173`
   with `Access-Control-Request-Method: PATCH` → 200 +
   `Access-Control-Allow-Methods: GET, HEAD, PATCH, OPTIONS`
2. `mimicanno/server/app.py:24` の `allow_methods` を拡張
3. `create_app(*, runs_root: Path, cors_origins: list[str],
   reviewer: str | None = None, labelset: LabelSetCache | None = None)`
   **完全な kwarg list を pin**: 既存の `runs_root`/`cors_origins` も
   keyword-only として明示し、T11 race test や T9 unit test が fixture
   drift しないようにする
4. reviewer を `make_router` 経由で route に thread (route はまだ使わ
   ないが、wiring を T7 で完成)

**Verify**:
```bash
uv run --extra server pytest tests/server/test_app.py -q
```

### T8: PATCH route + body validation

**目的**: spec §3.1 PATCH。HTTP layer のみ、ロジックは T6 に委譲、
reviewer は T7 で thread 済み。

**手順 (TDD)**:
1. **spec §5.1 の 18 ケースのうち #17 (T5 済) / #13 (T11 race) / #16
   (T10b annotate-overwrite) を除く 15 ケースを enumerate**:
   - `tests/server/test_routes_patch.py` 新規作成
   - 各ケースは spec §5.1 番号と 1:1 対応 (test 名に番号 prefix を
     付けて trace 容易化)
2. PATCH route 実装 (`mimicanno/server/routes.py`):
   - 既存 GET artifact route の **前** に登録 (spec §3.4)
   - body parse (JSON only、それ以外 415)
   - body shape validation (`phase` key のみ許可、extra keys/non-str
     → 400 `invalid_body`)
   - If-Match header parse (欠時 428、不一致 412)
   - `edit_repo.apply_edit(...)` 呼び出し
   - 例外 → HTTP envelope mapping (spec §3.6 全コード)
   - 200 + new ETag + 新 manifest body
3. 全 15 ケース green

**Verify**:
```bash
uv run --extra server pytest tests/server/test_routes_patch.py -q
```

### T9: `serve_cmd` の env passthrough

**手順 (TDD)**:
1. failing test (**programmatic, not subprocess**): monkeypatch
   `os.environ["MIMICANNO_REVIEWER"]`、`from mimicanno.cli import
   serve_cmd` 内部で `create_app` 呼び出しを spy / mock し、reviewer
   引数が期待通り渡ったことを assert。subprocess 経路は T16 smoke
   のみ。
2. `mimicanno/cli.py` の `serve_cmd` で
   `reviewer = os.environ.get("MIMICANNO_REVIEWER") or None` を読んで
   `create_app(reviewer=reviewer)` に forward
3. 既存 `test_serve_cli.py` の subprocess test (T9 範囲外) は temporarily
   skip しない、env を渡さなければ既存 behaviour 維持

**Verify**: `uv run --extra server pytest tests/server/test_serve_cli.py -q`

### T10: server integration test (PATCH cycle)

**目的**: spec §5.2 #1 (real disk PATCH cycle)。

**手順 (`tmp_runs_root_loadable` fixture を使う)**:
1. PATCH happy path → 200、response body == new manifest、ETag 一致
2. **再 GET** `/api/runs/<name>/manifest.json` → ETag が response の
   ETag と一致、body の `run_hash` も同値
3. 旧 ETag で再 PATCH → 412 `etag_mismatch`
4. 新 ETag で別 segment を PATCH → 成功、annotation.json on disk で
   両 segment が edited、`smoothing_ops` deduped

各 step を 1 test に分割 (atomic test、failure mode が見やすい)。

### T10b: annotate-overwrites-edit short-circuit assertion

**目的**: spec §5.1 #16。Gemma/SAM3 を回さずに **publish.py の
short-circuit ロジックを直接** テスト。

**手順**:
1. PATCH を実行して edited annotation.json + `run_hash =
   "sha256:<edit-derived>"` を作る
2. `publish.py::_existing_run_hash(paths.final)` を直接呼び、
   返り値が edit-derived hash であることを assert
3. auto-pipeline が同じ episode で `compose_run_hash(config_hash,
   input_hash)` を計算した値と **disjoint** であることを assert
   (`config.py:835` の `compose_run_hash` を直接呼ぶ)
4. publish.py の reuse check ロジック (`existing == req.run_hash`) が
   False を返すことを assert
   → `force=False` でも annotate は短絡せず rewrite に走る、人手 edit
   が上書きされる挙動を pin

Gemma/SAM3 を回さないので fast & deterministic。

### T11: 並行 race test (uvicorn-in-process)

**目的**: spec §5.1 #13 (real concurrency)。

**実装メモ**:
- `tests/server/test_patch_concurrent.py` 新規
- `uvicorn.Config(app, host="127.0.0.1", port=<free_port>,
  loop="asyncio")` + `uvicorn.Server(config)` を別スレッドで `serve()`
- ready 判定: `/healthz` (Phase 5 A から存在、verified) に 0.1s 毎
  curl until 200
- teardown: `server.should_exit = True` + thread.join(timeout=5)、
  ハング時は `kill -KILL` (safety net)
- 2 つの `httpx.Client` を `ThreadPoolExecutor` で同時 PATCH
- 期待: 1 つ 200 + 1 つ 412

### T11.5: frontend testing deps install

**目的**: vitest は scaffolded だが `@testing-library/*` + `jsdom`
が無いので component test 不可。

**手順**:
1. `frontend/package.json` の `devDependencies` に追加:
   - `@testing-library/react`
   - `@testing-library/dom`
   - `@testing-library/user-event`
   - `jsdom`
2. `frontend/vitest.config.ts` に:
   - `test.environment = "jsdom"` 設定
   - **`test.include` glob に `.tsx` を含める** (現状 `*.test.ts` のみ
     のため、component test を `*.test.tsx` で書くと拾われない):
     `include: ["src/**/__tests__/**/*.test.{ts,tsx}"]`
3. `pnpm install`、既存 test (もしあれば) が通ることを確認

**Verify**: `cd frontend && pnpm test`

### T12: Frontend `?api=1` toggle infrastructure

**手順 (TDD)**:
1. failing test (vitest): `useApiToggle()` hook が `?api=1` のときに
   true を返す (`URLSearchParams(window.location.search)` 直読み、
   react-router 導入なし)
2. `frontend/src/lib/ApiToggleContext.tsx` 新規 (Context + Provider +
   hook)
3. `frontend/src/lib/manifest.ts` の fetch helper を base URL 切替対応
   (`useApi ? "/api/runs/" : "/runs/"`)
4. **`RunList.tsx` も同じく `runs/index.json` の fetch path を toggle**
   (`/runs/index.json` ↔ `/api/runs/index.json`)
5. `RunViewer.tsx` で Context 消費、phase dropdown rendering を gate

### T13: Frontend phase dropdown + PATCH client

**手順 (TDD)**:
1. failing test (vitest + testing-library): segment row の
   `<select>` で onChange → mocked PATCH 呼び出しが
   `If-Match: "<run_hash>"` 付きで発火
2. component 実装、`/api/labelset` fetch + cache、412 toast

### T14: Frontend vitest 3 ケース完成

spec §5.3 の 3 ケース:
- PATCH 発火 (T13 で完成)
- 412 path → toast + revert
- labelset fetch + cache

### T15: mypy + 全 regression

```bash
# server 範囲は明示 scope (existing baseline と整合)
uv run --extra server mypy mimicanno/server
# 全体は既存 baseline と diff があるか確認
uv run --extra server mypy mimicanno 2>&1 | grep "mimicanno/server\|mimicanno/io.py\|mimicanno/schema.py\|mimicanno/publish.py\|mimicanno/pipeline.py" || true
# テスト
uv run --extra server pytest tests/ -q
cd frontend && pnpm test
```

**Typing 注意点** (review で指摘):
- `Manifest.to_dict()` の戻り型は `dict[str, Any]` を維持 (新フィールド
  追加で narrow させない)
- `apply_edit` 戻り型: `dict[str, Any]` を pin
- `raw.get("canonical_name") or path.parent.name`: `or` は **空文字列
  でも fallback する** (`"" or x → x`)。空文字列の `canonical_name` を
  silent に dir name に置換すると debug 困難になるので、`isinstance`
  ガードで明示分岐:
  ```python
  val = raw.get("canonical_name")
  canonical_name = val if isinstance(val, str) and val else path.parent.name
  ```

すべて green。

### T16: 手動 smoke + results note

`runs/so101_phase4_v5/` で server 起動、curl + ブラウザ smoke:
- `MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve --runs-root runs/so101_phase4_v5 --cors-origin http://localhost:5173`
- `curl -X PATCH ... -H 'If-Match: "<run_hash>"' -d '{"phase":"grasp_object"}'`
- ブラウザで `?api=1` 開いて 3 segments の phase を変更、リロード後に
  persist 確認

→ `docs/superpowers/notes/2026-05-13-phase5-b-r1-results.md` に curl
出力 + screenshot links。

### T17: docs

- 既存 `README.md` の `## Server` セクションに PATCH + labelset endpoint
  を追記、`MIMICANNO_REVIEWER` 環境変数を documented
- `mimicanno/server/README.md` に:
  - write contract (annotation → manifest → index 順、crash-recovery
    シナリオ 3 ケース)
  - `?api=1` rollout note
  - 例外 mapping table (§3.6)

### T18: memory 更新

- `project_phase5_status.md`: B (r1) を SHIPPED に
- 新規 `project_phase5_b_r1_shipped.md`: PATCH 契約、ETag 楽観 lock、
  `edited_at` フィールド、release 2+ で何を扱うかの roadmap

---

## 4. 検証コマンド一覧

```bash
# 各タスク後
uv run --extra server pytest tests/server -q
uv run pytest tests/unit -q
uv run pytest tests/ -q --tb=no                # 全 regression (T15)

# mypy (T15)
uv run --extra server mypy mimicanno/server
uv run --extra server mypy mimicanno

# 手動 smoke (T16)
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
    --runs-root runs/so101_phase4_v5 \
    --cors-origin http://localhost:5173
```

---

## 5. リスクと留意

- **既存 manifest fixture の golden 破壊**: T2/T3 で `canonical_name`
  / `edited_at` 対応するが、conditional emit のおかげで既存 manifest
  byte-identical のはず。それでも `tests/exports/fixtures/` のような
  snapshot を持つ test がある場合、T4 で golden update が要る可能性。
  最初に grep して触る範囲を可視化しておく。
- **race test の flakiness**: T11 の uvicorn-in-process は
  ready/teardown のタイミング次第で flake する。`free_port` fixture
  + ready 判定 (`until httpx.get /healthz`) + `should_exit` クリーン
  シャットダウン + safety-net `kill -KILL` を必ず通す。
- **`_recompute_confidence` 依存**: T6 で smoother から import すると
  config/labelset chain が引きずられる。最小依存に保つため、formula
  だけ schema.py に lift する方が clean (実装時判断)。
- **frontend テスト基盤**: T11.5 で `@testing-library/*` + `jsdom`
  を install。`pnpm install` が要 (CI で `--frozen-lockfile` のとき
  は lockfile も更新)。
- **frontend ルーティング無し**: 現状の app は react-router を持たない
  ので、`?api=1` は `URLSearchParams(window.location.search)` 直読み
  で十分。Provider は `App.tsx` 直下に置く。
- **CORS preflight キャッシュ**: ブラウザは preflight を 600s キャッシュ
  する。dev 中に `--cors-origin` を変更しても反映遅延する場合あり。
  T16 smoke 時にハマったら DevTools の network disable cache を切る。
- **PATCH on edited run → annotate re-run の挙動**: spec §7 で documented、
  T10b の integration test で direct assert (Gemma 抜き)。
- **`pipeline.py` 3 サイトの `canonical_name`**: pre-publish 時点で
  collision suffix が未確定なので None を渡し、publish.py の
  resolve-name 後 + `file_lock` 内で tmp manifest に upsert する設計
  (T4)。upsert 位置は locked reuse-recheck と rename の間。
- **T10b の short-circuit test に必要な fixture**: edit 後の disk 状態
  + auto-pipeline 再走時の expected hash の両方を構築できる必要があ
  る。`tmp_runs_root_loadable` (T4.5) + `compose_run_hash` 直呼びで
  実現。
- **labelset endpoint の cache mismatch**: spec §3.1 で
  `Cache-Control: public, max-age=300` (5 分)。dev で labels yaml を
  swap → サーバ再起動しても browser cache 5 分残る。manual smoke 時
  に DevTools で cache 無効化。
- **ブランチ衛生**: memory `feedback_handoff_conflict_check` を必ず
  実施。並行作業 (Piper など) との衝突回避は T0 として暗黙の前提。
