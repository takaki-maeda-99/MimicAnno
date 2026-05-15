# Run-Set Switcher — Implementation Plan

**Date:** 2026-05-16
**Feature:** UI ドロップダウンで runs/ 直下のサブディレクトリを切り替え
**Branch:** `feat/run-set-switcher`
**Spec context:** TODO.md §S-RS
**Estimated effort:** 半日〜1 日

---

## §0 前提・出口基準

### 前提

- `--runs-root` は現在 **単一 run-set dir** (例: `runs/so101_phase4_v5`) を指す。
  新実装後は **親ディレクトリ** (例: `runs/`) も受け付ける。後方互換あり (後述)。
- `RunsRepository` / `edit_repo.apply_edit` は変更不要。変更するのはルート算出ロジックのみ。

### 後方互換ルール

| `--runs-root` の中身 | 動作 |
|---|---|
| `index.json` が直下にある (legacy) | `effective_root = runs_root`。`/api/run-sets` は `[{"name":".", "label":"(root)"}]` → フロントはドロップダウンを **表示しない** |
| サブディレクトリが存在する (multi mode) | `/api/run-sets` はサブディレクトリ一覧 → ドロップダウン表示 |

### 出口基準

1. `GET /api/run-sets` が runs/ 直下のサブディレクトリ名一覧を返す
2. `GET /api/runs/index.json?run_set=so101_phase4_v5` が so101 の index を返す
3. `PATCH /api/runs/{name}/segments/{id}?run_set=so101_phase4_v5` が正しく書き込む
4. UI ドロップダウンで so101 / piper / gem4 を切り替えると episode 一覧が変わる
5. 既存 1170+ tests green、mypy --strict clean
6. legacy mode (`--runs-root runs/so101_phase4_v5`) でドロップダウンが表示されない

---

## §1 設計決定 (3 MUST-fix 解決)

### MUST-fix 1: ロックパス

`apply_edit` は `runs_root / "index.json.lock"` を使う。
`effective_root = runs_root / run_set` を渡すことで lock は `runs/so101_phase4_v5/index.json.lock` になる。
run-set 間は完全に独立なので per-run-set ロックで正しい。`mimicanno annotate` の publish も同ロックを取る設計 (edit_repo.py:8-11) だが、publish.py 自体はこのロックを取らないことを確認済 (`grep -n file_lock mimicanno/pipeline/publish.py` → 0 件)。**変更不要。**

### MUST-fix 2: RunsRepository 設計

`RunsRepository(root)` は既存のまま。route handler で `effective_root` を算出し `RunsRepository(effective_root)` を per-request 生成する。クラス変更不要。

### MUST-fix 3: apply_edit の run_dir / idx_path

`apply_edit(runs_root=effective_root, ...)` を渡すことで、`run_dir = effective_root / name`、`idx_path = effective_root / "index.json"` が正しく解決される。`edit_repo.py` 変更不要。

---

## §1.5 レビューで判明した追加 MUST-fix (rev2)

**R-M1: パストラバーサルチェックをシンボリックリンク対応に変更**
`effective.parent != parent_root` は symlink 先が別 dir の場合に誤拒否する。
`runs_repo.py` の `_is_under(candidate, root)` パターン (`is_relative_to`) と同じ方法を使い、
`effective.is_relative_to(parent_root) and effective != parent_root` で 1 レベル直下を確認する。

**R-M2: `fetchRunSets` は固定パス `/api/run-sets` を使う**
`apiBase.replace("/runs/", "/run-sets")` は brittle。
`fetch("/api/run-sets")` と直接書き、`apiEnabled=true` の場合のみ呼ぶ。

**R-M3: `editClient.patchSegmentPhase` に `runSet?: string` 引数追加**
`RunViewer.tsx` の `patchSegmentPhase` 呼び出しが `apiBase` しか渡さないため、PATCH URL に `?run_set=` が付かない。
`editClient.ts` の `patchSegmentPhase` に `runSet?: string` を追加し、URL を
`${apiBase}${name}/segments/${id}${runSet ? `?run_set=${runSet}` : ""}` で構成する。

---

