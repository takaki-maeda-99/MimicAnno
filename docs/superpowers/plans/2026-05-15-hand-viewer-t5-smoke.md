# Hand Viewer — T5 統合 smoke 計画

**Date:** 2026-05-15
**Parent plan:** `docs/superpowers/plans/2026-05-15-hand-viewer-plan.md` (T5 セクション)
**Branch / Worktree:** `feat/hand-viewer` (`/misc/dl00/gayagaya/MimicAnno-hand-viewer`)

## 前提条件 (確認済み)

- T1: `data/hands/*/signals.json` は **MimicAnno 本体側** (`/misc/dl00/gayagaya/MimicAnno/data/hands/`) に v2 で生成済 (9 episodes 全て `schema_version=2`)。
- T2: `mimicanno serve --hands-root` 実装済 (cli.py:527, app.py:51, hands_routes.py)。
- T3/T4: フロントエンドコード commit 前だが `pnpm test --run` で 72/72 green, `pnpm build` (tsc + vite) green。
- video_source は `meta.json` 内で **MimicAnno 本体からの相対パス** (`data/video/new/GX010085.MP4` 等) なので、サーバーは `/misc/dl00/gayagaya/MimicAnno` を CWD として起動する必要がある。

## 課題: worktree 分離

このタスクを実行する worktree (`MimicAnno-hand-viewer`) には `data/` も `runs/` も無い。一方サーバーコードと frontend ソースは worktree 側だけが最新。

**選択肢:**

1. **(A)** worktree 内で `--hands-root /misc/dl00/gayagaya/MimicAnno/data/hands` のように **絶対パス指定**。ただし `video_source` の repo-root 検証 (`is_relative_to(repo_root.resolve())`) で弾かれる。`repo_root = Path.cwd()` で決まるので、CWD を本体 `/misc/dl00/gayagaya/MimicAnno` に変える必要がある。が、その場合 `mimicanno` パッケージは本体側の古い版が import される → サーバーコード不整合。
2. **(B)** worktree 側に `data/` を symlink (`ln -s /misc/dl00/gayagaya/MimicAnno/data data`)。CWD は worktree のまま、`--hands-root data/hands` を渡せば `repo_root = worktree`, `video_path = worktree/data/video/.../GX010085.MP4` が symlink 経由で解決され、`is_relative_to` も pass する。
3. **(C)** smoke を **API レイヤだけ** にとどめ、`tests/server/fixtures/hands` を `--hands-root` に渡して endpoint レスポンスの形だけ確認する。実データ視聴はスキップ。

**推奨: (B)**。理由:
- 計画 T5 の確認項目 ("動画が再生できること", "depth_ok=false でグレーアウト" 等) は実データが無いと満たせない。
- (A) は import 経路がぐちゃぐちゃで信頼性低い。
- (C) は計画書 T5 の意図 (実データ smoke) を満たさない。

symlink 作戦の副作用: `data/` が worktree から見えるようになるが、git に track されない (シンボリックリンク自体だけが untracked になる)。smoke 後は `rm data` で戻せる。`.gitignore` に追加 or 一時的なものとして放置。

## レビュー結果反映 (2026-05-15)

reviewer 指摘:
- `hands_routes.py:127-129` で `video_path.resolve()` と `repo_root.resolve()` を比較しているため、**symlink は flatten されて 400 が返る**。(B) symlink 方式は破綻。
- 正解は **(A) cwd-swap + `uv run --project <worktree>`**。`uv run --project` でパッケージ解決は worktree 側、CWD は本体側にできるので両立する。
- `runs/` は worktree に既に実体あり (worktree 自体のもの)。本体の `runs/` には触らず、`--runs-root` には本体側絶対パスを渡すか、`--runs-root` を省略する (RunList 404 は許容)。
- `pnpm dev` は autonomy では UI 視認できず無意味。curl smoke + 既存 `pnpm test` / `pnpm build` で代替。
- background kill は `%1 %2` でなく記録した PID で。

## ステップ (改訂版 r2)

### Step 0.5 — sam3 submodule 初期化

`pyproject.toml [tool.uv.sources]` に `sam3 = { path = "sam3", editable = true }` があり、worktree の `sam3/` は空のため `uv run --project` がメタデータ解決で失敗する。

```bash
git -C /misc/dl00/gayagaya/MimicAnno-hand-viewer submodule update --init sam3
```

### Step 1 — サーバー起動 (cwd-swap, background, PID 記録)

CWD は **本体 `/misc/dl00/gayagaya/MimicAnno`**、パッケージは worktree から解決。

```bash
cd /misc/dl00/gayagaya/MimicAnno
uv run --project /misc/dl00/gayagaya/MimicAnno-hand-viewer --extra server \
  mimicanno serve \
  --hands-root data/hands \
  --port 8765
```

