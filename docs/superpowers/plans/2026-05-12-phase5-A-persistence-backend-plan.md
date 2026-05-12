# Phase 5 A — Persistence backend (read-only) plan

Date: 2026-05-12
Status: draft
Spec: [`../specs/2026-05-12-phase5-A-persistence-backend-design.md`](../specs/2026-05-12-phase5-A-persistence-backend-design.md)
Branch: `feat/phase4-smoother-source-aware-merge` (smoother sub-project がマージ後に
新ブランチ `feat/phase5-a-persistence-backend` を切る予定)

---

## 0. ゴール

spec §6 の exit criteria 10 項目を満たす:

1. `uv run mimicanno serve --runs-root <非空 runs/>` で localhost:8000 起動、
   `curl /api/runs/index.json` が 200 を返す
2. 単体 20 + 統合 + 並行 全 green
3. パストラバーサル全攻撃を遮断 (literal/percent/symlink)
4. publish dir-gap retry 成功 + 持続失敗時のみ 404
5. CORS allowlist 厳格 (allowlist 指定時のみ preflight 通る)
6. 既存 unit suite 全 green (回帰なし)
7. manifest 応答に `ETag: "<run_hash>"`
8. `mypy --strict` clean
9. base 依存膨らまない (`[server]` extra 化)
10. notes 作成 + memory 更新

---

## 1. 原則

- **TDD**: 各 task 「失敗するテスト → 実装 → green」
- **1 task = 1 commit** (PR-able)
- **検証は uv 経由** (`uv run pytest ...`, `uv run mimicanno serve ...`)
- **既存挙動を絶対に壊さない**: server 未起動 / `[server]` extra 未取得時の
  既存 CLI 挙動完全保持。base 依存 ([dependencies]) は触らない
- **viewer (frontend) は本 plan で変更しない** (spec §7、B sub-project で扱う)

---

## 2. タスク分解

| # | タスク | 出力 | 依存 |
|---|---|---|---|
| T1 | `pyproject.toml` に `[server]` extra + dev httpx 追加、`[[tool.mypy.overrides]]` に fastapi/uvicorn/starlette、`uv sync --extra server` で取得確認 | `pyproject.toml`, `uv.lock` | - |
| T2 | `mimicanno/server/__init__.py` (空) + `mimicanno/server/errors.py` (`MimicAnnoHTTPError` + `{error,message}` envelope + 汎用 `Exception` handler for 500 no-stack) + 単体テスト | `errors.py`, `tests/server/test_errors.py` | T1 |
| T2.5 | `tests/server/conftest.py`: 共有 fixtures (`tmp_runs_root` で index.json + manifest.json + 他 artifacts、`make_app` factory、`free_port`) | `tests/server/conftest.py` | T2 |
| T3 | `mimicanno/server/runs_repo.py`: allow-list + canonical_name regex + `resolve().is_relative_to` + 100ms×3 retry **(index と artifact 両方)** + path/etag タプル返却 + 単体 | `runs_repo.py`, `tests/server/test_runs_repo.py` | T2.5 |
| T4 | `mimicanno/server/routes.py`: 2 GET + /healthz + **manifest は bytes (ETag 用) / 他 artifact は `FileResponse` ストリーミング** + Cache-Control + WARNING/ERROR ログ (spec §3.7) + 単体 (CORS 抜きで 17 ケース) | `routes.py`, `tests/server/test_routes.py` | T3 |
| T5 | `mimicanno/server/app.py`: FastAPI factory + CORS middleware + exception handler 配線 + CORS 単体 (preflight allow/未指定/不許可 = 3 ケース) | `app.py`, `tests/server/test_app.py` | T4 |
| T6 | `mimicanno/cli.py` に `serve` サブコマンド (Typer) + 統合テスト (subprocess + free port + cleanup) | `cli.py`, `tests/server/test_serve_cli.py` | T5 |
| T7 | 並行性テスト: `publish.py` の実 rename 列 (bak rename → tmp rename → rmtree) を thread で回しつつ 100 req | `tests/server/test_concurrent_publish.py` | T6 |
| T8 | `mypy --strict` (`uv run --extra server mypy mimicanno/server`) clean + `uv run pytest tests/` 全 green (回帰ゼロ) | テスト結果 | T7 |
| T9 | README に server セクション追記 + `mimicanno/server/README.md` (内部開発者向け) | docs 差分 | T8 |
| T10 | 手動 smoke: `runs/so101_phase4_v5/` を root に立ち上げ、curl で全 endpoint を叩いて kill + notes | `docs/superpowers/notes/2026-05-12-phase5-a-results.md` | T9 |
| T11 | memory 更新 (`project_phase5_status.md` の A を「shipped」へ、新 `project_phase5_a_shipped.md` 追加) | memory diff | T10 |