## §2 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `mimicanno/server/runs_repo.py` | `list_run_sets(parent: Path) -> list[dict]` 追加 |
| `mimicanno/server/routes.py` | `make_router` を `parent_root` ベースに変更、`?run_set=` 対応、`/api/run-sets` 追加 |
| `frontend/src/lib/runsClient.ts` | 新規: `fetchRunSets()` (固定 `/api/run-sets`, api mode 専用) |
| `frontend/src/lib/editClient.ts` | `patchSegmentPhase` に `runSet?: string` 追加 |
| `frontend/src/components/RunList.tsx` | run-set ドロップダウン + `?run_set=` URL param |
| `frontend/src/App.tsx` | `run_set` URL param を `RunList` / `RunViewer` に prop で渡す |
| `frontend/src/components/RunViewer.tsx` | artifact fetch (index.json + manifest + PATCH) に `?run_set=` を pass-through |

CLIの `cli.py` は変更不要 (`--runs-root` は既存のまま; 親 dir を渡せばよい)。

---

## §3 タスク (TDD: 失敗テスト → 実装 → green = 1 commit)

### T0: audit (1 commit)

```
grep -n "run_set\|?run_set" tests/server/ -r      # 0 件を確認
grep -n "real_so101_run\|tmp_runs_root" tests/server/conftest.py
```

- `conftest.py` に `tmp_parent_runs_root` fixture がないことを確認 (新規追加が必要)
- frontend tests の既存パターン (vi.fn vs msw) を `frontend/src/__tests__/RunList.test.tsx` で確認

### T1: `list_run_sets` unit test + impl (1 commit)

**テスト** (`tests/server/test_runs_repo_run_sets.py`):
```python
def test_list_run_sets_multi(tmp_path):
    # サブディレクトリ 2 本、それぞれに index.json
    (tmp_path / "so101_phase4_v5").mkdir()
    (tmp_path / "so101_phase4_v5" / "index.json").write_text("{}")
    (tmp_path / "piper_phase4_v5").mkdir()
    (tmp_path / "piper_phase4_v5" / "index.json").write_text("{}")
    result = list_run_sets(tmp_path)
    assert {r["name"] for r in result} == {"so101_phase4_v5", "piper_phase4_v5"}

def test_list_run_sets_legacy(tmp_path):
    # 直下に index.json → legacy mode
    (tmp_path / "index.json").write_text("{}")
    result = list_run_sets(tmp_path)
    assert result == [{"name": ".", "label": "(root)"}]

def test_list_run_sets_empty(tmp_path):
    result = list_run_sets(tmp_path)
    assert result == []
```

**実装** (`runs_repo.py`):
```python
def list_run_sets(parent: Path) -> list[dict[str, str]]:
    if (parent / "index.json").exists():
        return [{"name": ".", "label": "(root)"}]
    result = []
    for d in sorted(parent.iterdir()):
        if d.is_dir() and (d / "index.json").exists():
            result.append({"name": d.name, "label": d.name})
    return result
```

### T2: `make_router` の effective_root 算出 + `/api/run-sets` endpoint (1 commit)

`make_router` の変更点:
```python
def make_router(
    runs_root: Path,
    labelset: LabelSetCache,
    reviewer: str | None = None,
) -> APIRouter:
    parent_root = runs_root.resolve()

    def get_effective_root(run_set: str | None = Query(None, alias="run_set")) -> Path:
        if run_set is None or run_set == ".":
            return parent_root
        # security: symlink-safe check — must be exactly 1 level under parent_root
        effective = (parent_root / run_set).resolve()
        if not effective.is_relative_to(parent_root) or effective == parent_root:
            raise MimicAnnoHTTPError(status=400, code="invalid_run_set",
                                     message=f"run_set {run_set!r} is not a direct subdirectory")
        if not effective.is_dir():
            raise MimicAnnoHTTPError(status=404, code="run_set_not_found",
                                     message=f"run_set {run_set!r} not found")
        return effective

    @router.get("/api/run-sets")
    def get_run_sets() -> Response:
        from mimicanno.server.runs_repo import list_run_sets
        data = list_run_sets(parent_root)
        return Response(content=json.dumps(data).encode(), media_type="application/json")
```

