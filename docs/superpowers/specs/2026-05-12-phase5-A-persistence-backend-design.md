# Phase 5 A — Persistence backend (read-only first release)

Date: 2026-05-12
Status: draft
Author: Claude (Opus 4.7) under Phase 5 autonomy directive (2026-04-30 →)

Related:
- Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md)
  §4.4 (runs/index.json + publish transaction), §4.7 (Phase 5 backend reference),
  §14 (MimicRec integration), §15 #17 (Phase 5 exit criterion)
- Parent Phase 5 spec: [`2026-04-30-mimicanno-phase5-export-design.md`](./2026-04-30-mimicanno-phase5-export-design.md) (sub-project A/B/C/D/E 分解)

---

## 1. Motivation

Phase 5 の 5 sub-project (A persistence / B edit UI / C parquet export /
D evaluation / E MimicRec integration) のうち **C のみ SHIPPED**、A/B/D/E は
未着手 (memory `project_phase5_status.md` 参照)。

B (Edit UI) は静的ファイル経由では実装できない (POST/PATCH を受ける主体が必要)。
D は B のログ依存、E は A の API shape に乗ると親 spec §14 にある。
よって **A は B/D/E すべての前提となる Phase 5 続行のクリティカルパス**。

ただし B のエンドポイント設計 (boundary drag, relabel, reviewed write 等) は
それ自体が独立 sub-project (Brainstorming 別途) であり、A 内で先取りすると
spec が肥大化する。本 sub-project は **read-only ファーストリリース** に
限定し、B の API は後続 PR で additive に積む。

## 2. Scope

In scope:
- FastAPI ベースの HTTP サーバ (uvicorn 起動、localhost dev のみ)
- 2 endpoints (manifest は artifact の特殊ケースで統合; parent spec §14):
  - `GET /api/runs/index.json` (静的 `runs/index.json` と同一 JSON shape)
  - `GET /api/runs/<canonical_name>/<artifact>` 例:
    `manifest.json`, `annotation.json`, `boundaries.json`, `signals.json`,
    `tracks.json` (**allow-list、後述 §3.3**)
- `GET /healthz` (uvicorn `--reload` 動作確認 + future E のヘルスチェック用)
- CORS allowlist (frontend dev server `http://localhost:5173` などを `--cors-origin` で指定)
- publish transaction (§4.4) の短い「dir 消失ウィンドウ」に対する **server-side**
  retry (3 回 / 100 ms バックオフ) → 失敗時 404
  (frontend の `fetchRetry.ts` は 404 のみ retry → server 側で 404 を返せば
  viewer 既存挙動と整合、503 を返すと viewer が即時 throw する)
- 404 エラーレスポンス契約 ({error, message} envelope、FastAPI default の `{detail}` を override)
- ETag ヘッダ (manifest レスポンスに `ETag: "<run_hash>"` を出して将来の B PATCH
  での `If-Match` 楽観ロックを breaking change なしで導入できるようにする)
- `uv run mimicanno serve` CLI コマンド (port / host / cors-origin オプション)
- pytest 統合テスト (FastAPI `TestClient`、tmp `runs/` ツリー)
- 依存追加は **`[server]` extra** として分離 (vlm/sam3 extra と同パターン)

Out of scope (それぞれ別 spec):
- **書き込み系エンドポイント** (B sub-project 別 spec で追加。本 PR は GET のみ)
- **認証 / multi-user / RBAC** (Phase 6+; localhost 単人前提)
- **MimicRec 側統合** (E sub-project 別 spec。ただし API shape は親 §14 と
  一致させ、E が同じエンドポイントを叩けるように設計する)
- **viewer の HTTP fetch 切り替え** (frontend 改修。本 spec は backend 側のみで、
  viewer は B sub-project で書き換え)
- **docker / systemd / Nginx reverse proxy** (Phase 6+)

「将来やる」リスト (out-of-scope だが design intent として記録):
- 書き込みエンドポイント (B 由来):
  - `PATCH /api/runs/<name>/segments/<segment_id>` — phase/object/reviewed 変更
  - `PATCH /api/runs/<name>/segments/<segment_id>/boundaries` — boundary drag
  - `POST /api/runs/<name>/lock` / `DELETE` — 編集ロック取得・解放