---

## 3. 各タスク詳細

### T1: `[server]` extra 追加

**変更**: `pyproject.toml`

```toml
[project.optional-dependencies]
server = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.30,<1",
]

[dependency-groups]
dev = [
    # 既存 + 以下:
    "httpx>=0.27,<1",
]

[[tool.mypy.overrides]]
module = ["fastapi.*", "fastapi", "uvicorn.*", "uvicorn", "starlette.*"]
ignore_missing_imports = true
```

**手順**:
1. 既存の `[project.optional-dependencies]` セクションを確認 (vlm/sam3 と同パターン)
2. `[server]` 追加
3. `[[tool.mypy.overrides]]` で fastapi/uvicorn/starlette を `ignore_missing_imports`
   (uvicorn は types-uvicorn が無く、starlette も部分的)
4. `uv sync --extra server` 実行 → `uv.lock` 更新
5. base sync (`uv sync` 単独) が server なしで通ること確認

**Verify**:
```bash
uv sync                                              # base: server 依存無し
uv sync --extra server                               # server 取得
uv run --extra server python -c "import fastapi; print(fastapi.__version__)"
```

### T2: `errors.py` + 例外 envelope

**目的**: spec §3.6 の `{error, message}` shape。FastAPI default `{detail}` を override。
500 系では stack をレスポンスボディに含めない。

```python
# mimicanno/server/errors.py
class MimicAnnoHTTPError(Exception):
    def __init__(self, *, status: int, code: str, message: str) -> None:
        ...

def install_handlers(app: FastAPI) -> None:
    """Register custom handlers:
    - MimicAnnoHTTPError → {error, message} with status
    - HTTPException → {error: 'http_<status>', message: detail}
    - Exception (generic catchall) → 500 {error:'internal', message:'unexpected'},
      log the stack via _LOG.exception but do NOT leak it to the response body
    """
    ...
```

**Tests (`tests/server/test_errors.py`)**:
- 直接 `raise MimicAnnoHTTPError(...)` を投げる minimal route で response shape を pin
- `HTTPException` 直 raise でも同 shape に丸まる
- 想定外例外 (e.g. `raise RuntimeError("boom")`) → 500、body に "boom" / "Traceback"
  が含まれない
- WARNING / ERROR ログが正しく出る (caplog 確認)

### T2.5: `tests/server/conftest.py` 共有 fixtures