既存の `repo = RunsRepository(runs_root)` / `get_repo()` を削除し、各エンドポイントで `effective_root = Depends(get_effective_root)` を使って per-request に `RunsRepository(effective_root)` を生成する。

**テスト** (`tests/server/test_routes_run_set.py`):
```python
# GET /api/run-sets multi mode
def test_run_sets_multi(tmp_parent_runs_root):
    client = make_test_client(tmp_parent_runs_root)
    r = client.get("/api/run-sets")
    assert r.status_code == 200
    names = {x["name"] for x in r.json()}
    assert "so101_phase4_v5" in names

# GET /api/run-sets legacy mode
def test_run_sets_legacy(tmp_runs_root):
    client = make_test_client(tmp_runs_root)
    r = client.get("/api/run-sets")
    assert r.status_code == 200
    assert r.json() == [{"name": ".", "label": "(root)"}]

# path traversal blocked
def test_run_set_traversal_blocked(tmp_parent_runs_root):
    client = make_test_client(tmp_parent_runs_root)
    r = client.get("/api/runs/index.json?run_set=../secret")
    assert r.status_code == 400
```

### T3: `GET /api/runs/index.json?run_set=` (1 commit)

`get_index` を変更:
```python
@router.api_route("/api/runs/index.json", methods=["GET", "HEAD"])
def get_index(effective_root: Path = Depends(get_effective_root)) -> Response:
    repo = RunsRepository(effective_root)
    return Response(content=repo.read_index(), media_type="application/json")
```

テスト: `?run_set=so101_phase4_v5` で so101 の index が返ること、`?run_set=` なしで legacy が動くこと。

### T4: `GET /api/runs/{name}/{artifact}?run_set=` (1 commit)

`get_artifact` を同様に変更。テスト: `?run_set=so101_phase4_v5` でマニフェストが取れること。

### T5: `PATCH /api/runs/{name}/segments/{id}?run_set=` (1 commit)

`patch_segment` 内の `runs_root=runs_root` を `runs_root=effective_root` に変更。
テスト: PATCH に `?run_set=so101_phase4_v5` が通ること (existing `test_routes_patch.py` パターンを参考)。

### T6: `conftest.py` に `tmp_parent_runs_root` fixture 追加 (T1 と同 commit; T2 より先に必要)

```python
@pytest.fixture
def tmp_parent_runs_root(tmp_path):
    """親ディレクトリに 2 run-set サブディレクトリを持つ tmp ツリー。"""
    for name in ("so101_phase4_v5", "piper_phase4_v5"):
        sub = tmp_path / name
        sub.mkdir()
        (sub / "index.json").write_bytes(b'{"schema_version":1,"runs":[]}')
    return tmp_path
```

### T7: `runsClient.ts` 新規 + unit test (1 commit)

```typescript
// frontend/src/lib/runsClient.ts
export type RunSetEntry = { name: string; label: string };

// api mode 専用。/api/run-sets は固定パス (apiBase 非依存)。
export async function fetchRunSets(): Promise<RunSetEntry[]> {
  const r = await fetch("/api/run-sets");
  if (!r.ok) return [];
  return r.json() as Promise<RunSetEntry[]>;
}
```

テスト (`__tests__/runsClient.test.ts`): vi.fn() で fetch をモック、`[{name:"so101_phase4_v5", label:"so101_phase4_v5"}]` を返すこと。
`RunList.tsx` では `apiEnabled=true` の場合のみ `fetchRunSets()` を呼ぶ。

### T8: `RunList.tsx` にドロップダウン追加 (1 commit)

- mount 時に `fetchRunSets` を呼ぶ
- `runSets.length > 1` の場合のみ `<select>` を表示
- 選択変更 → URL `?run_set=<name>` を更新 (`history.pushState` または `<a>` リロード)
- `index.json` の fetch URL を `${apiBase}index.json${runSetParam}` に変更

テスト (`__tests__/RunList.test.tsx`): 2 run-set がある場合は `<select>` が表示され、1 run-set (legacy) では表示されないこと。

### T9: `App.tsx` で `?run_set=` を `apiBase` に反映 (1 commit)