`--runs-root` 省略 (RunList 404 は許容)。`--cors-origin` は curl smoke では不要。

Bash tool では `run_in_background: true` で起動し、shell ID を保持する。起動完了は `curl -s http://localhost:8765/api/hands/index.json` が 200 を返すまでポーリング (Monitor または短い retry)。

### Step 2 — endpoint smoke (curl)

```bash
curl -sS http://localhost:8765/api/hands/index.json | python3 -m json.tool | head -30
curl -sS http://localhost:8765/api/hands/GX010085/meta.json | python3 -m json.tool | head -10
curl -sS http://localhost:8765/api/hands/GX010085/signals.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('schema_version:', d['schema_version']); print('frame_000000:', d.get('frame_000000'))"
# Range request
curl -sI -H "Range: bytes=0-1023" http://localhost:8765/api/hands/GX010085/video | head -10
# 期待: HTTP/1.1 206 Partial Content
```

期待される確認:
- index.json で 9 episode 全て `signals_ready=true`
- meta.json が schema 通り
- signals.json schema_version=2、cam_t/euler_deg/depth_ok を持つ
- video endpoint が 206 Partial Content を返す (Range 対応)

### Step 3 — (削除) frontend dev server

autonomy 下で UI 視認できないため `pnpm dev` は省略。`pnpm test --run` (72/72 green) と `pnpm build` (clean) が UI 検証の代理。

<details><summary>(参考、削除前メモ)</summary>

```bash
export PATH=$HOME/.local/bin:$PATH
cd frontend
pnpm dev --host 127.0.0.1 --port 5173 &
```

vite proxy は通常未設定。代わりに dev mode で API を直接叩くと CORS で弾かれる可能性。`vite.config.ts` を確認し、proxy 設定があれば port 8765 に向ける必要。**事前確認必須**。

`vite.config.ts` を見て:
- proxy 設定があれば port が 8765 と一致するか確認
- 無ければ `--cors-origin http://localhost:5173` でカバー可能 (CORS 経由で叩く)

### Step 5 — ヘッドレス検証 (curl over vite)

vite dev server が proxy 設定なし & CORS 経由の場合、ブラウザでないと UI が描画できない。ヘッドレスでの確認は curl で API を叩く Step 3 で済ませ、UI の描画確認は **手動 OR スクリーンショット** に限定する。

autonomous モードかつ手動視認が難しい場合、以下に置き換える:
- index.html を取得して HTML スケルトンが正しく返ってくることだけ確認
- `pnpm test --run` (既に green) を UI 検証の代理として記録

</details>

### Step 4 — cleanup

サーバー shell を停止 (Bash tool の background shell を KillBash)。symlink 作成しないので `rm` 不要。

## 完了条件

1. Step 3 の 4 つの curl 検証が全て期待通り
2. `pnpm test --run` 全 green (実行済)
3. `pnpm build` clean (実行済)
4. サーバーログにスタックトレース無し
5. cleanup 完了

## リスクと回避

| リスク | 回避 |
| --- | --- |
| `vite.config.ts` に API proxy 設定が無く CORS で fetch 失敗 | `--cors-origin http://localhost:5173` で CORS 許可、または vite proxy を一時追加 |
| `runs/so101_phase4_v5` が本体側に存在しない | `ls runs/` で代替のラン名を見つけて差し替え。RunList の確認は T5 必須ではない |
| symlink 経由で `is_relative_to` が pass しない (resolve() でターゲットに展開される) | `repo_root.resolve()` と `video_path.resolve()` を比較していると symlink 解決後の絶対パスを比較するので、worktree CWD と一致せず 400 を返す可能性。**事前検証必須** (Step 0 で `python3 -c "...is_relative_to..."` を試す) |
| symlink 残置のリスク | Step 6 で確実に `rm` |

## Step 0 (追加) — symlink + repo_root 検証

`hands_routes.py` の video endpoint 実装を読み、`repo_root.resolve()` か単に `repo_root` かを確認。`resolve()` の場合、symlink ターゲット (`/misc/dl00/gayagaya/MimicAnno`) と CWD (`/misc/dl00/gayagaya/MimicAnno-hand-viewer`) が違うため 400 を返す。その場合は **(A) CWD を本体側に変えるが、`uv run` を worktree 側の pyproject から呼ぶ** で対応:

```bash
cd /misc/dl00/gayagaya/MimicAnno
uv run --project /misc/dl00/gayagaya/MimicAnno-hand-viewer --extra server \
  mimicanno serve --hands-root data/hands ...
```

これで CWD = MimicAnno 本体、コードは worktree から import される。