```python
# tests/server/conftest.py
import json, socket
from pathlib import Path
import pytest

@pytest.fixture
def tmp_runs_root(tmp_path: Path) -> Path:
    """Build a minimal runs/ tree with index.json + 1 run dir + all 5 artifacts."""
    root = tmp_path / "runs"
    root.mkdir()
    name = "episode_000000__abc123"
    rd = root / name
    rd.mkdir()
    manifest = {
        "schema_version": "0.2.0", "run_hash": "sha256:dead1234",
        "episode_id": "episode_000000", "artifacts": [...],
    }
    (rd / "manifest.json").write_text(json.dumps(manifest))
    for f in ("annotation.json","boundaries.json","signals.json","tracks.json"):
        (rd / f).write_text("{}")
    index = {"schema_version": "0.1.0", "runs": [{"canonical_name": name, ...}]}
    (root / "index.json").write_text(json.dumps(index))
    return root

@pytest.fixture
def free_port() -> int:
    """Return a port the OS just said is free. Avoids hardcoded 8000 collisions
    in CI / multi-test runs."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

### T3: `runs_repo.py` (リポジトリ抽象)

```python
class RunsRepository:
    def __init__(self, root: Path): self.root = root.resolve()

    def read_index(self) -> bytes:
        """Retry 100ms × 3 on FileNotFoundError, then raise
        MimicAnnoHTTPError(404, 'index_missing')."""

    def open_artifact(self, name: str, artifact: str) -> tuple[Path, bytes | None]:
        """allow-list + traversal guard + retry.

        Returns (resolved_path, manifest_bytes_or_None).
        - For 'manifest.json' the bytes are also returned so the route can
          compute the ETag without re-reading.
        - For other artifacts only the resolved Path is returned so the
          route can stream via FileResponse (spec §4.1 #20 large-file
          streaming requirement).
        """

ARTIFACT_ALLOWLIST: frozenset[str] = frozenset({
    "manifest.json", "annotation.json",
    "boundaries.json", "signals.json", "tracks.json",
})
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
```

retry ロジック:
```python
def _read_with_retry(path: Path) -> bytes:
    for _ in range(3):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            time.sleep(0.1)
    raise MimicAnnoHTTPError(404, "run_not_found", ...)
```

**Tests (`tests/server/test_runs_repo.py`)**:
- allow-list 通る → 正常 (path + bytes for manifest, path only otherwise)
- allow-list 外 (e.g. `video.mp4`) → 404 `artifact_not_found`
- canonical_name regex 不一致 → 400 `invalid_name`
- symlink で root 外を指す → 404 `artifact_not_found` (resolve + is_relative_to)
- `FileNotFoundError` 注入 (`monkeypatch`) 2 回 → 3 回目で OK → bytes 返却
- `FileNotFoundError` 注入 3 回連続 → 404 `run_not_found`
- index.json 不在 → retry 3 回後 404 `index_missing` (Cat 1 #3 反映)

### T4: `routes.py` (2 endpoints + /healthz)

```python
from typing import Any, cast
import json
from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api")

@router.get("/runs/index.json")
def get_index(repo: RunsRepository = Depends(get_repo)) -> Response:
    return Response(content=repo.read_index(), media_type="application/json")

@router.get("/runs/{name}/{artifact}")
def get_artifact(name: str, artifact: str, repo=Depends(get_repo)) -> Response:
    path, manifest_bytes = repo.open_artifact(name, artifact)
    headers = {"Cache-Control": "no-cache"}
    if artifact == "manifest.json":
        assert manifest_bytes is not None
        # mypy --strict friendly: cast then isinstance-guard
        parsed = cast(dict[str, Any], json.loads(manifest_bytes))
        rh = parsed.get("run_hash")
        if isinstance(rh, str):
            headers["ETag"] = f'"{rh}"'
        return Response(content=manifest_bytes, headers=headers,
                        media_type="application/json")
    # Other artifacts: stream via FileResponse so 10MB+ tracks.json doesn't
    # load into memory (spec §4.1 #20).
    return FileResponse(path, headers=headers, media_type="application/json")

@app.get("/healthz")
def healthz(): return {"status": "ok", "runs_root": str(runs_root)}
```

**Tests (`tests/server/test_routes.py`)** — CORS 抜きで 17 ケース
(CORS は T5 で middleware と一緒にテスト):

1-3 (index): 200 / 404 / 空 index
4-7 (artifact): 200 + ETag (manifest) / 404 run / 404 video.mp4 (allow-list 外)
8-11 (security): invalid_name / percent-encoded / literal `..` / symlink escape
12 (truncated JSON): 500、body に "Traceback" 含まれない
13-14 (dir-gap): retry 成功 / retry 失敗
15 (/healthz)
16 (HEAD): 200 + 同 ETag、body 空
17 (large file 10MB+ streaming): FileResponse 経由を確認 (response.stream の
   chunked transfer property)

### T5: `app.py` (FastAPI factory) + CORS テスト

```python
def create_app(*, runs_root: Path, cors_origins: list[str]) -> FastAPI:
    app = FastAPI(title="mimicanno persistence", openapi_url=None)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "HEAD"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    install_handlers(app)
    app.include_router(make_router(runs_root))
    return app