- 編集監査ログ (D 用): `human_edit_time`、`reviewer_id`
- annotate キュー (CLI ジョブの HTTP enqueue + status pull)
- 認証: JWT / OAuth、HTTPS、ロール
- デプロイ: docker compose、systemd unit、reverse proxy
- MimicRec replay 統合: 同 `/api/runs/*` を MimicRec の Replay page から消費

## 3. Design

### 3.1 モジュール構成

```
mimicanno/
  server/
    __init__.py
    app.py            # FastAPI app factory
    routes.py         # 3 endpoints + CORS middleware
    runs_repo.py      # runs/ ディレクトリ抽象 (path resolution + retry)
    errors.py         # HTTP-mappable error helpers
  cli.py              # 既存に + `serve` サブコマンド
```

`runs_repo.py` は I/O 副作用の単一窓口。テストで mock せず一時 dir を
使う方針 (テスト容易性 + 単純さ優先)。

### 3.2 サーバ起動 (`mimicanno serve`)

```bash
uv run mimicanno serve \
  --runs-root ./runs \
  --host 127.0.0.1 \
  --port 8000 \
  --cors-origin http://localhost:5173 \
  [--reload]   # dev 用
```

- `--runs-root` 必須 (CLI annotate と同じ意味)
- `--host` 既定 `127.0.0.1` (localhost-only)
- `--port` 既定 `8000`
- `--cors-origin` 複数指定可。**既定で空** (CORS 無効)。`--reload` でも
  自動許可はしない (CORS パスを一本化、ユーザが明示)
- `--reload` uvicorn の `reload=True` パススルー

内部実装: `app = create_app(runs_root, cors_origins)` → `uvicorn.run(app, ...)`。

### 3.3 Endpoints

#### `GET /api/runs/index.json`

- ディスク上の `<runs_root>/index.json` を読み、UTF-8 JSON で返す
- 実装は `mimicanno.runindex.read_index` を使う (`runindex.py:32-37`)
- 書き込み側は `tmp.replace(path)` で atomic (`runindex.py:45-47`) なので
  torn read は起きない → **ロック取得しない**
