# Hand Viewer — T5 統合 smoke 実行ログ

**Date:** 2026-05-15 (実施) / 2026-05-16 (本ノート整理)
**Plan:** `docs/superpowers/plans/2026-05-15-hand-viewer-t5-smoke.md`
**Worktree:** `/misc/dl00/gayagaya/MimicAnno-hand-viewer` (branch `feat/hand-viewer`)

## 実行サマリ

T3/T4 (frontend HandViewer + RunList) を実装済の状態で、T5 (mimicanno serve + 統合 smoke) を実行した。

- frontend: `pnpm test --run` → **72/72 green** (HandViewer 9 件 + RunList 3 件含む)
- frontend: `pnpm build` (`tsc -b && vite build`) → **clean** (213 kB / gzip 67 kB)
- backend smoke: 4 endpoint 全て green (詳細下記)

## 行ったこと

### 1. 環境準備
- `corepack` で `pnpm` を `~/.local/bin` に enable
- `pnpm install` で frontend deps 取得
- `git submodule update --init sam3` (worktree の `sam3/` が未 init で `uv run --project` が metadata 解決で失敗するため。`pyproject.toml [tool.uv.sources]` が空 dir を editable で参照していた)

### 2. frontend 検証
- `pnpm test --run` で 72/72 通過
- `pnpm build` で型チェック + バンドル成功

### 3. backend 起動 (cwd-swap pattern)

worktree には `data/` も `runs/` も無いので、本体側を CWD にし `--project` で worktree の最新コードをロード:

```bash
cd /misc/dl00/gayagaya/MimicAnno
uv run --project /misc/dl00/gayagaya/MimicAnno-hand-viewer --extra server \
  mimicanno serve \
  --runs-root /misc/dl00/gayagaya/MimicAnno/runs \
  --hands-root data/hands \
  --port 8765
```

`--runs-root` は CLI 必須 (計画 r1 では「省略可」と書いたが実測で required と判明)。`--cors-origin` は curl smoke では不要なので省略。

### 4. endpoint smoke (curl)

| endpoint | 期待 | 結果 |
| --- | --- | --- |
| `GET /api/hands/index.json` | 9 episode, 全 `signals_ready=true` | ✅ 9/9 ready |
| `GET /api/hands/GX010085/meta.json` | `video_source` / `video_fps` / `video_total_frames` | ✅ `data/video/new/GX010085.MP4`, 29.97 fps, 1397 frames |
| `GET /api/hands/GX010085/signals.json` | `schema_version=2`, cam_t/euler_deg/depth_ok | ✅ schema 2, frame_000000 left hand `cam_t=[-0.333, 0.465, 0.259]`, `euler=(66.6, 37.9, -153.8)`, `depth_ok=true` |
| `GET /api/hands/GX010085/video` (Range) | `206 Partial Content` | ✅ `HTTP/1.1 206 Partial Content` (`curl -sv -H "Range: bytes=0-1023"`) |

注: `curl -I` (HEAD) は 405 を返す。endpoint は GET のみ実装。Range GET で 206。

### 5. cleanup
- `pkill -f "mimicanno serve --runs-root"` でサーバー停止確認
- `pgrep -af mimicanno` が空、port 8765 reachable=false

## 計画フェーズで見つかった blocker (2 ラウンドレビューで発見)

### Round 1: symlink 案の致命的バグ
当初案「worktree に `data` symlink」は `hands_routes.py:127-129` の `video_path.resolve() / repo_root.resolve()` 比較で symlink が flatten され、`is_relative_to()` が **常に false → 400** を返すことが判明。
→ cwd-swap + `uv run --project <worktree>` に切替。

### Round 2: sam3 submodule blocker
cwd-swap 案でも `pyproject.toml [tool.uv.sources]` の `sam3 = { path = "sam3", editable = true }` が **未 init の空 dir** を参照しており、uv が metadata 解決で必ず失敗。
→ Step 0.5 に `git submodule update --init sam3` を追加して解消。

### Round 2: --runs-root の指定粒度
当初「`runs/so101_phase4_v5` を渡す」と書いたが、CLI 仕様は「run **群** の親」を期待する。
→ `runs/` 直下を指定 (実測で `--runs-root` は省略不可だった)。

## 完了基準チェック

| 項目 | 状態 |
| --- | --- |
| T1 全 episode の signals.json v2 (本体側で既達) | ✅ 9/9 schema_version=2 |
| T2 サーバー `/api/hands/` 4 endpoint 動作 | ✅ 全 endpoint green |
| T3 HandViewer.tsx + tests | ✅ コード + 9 tests green |
| T4 RunList 手 episode リンク + tests | ✅ コード + 3 tests green |
| T5 統合 smoke (curl ベース) | ✅ 4/4 green |
| `pnpm build` clean | ✅ |
| `pnpm test --run` 全 green | ✅ 72/72 |

## 未確認 (autonomy 制約)

- ブラウザでの UI 視認 (`pnpm dev` → `?hand=GX010085&api=1`): autonomy 下で headless 環境のため省略。UI 経路は `pnpm test` (jsdom + RTL) でロジック検証済。
- depth_ok=false フレームのグレーアウト視覚確認: 同上。jsdom テストで `.hand-estimated` クラス + `(推定)` バッジ表示は検証済。

## 次のアクション (ハンドオフ用)

- worktree の uncommitted な変更 (`HandViewer.tsx`, `RunList.tsx`, `App.tsx`, `handsClient.ts`, 各 test) を T3/T4 コミット → branch push
- 必要なら開発者ローカルで `pnpm dev` を起動して UI 視認 (CORS 経由なら `--cors-origin http://localhost:5173` をサーバーに付与)
- 計画書 (`2026-05-15-hand-viewer-plan.md`) の T5 完了マーク