```

**Tests (`tests/server/test_app.py`)**:
- endpoint reachability (`TestClient(create_app(runs_root=tmp, cors_origins=[]))`)
- CORS preflight allow (origin = `http://localhost:5173`、allowlist 設定済)
- CORS 未指定 → preflight に allow-origin header 出ない
- CORS 不許可 origin → preflight に allow-origin header 出ない

### T6: CLI `serve`

```python
# mimicanno/cli.py に追加
@app.command("serve")
def serve_cmd(
    runs_root: Path = typer.Option(..., "--runs-root", exists=True, ...),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    cors_origin: list[str] = typer.Option(
        None, "--cors-origin",  # Typer convention for list defaults
        help="CORS allowed origin(s); repeatable.",
    ),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    origins = cors_origin or []
    try:
        from mimicanno.server.app import create_app
    except ImportError:
        typer.echo("FastAPI not installed. Run: uv sync --extra server", err=True)
        raise typer.Exit(2)
    import uvicorn
    app = create_app(runs_root=runs_root, cors_origins=origins)
    uvicorn.run(app, host=host, port=port, reload=reload)
```

**統合テスト (`tests/server/test_serve_cli.py`)**:
- `free_port` fixture で空きポート確保 → `subprocess.Popen(["uv","run","--extra","server","mimicanno","serve","--runs-root",...,"--port",str(port)])`
- ready 判定: `until httpx.get(f"http://127.0.0.1:{port}/healthz")` を 0.1s ループ (最大 10s)
- `httpx.get` で各 endpoint 200 確認
- `subprocess.terminate()` (SIGTERM) → `.wait(timeout=5)` で graceful shutdown
- **finally で必ず kill** (timeout 内に終わらなければ `.kill()`)

### T7: 並行性テスト

`publish.py:141-165` の実時序 (bak rename → tmp rename → rmtree) を thread で再現:

```python
def test_concurrent_publish_no_500(tmp_runs_root):
    """Replicate publish.py:141-165 real sequence:
      1. runs/<name>/        → runs/<name>.bak/  (rename)
      2. runs/<name>.tmp.N/  → runs/<name>/      (rename)
      3. rm -rf runs/<name>.bak/
    Race against 100 GET /api/runs/<name>/manifest.json.
    Expect: every response is 200 or 404, never 500 (= server-side retry/error
    handling holds under real rename gap)."""
    from mimicanno.server.app import create_app
    app = create_app(runs_root=tmp_runs_root, cors_origins=[])
    client = TestClient(app)
    name = "..."
    # thread 1: race publish renames
    # thread 2: 100 GETs
    ...
```

### T8: mypy strict + 回帰

```bash
uv run --extra server mypy mimicanno/server   # --strict は pyproject 既設定
uv run --extra server pytest tests/ -q
```

両方 clean / 全 green。`--extra server` 必須 (fastapi 型が見つからないと
`error: Library stubs not installed for "fastapi"` で落ちる)。

### T9: docs

- README.md にトップレベルセクション `## Server (Phase 5 A)` を追加
- `mimicanno/server/README.md` を新設 (内部開発者向け: アーキテクチャ + テスト走らせ方)

### T10: 手動 smoke + results note