- Content-Type: `application/json`
- 404: ファイル無し → `{"error":"index_missing"}`
- 200 + 空: `{"schema_version": ..., "runs": []}` のとき (空 runs/ 環境) は
  正常レスポンス (テスト 4.1 #11)

#### `GET /api/runs/<canonical_name>/<artifact>` (manifest 含む統合)

manifest は artifact の特殊ケースなので 1 ルートに統合。

- `<artifact>` は **allow-list** で制限:
  `{"manifest.json", "annotation.json", "boundaries.json",
    "signals.json", "tracks.json"}`
  以外は 404 `artifact_not_found` (video や parquet は対象外、symlink
  経由の漏えいリスクも allow-list で root cause 排除)
- `<canonical_name>` 検証: `^[a-zA-Z0-9_]+$` のような寛い regex で
  事前 reject、url-decode 後の値で評価 (`%2F` 経由トラバーサルも遮断)
- パストラバーサル防御 (二段):
  1. canonical_name pattern check
  2. `(runs_root / name / artifact).resolve(strict=False).is_relative_to(runs_root.resolve())`
- ETag (manifest.json のみ): `manifest.run_hash` を `ETag: "<hash>"` として
  emit (将来の B PATCH の `If-Match` 用)。他 artifact は emit しない
- Cache-Control: `no-cache` (B が PATCH を入れたとき stale を見せない)
- mime type: `.json` → application/json

#### `GET /healthz`

- 200 OK + `{"status":"ok","runs_root":"<path>"}` の単純 JSON
- runs_root が存在しなければ 500 (起動構成の自己診断)

#### Publish-in-progress dir-gap の扱い (parent §4.4 / publish.py:127-189)

publish 中の実時序 (`publish.py` 確認結果):
1. `runs/<name>/` → `runs/<name>.bak/` rename (atomic)
2. `runs/<name>.tmp.<pid>/` → `runs/<name>/` rename (atomic)
3. `rm -rf runs/<name>.bak/`

ステップ 1-2 間が**短い dir-gap window** (実時間で ms オーダー)。
リーダーが `runs/<name>/manifest.json` を読みに行くと `FileNotFoundError`。

サーバ側 retry 方針:
- artifact GET の `FileNotFoundError` 検出時、**100 ms sleep × 3 回**まで
  内部 retry してから 404 を返す
- 503 を選ばないのは、frontend の `fetchRetry.ts:11` が 404 のみ retry
  する実装で、503 は即 throw されるため (viewer 既存挙動との整合性優先)
- 同じ理由で `index.json` GET でも同じ retry を入れる (将来 index の
  rewrite が長くなった場合の保険)

### 3.4 ファイル不変条件 (publish §4.4 との契約)

| 不変条件 | 保証する側 | 根拠 |
|---|---|---|
| `index.json` の write は atomic (`tmp.replace`) | CLI publish | `runindex.py:45-47` |
| publish dir-gap は ms オーダー | CLI publish | `publish.py:127-189` (rename 2 回) |
| publish 中は `runs/index.json.lock` を最大 30s 保持 | CLI publish | `publish.py:27` `LOCK_TIMEOUT_SEC=30` |
| 読み取りはロック取らない | server | §3.3 (atomic write 前提で torn read 不能) |
| 読みは allow-list の固定 5 ファイルのみ | server | §3.3 |

将来 B (Edit UI) が PATCH を入れるときも、`tmp.replace` semantics を守る
限り server は **読み取りロック不要**のまま据え置ける (将来 spec のために
明文化)。

### 3.5 CORS

`fastapi.middleware.cors.CORSMiddleware`:
- `allow_origins` = `--cors-origin` で渡された値リスト
- `allow_methods` = `["GET"]` (read-only)
- `allow_headers` = `["*"]`
- `allow_credentials` = False (本 PR は cookie 不要)

### 3.6 エラーモデル

FastAPI default の `{"detail": "..."}` を **override**。`app.add_exception_handler`
で `HTTPException` をカスタム handler に通し、以下の shape で emit:

```json
{ "error": "<code>", "message": "<human-readable>" }
```

| HTTP | code | when |
|---|---|---|
| 404 | `index_missing` | runs/index.json 不在 |
| 404 | `run_not_found` | canonical_name の dir 無し (retry 後も解消せず) |
| 404 | `artifact_not_found` | artifact が allow-list 外、または dir 内に無し |
| 400 | `invalid_name` | canonical_name regex 不一致 |
| 500 | `internal` | 想定外例外 (stack trace は body に出さない) |

**注**: spec ドラフト初稿の 503 `publish_in_progress` は frontend の
`fetchRetry.ts:11` が 404 のみ retry する実装と非整合だったので削除。
server 側で 100ms × 3 retry してから 404 に丸める方針に変更 (§3.3 末尾)。

### 3.7 ロギング

- access log: uvicorn 標準 (INFO 行 / リクエスト)
- application log: `logging.getLogger("mimicanno.server")` で INFO
  (publish_in_progress 503 は WARNING、500 は ERROR + stack)

### 3.8 「将来やる」 (out-of-scope 詳細)

**書き込みエンドポイント (B 由来、別 spec)**

```
PATCH /api/runs/<name>/segments/<segment_id>
  body: { phase?, object?, target?, reviewed?, reviewer_id? }
  semantics: optimistic write with run_hash precondition + index.json.lock 取得
  test: 同時編集の last-writer-wins ではなく conflict 検出
```

```
PATCH /api/runs/<name>/segments/<segment_id>/boundaries
  body: { start_time?, end_time?, source_addition?, ... }
```

```
POST   /api/runs/<name>/lock     → 編集ロック取得 (TTL 5min)
DELETE /api/runs/<name>/lock
```

**MimicRec 統合 (E 由来、別 spec)**

- MimicRec Replay page の動的読み取り経路を `GET /api/runs/<name>/manifest.json`
  に差し替え。同 endpoint なので shape 互換、追加実装不要 (Replay 側変更のみ)
- `save_annotations` (MimicRec) を `PATCH /api/runs/<name>/segments/<id>`
  経由に切り替え (要 B 完了)

**認証 / multi-user**

- まず JWT bearer (簡単な reviewer_id 同定) → OAuth (GH/Google)
- HTTPS は reverse proxy 側 (Nginx / Caddy) で終端
- ロール: viewer / reviewer / admin

**デプロイ形態**

- `docker compose` 1 ファイルで dev も prod も統一
- `systemd` unit (server, web frontend, scavenger)
- reverse proxy (Caddy 推奨、Let's Encrypt 自動)

## 4. Test plan

### 4.1 単体 (`tests/server/test_routes.py`)

`fastapi.testclient.TestClient` を使い、`tmp_path` に最小限の runs/ ツリーを
作って各エンドポイントをテスト:

1. `GET /api/runs/index.json` → 200 + JSON 形 (mock index.json)
2. 同上 → 404 `index_missing` (`index.json` 不在)
3. **空 index** (`{schema_version:..., runs:[]}`) → 200 + `runs:[]`
4. `GET /api/runs/<name>/manifest.json` → 200 + manifest 内容 + `ETag: "<run_hash>"`
5. `GET /api/runs/<name>/manifest.json` → 404 `run_not_found` (dir 不在)
6. `GET /api/runs/<name>/boundaries.json` → 200 + バイト一致
7. `GET /api/runs/<name>/video.mp4` → 404 `artifact_not_found` (allow-list 外)
8. `GET /api/runs/<name>/missing.json` → 400 `invalid_name` or 404 (allow-list ベース)
9. **パストラバーサル (literal)**: `GET /api/runs/<name>/../../etc/passwd`
   → 400 `invalid_name`
10. **パストラバーサル (percent-encoded)**:
    `GET /api/runs/<name>/..%2F..%2Fetc%2Fpasswd` → 400 / 404
11. **symlink 経由の escape**: `runs/<name>/manifest.json` を `/etc/passwd`
    への symlink にしておく → 404 `artifact_not_found` (allow-list 通っても
    `resolve()` で `is_relative_to(runs_root)` 失敗で reject)
12. **truncated JSON** (`{"schema_version":` で終わる) → 500 `internal`、
    response body に stack trace を含まない
13. **dir-gap simulation**: `monkeypatch` で `Path.read_bytes` に
    `FileNotFoundError` を最初 2 回 raise させてから OK → 200 (server retry が機能)
14. **dir-gap 持続**: 3 retry 失敗 → 404 `run_not_found`
15. CORS preflight: `OPTIONS /api/runs/index.json` の `Origin: localhost:5173`
    が 200 + 適切な `Access-Control-Allow-*` ヘッダ (allowlist 設定済)
16. `--cors-origin` 未指定 → CORS 無効 (preflight no allow-origin header)
17. CORS 不許可 origin → preflight に allow-origin header 出ない
18. `GET /healthz` → 200 + `{status:"ok", runs_root:"..."}`
19. **HEAD request**: `HEAD /api/runs/<name>/manifest.json` → 200 + 同 ETag (body 空)
20. **大きい artifact** (10 MB+ の tracks.json) → `FileResponse` でストリーム
    される (body 量 == file size、メモリにロードされない)

### 4.2 統合 (`tests/server/test_serve_cli.py`)

- `uv run mimicanno serve --runs-root <tmp>` をサブプロセス起動、httpx で
  全 endpoint を叩き、200 + shape を検証
- SIGTERM で graceful shutdown 確認

### 4.3 並行性 (`tests/server/test_concurrent_publish.py`)

- スレッドで `runs/<name>/` を `<name>.bak` rename → tmp rename を回しつつ、
  別スレッドで `GET /api/runs/<name>/manifest.json` を 100 回叩く
- 期待: 全レスポンスが 200 か 404、500 や torn JSON は出ない

### 4.3 ロード (本 PR では out)

将来書き込みエンドポイントが入ったときに locust / k6 で同時編集の楽観
ロック挙動を検証する。今 PR では out of scope。

## 5. Backward compatibility

- 既存 frontend (Phase 1-3 viewer) は静的 `runs/index.json` を読む。本サーバの
  追加で既存挙動は変わらない (`mimicanno serve` を起動するかどうかは任意)
- `runs/index.json` ファイル形式は不変 (parent §4.4 と同一)
- annotate CLI / 既存テストへの影響なし

## 6. Exit criteria

1. `uv run mimicanno serve --runs-root <非空 runs/>` で localhost:8000 が
   立ち上がり、`curl /api/runs/index.json` が 200 + 既知の run list を返す
2. 単体テスト 20 ケース (§4.1) + 統合テスト (§4.2) + 並行テスト (§4.3) 全 green
3. パストラバーサル (literal / percent-encoded / symlink escape) を全て遮断
4. publish dir-gap simulation で server retry が 200 を返し、retry 失敗時のみ 404
5. CORS allowlist 指定時のみ preflight 通る、未指定なら allow-origin header なし
6. 既存 unit test suite 全 green (回帰なし)
7. `manifest.json` レスポンスに `ETag: "<run_hash>"` ヘッダが出る (B PATCH 前提)
8. `mypy --strict` パス (`pyproject.toml:94-97` の既存設定で server モジュール含めて clean)
9. `uv sync` 既定の依存ツリーが膨らまない (`[server]` extra 化、§7)
10. notes `2026-05-12-phase5-a-results.md` に手動 smoke 結果と `curl` 例

## 7. Risks & follow-ups

- **「将来 B が書く」と前提した API shape の早すぎる決定**: 本 PR は GET のみ
  なので shape は parent §14 と完全一致でリスクほぼゼロ。manifest に
  ETag を仕込んでおくことで B の `If-Match` 楽観ロックを breaking change
  なしで導入可能
- **uvicorn `--reload` の挙動**: ファイル監視で server が再起動する瞬間に
  リクエストが落ちるが、dev 専用なので許容
- **dir-gap retry テストの時序再現**: 実時序テストは並行スレッドで実 rename
  を回す統合テスト (§4.3)。それと別に `monkeypatch` で `FileNotFoundError`
  注入する単体 (§4.1 #13-14) も入れる
- **パストラバーサル防御**: allow-list (固定 5 ファイル) + canonical_name
  pattern check + `resolve().is_relative_to(runs_root)` の三段。symlink 経由
  の escape は `resolve()` で展開後判定するので allow-list を通っても
  `is_relative_to` で reject される
- **MimicRec (E) との API shape 互換**: 本 PR で出した GET shape を `/api/runs/...`
  そのまま MimicRec の Replay page から叩けるはずだが、smoke レベルでの
  shape 一致確認は E sub-project の最初の task で行う (本 PR では out)
- **case-insensitive FS / macOS HFS+**: 本リリースは Linux dev box のみを想定。
  macOS で動かす場合 canonical_name 比較が緩くなる懸念はあるが Phase 6+ の
  デプロイ spec で扱う
- **viewer の HTTP 切り替え**: 本 PR では viewer は静的 fetch のまま据え置く
  ため server は B 着手まで dead code。これは意図的 (B sub-project で
  Vite proxy 経由の HTTP 切り替えを実施)

## 7.5 依存追加 (詳細)

`pyproject.toml` に **新規 optional extra `[server]`** を追加 (vlm/sam3 と同パターン):

```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.30,<1",
]

[dependency-groups]
dev = [
    # 既存に加えて:
    "httpx>=0.27,<1",
]
```

- **base には足さない**: torch/transformers の重い依存と並べると `uv sync`
  既定が遅くなるため
- `uv sync --extra server` でサーバ依存を取得、`mimicanno serve` 実行時に
  fastapi が見つからなければ「`uv sync --extra server` を実行してください」
  という分かりやすいエラーで CLI を fail させる
- `httpx` は test のみ (`TestClient` 内部依存だが dev に明示しておく)
- 既存テスト suite (798 passed) が server extra なしで通り続けることを CI で守る

## 8. Implementation order (for the plan)

1. `pyproject.toml` に `[server]` extra + dev httpx 追加、`uv sync --extra server`
2. `mimicanno/server/__init__.py` (空)
3. `mimicanno/server/errors.py` (HTTP exception helpers + custom envelope)
4. `mimicanno/server/runs_repo.py` + 単体テスト (path resolution + allow-list + retry)
5. `mimicanno/server/routes.py` + 単体テスト (2 endpoints + /healthz + CORS + ETag)
6. `mimicanno/server/app.py` (FastAPI factory + 例外 handler 設定)
7. `mimicanno/cli.py` に `serve` サブコマンド追加 + 統合テスト (subprocess + httpx)
8. 並行テスト (`tests/server/test_concurrent_publish.py`)
9. `mypy --strict` パス確認
10. README / docs に server セクション追記
11. 手動 smoke: `runs/so101_phase4_v5/` を root に立ち上げ、curl で endpoint 確認
12. notes 作成、memory 更新