現在の `apiBase` は `"/api/runs/"` (api mode) or `"/runs/"` (static mode)。
`?run_set=` は別パラメータとして `RunList` / `RunViewer` に渡す (`RunSetContext` を追加するか、URLSearchParams を都度読む)。

シンプルな方針: `App.tsx` で `useSearchParams` → `runSet` を `RunList` / `RunViewer` に prop で渡す。

### T10: `RunViewer.tsx` + `editClient.ts` で全 fetch / PATCH に `?run_set=` pass-through (1 commit)

`RunViewer` が受け取った `runSet` prop を全 fetch URL と PATCH 呼び出しに付加。

```typescript
const qs = runSet && runSet !== "." ? `?run_set=${encodeURIComponent(runSet)}` : "";
// index.json
const r = await fetch(`${apiBase}index.json${qs}`);
// manifest URL (ETag + artifact base)
const manifestUrl = `${apiBase}${name}/manifest.json${qs}`;
// PATCH
await patchSegmentPhase({ apiBase, runName, segmentId, phase, ifMatch, runSet });
```

`editClient.ts` の `patchSegmentPhase` に `runSet?: string` を追加:
```typescript
export async function patchSegmentPhase(args: {
  apiBase: string;
  runName: string;
  segmentId: string;
  phase: string;
  ifMatch: string;
  runSet?: string;
}): Promise<...> {
  const qs = args.runSet && args.runSet !== "." ? `?run_set=${encodeURIComponent(args.runSet)}` : "";
  const url = `${args.apiBase}${encodeURIComponent(args.runName)}/segments/${encodeURIComponent(args.segmentId)}${qs}`;
  ...
}
```

テスト:
- `runSet="so101_phase4_v5"` を渡したとき index.json / manifest / PATCH URL に `?run_set=so101_phase4_v5` が含まれること
- `runSet` なし / `.` の場合は QS なし (`?` 自体が付かないこと)

### T11: mypy --strict 確認 + 既存 tests all green (1 commit でまとめ可)

```bash
uv run --extra server mypy mimicanno/server
uv run pytest tests/ -q
cd frontend && pnpm test --run
```

---

## §4 smoke 手順 (T12)

```bash
# 1. サーバー起動 (runs/ を親として渡す)
cd /misc/dl00/gayagaya/MimicAnno
uv run --extra server mimicanno serve \
  --runs-root runs \
  --port 8765

# 2. run-sets 確認
curl -s http://localhost:8765/api/run-sets | python3 -m json.tool

# 3. so101 index.json
curl -s "http://localhost:8765/api/runs/index.json?run_set=so101_phase4_v5" | python3 -m json.tool | head -20

# 4. piper index.json
curl -s "http://localhost:8765/api/runs/index.json?run_set=piper_phase4_v5" | python3 -m json.tool | head -20

# 5. ブラウザ確認: ドロップダウンで切り替え
# http://localhost:5173/?api=1 → ドロップダウンで so101/piper/gem4 を切り替え

# 6. legacy mode (後方互換)
uv run --extra server mimicanno serve \
  --runs-root runs/so101_phase4_v5 \
  --port 8766
curl -s http://localhost:8766/api/run-sets  # → [{"name":".","label":"(root)"}]
```

---

## §5 実装上の注意

- `get_effective_root` は FastAPI `Depends` として定義することで全エンドポイントで再利用
- `effective.parent != parent_root` のチェックは **resolved path** で比較 (symlink flatten 済み)
- `list_run_sets` はサブディレクトリが `index.json` を持つものだけを有効な run-set として扱う (`.git`, `__pycache__` など除外)
- フロントのドロップダウンは `runSets.length <= 1` のとき非表示 — legacy 環境でのレイアウト崩れなし
- `?run_set=` なし + multi-mode サーバー → `effective_root = parent_root` のまま。`parent_root / "index.json"` が存在しなければ 404 (期待通りのエラー)

---

## §6 完了後にやること

1. branch push + PR 作成 (`gh pr create`)
2. `docs/superpowers/notes/2026-05-16-run-set-switcher-results.md` に curl 結果貼付
3. memory `project_phase5_status.md` に S-RS SHIPPED 追記
4. `TODO.md` S-RS チェックボックスを全て `[x]` に