```bash
# 起動 (background) — finally で kill するのを忘れない
uv run --extra server mimicanno serve --runs-root runs/ \
    --cors-origin http://localhost:5173 &
SERVE_PID=$!
trap "kill $SERVE_PID 2>/dev/null; wait $SERVE_PID 2>/dev/null" EXIT

# ready 待ち
until curl -sf http://127.0.0.1:8000/healthz > /dev/null; do sleep 0.1; done

# smoke
curl -sf http://127.0.0.1:8000/healthz
curl -sf http://127.0.0.1:8000/api/runs/index.json | jq '.runs | length'
NAME=$(curl -s http://127.0.0.1:8000/api/runs/index.json | jq -r '.runs[0].canonical_name')
curl -i http://127.0.0.1:8000/api/runs/$NAME/manifest.json | grep ETag
curl -sf http://127.0.0.1:8000/api/runs/$NAME/boundaries.json | jq 'keys'
# CORS preflight
curl -i -X OPTIONS \
    -H "Origin: http://localhost:5173" \
    -H "Access-Control-Request-Method: GET" \
    http://127.0.0.1:8000/api/runs/index.json | grep -i access-control

# clean exit
kill $SERVE_PID
```

results note (`docs/superpowers/notes/2026-05-12-phase5-a-results.md`):
起動時間、各 endpoint レスポンス、ETag 値、CORS 動作、curl 出力サンプル。

### T11: memory 更新

- `project_phase5_status.md`: A を `**SHIPPED (2026-05-12)**` に更新
- 新規 `project_phase5_a_shipped.md`: server エンドポイント仕様、`[server]` extra
  取得方法、B/E が前提として依存する事実

---

## 4. 検証コマンド一覧

```bash
# 各タスク後
uv run pytest tests/server -q
uv run pytest tests/ -q --tb=short   # 回帰 (T8)

# mypy (T8)
uv run mypy --strict mimicanno/server

# 手動 smoke (T10)
uv run mimicanno serve --runs-root runs/ --cors-origin http://localhost:5173
```

---

## 5. リスクと留意

- **fastapi バージョン pinning**: 0.115+ で `lifespan` API が新しめ。
  既存テスト pyproject の python>=3.11 制約と互換確認 (FastAPI 0.115 は OK)
- **uv.lock 肥大**: server extra 取得時のみ lock に lazy 解決される確認
- **TestClient + lifespan**: FastAPI 0.115 では TestClient が lifespan を
  走らせる。本 app は lifespan を使わないので副作用無しのはずだが、テスト
  で startup hook を間違って追加しないこと
- **TestClient warning**: starlette TestClient は内部で httpx を使うので
  dev に明示。version skew は dev グループに固定で抑える
- **SIGTERM テストの flakiness**: subprocess + sleep ベースは flake しがち。
  ready 判定は `until curl 127.0.0.1:<free_port>/healthz; do sleep 0.1; done` で
  ガード。port は OS から動的取得 (T2.5 `free_port` fixture)、8000 固定 NG
- **Typer の list[str] default**: `typer.Option([])` は mutable default 警告 +
  Typer 0.12 系で動作不安定。`typer.Option(None, ...)` + 関数内で `or []`
  に正規化 (T6 例示済)
- **viewer 切り替えが本 PR で起きない**: server は B 着手まで dead code
  (spec §7 で明文化)。CI で `mimicanno serve` を起動する flow は本 PR では
  作らない (B で frontend と一緒に整える)。README の server 章 (T9) では
  「B 完了まで viewer は静的 fetch のまま」と明記する
- **mypy strict + uvicorn**: uvicorn の types は完全ではないので
  `[[tool.mypy.overrides]]` で `ignore_missing_imports`。コード内 `# type: ignore`
  は最後の手段、`cast` で narrow を優先
- **`resolve()` symlink テストの FS 依存**: tmpfs と ext4 で symlink resolve
  挙動が同じことを確認。macOS HFS+/APFS は本 PR の対象外 (Linux dev box のみ)
- **WARNING / ERROR ログ流出**: 例外 handler は `_LOG.exception()` で stack を
  ログには出すが body には出さない。テストで body に stack 文字列が含まれない
  ことを必ず assert (T2 / T4 case 12)
