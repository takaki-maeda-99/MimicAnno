# Hand Viewer — implementation plan

**Date:** 2026-05-15 (rev2: 4 BLOCKER fixes)
**Spec:** `docs/superpowers/specs/2026-05-15-hand-viewer-design.md`
**Branch:** `feat/hand-viewer` (cut from `main`)

---

## 前提

- `main` = `9f1dd06` (Phase 5 B r1 + hand-pipeline 取り込み済み)
- `data/hands/{episode}/frames/frame_NNNNNN.pkl` 存在; signals.json は未生成 (GX010176 のみ v1 が存在 → T1 で上書き)
- `data/video/new/GX010085.MP4` 等のソース動画は存在する
- `run_hand_estimation.py` に `--pass2` フラグは存在しない

---

## タスク一覧

### T1: signals.json v2 生成 (`run_hand_estimation.py` 拡張)

**ファイル:** `scripts/run_hand_estimation.py`

変更内容:
1. `_generate_signals()` に `full: bool = False` パラメータ追加。
2. `full=True` 時、各フレームのエントリに `cam_t`, `euler_deg`, `depth_ok` を追加し `schema_version: 2` を設定。
   - Euler 変換: `Rotation.from_matrix(h.global_orient).as_euler('ZYX', degrees=True)` → `[yaw, pitch, roll]` → `{"yaw": ..., "pitch": ..., "roll": ...}`
3. CLI に `--signals-only` フラグ追加: per-frame 推定をスキップし `frames/*.pkl` から signals.json のみ再生成。既存フレーム pkl が全て揃っている前提。
4. CLI に `--full-signals` フラグ追加 (default: False、後方互換): `_generate_signals(full=True)` を呼ぶ。
5. `--signals-only` 実装: `frames/*.pkl` を名前順にソートしてロード、`frame_index = int(stem.split("_")[1])` で復元し `_generate_signals()` に渡す。`--signals-only` は `--pinch-smooth-sigma` (デフォルト 2.0) を尊重する。`--video` と `--depth` は省略可能になる; fps と画像サイズは `--out/meta.json` から読み込む。`meta.json` が存在しない場合はエラー終了。
6. `_generate_signals()` の両手未検出フレームの扱いを変更: 現行実装はフレームキーを削除するが、v2 では `{"right": null, "left": null}` としてキーを保持する。v1 (`full=False`) は既存挙動のまま。

テスト (`tests/hand_pipeline/test_pipeline_signals.py`、新規作成):
- `schema_version` が 2
- `cam_t` が list[float] 3要素
- `euler_deg` に `yaw`, `pitch`, `roll` キー
- `depth_ok=false` フレームでも `cam_t` が値を持つ (HaMeR 擬似メトリック値)
- 手が検出されなかったフレームは `null`
- `schema_version` が 1 (full=False) → `cam_t` フィールドが存在せず、pinch キーは `value` (not `pinch_m`)
- v2 (`full=True`) → `pinch_depth_ok` フィールドが存在しない (`depth_ok` に統合済み)
- 両手未検出フレームで v2 は `{"right": null, "left": null}` を出力し、フレームキーを削除しない

完了後: 全エピソードの signals.json を v2 で生成/上書き。既存の v1 は上書きされるため、事前にバックアップ推奨 (`cp data/hands/GX010176/signals.json data/hands/GX010176/signals.json.v1.bak`)。CLAUDE.md 指定の HaMeR 専用 python を使うこと:
```bash
for ep in data/hands/*/; do
  hamer/.hamer/bin/python scripts/run_hand_estimation.py --signals-only --full-signals --out "$ep"
done
```

---

### T2: サーバー `/api/hands/` ルート

**新規ファイル:** `mimicanno/server/hands_routes.py`
**変更ファイル:** `mimicanno/server/app.py` (または `__main__.py`)

変更内容:
1. `make_hands_router(hands_root: Path | None, repo_root: Path)` 関数を作成。
   - `repo_root = Path.cwd()` をサーバー起動時に確定して渡す。
2. `hands_root` が None の場合、全ルートは `503 Service Unavailable` (`{"error": "hands_root not configured"}`)。
3. episode パスの検証 (全ルート共通):
   - `Path(episode).parts` が 1 要素かつ `..` でないこと。違反時は 400。
4. ルート実装:
   - `GET /api/hands/index.json` — `hands_root` 内のサブディレクトリを列挙し、各 `meta.json` を読んで episodes 配列を生成。`signals_ready` の判定: `(signals.json が存在) and (data.get("schema_version") == 2)` where data は `try: json.load(...) except (JSONDecodeError, Exception): {}`。`schema_version` キー欠損も含めて全ての malformed JSON を `signals_ready=false` として扱い、エンドポイント自体はクラッシュしない。
   - `GET /api/hands/{episode}/meta.json` — ファイルを JSON で返す。
   - `GET /api/hands/{episode}/signals.json` — ファイルを JSON で返す。
   - `GET /api/hands/{episode}/video`:
     - `meta.json["video_source"]` を読む。
     - `video_path = (repo_root / video_source).resolve()`
     - `video_path.is_relative_to(repo_root.resolve())` を確認 → 失敗時 400。
     - ファイルが存在しない → 404。
     - `FileResponse(video_path, media_type="video/mp4")` (Range 対応)。
5. `mimicanno serve` に `--hands-root` オプション追加。

テスト (`tests/server/test_hands_routes.py`、新規作成):
- index.json: 正常系 (fixture ディレクトリを使用)、`signals_ready` フラグが正しいこと
- hands-root なし → 503
- episode = `../etc` → 400
- signals.json が存在しない episode → 404
- video_source が repo_root 外を指す → 400
- meta.json に `video_source` キーがない → 400 (`{"error": "meta.json missing video_source"}`)
- video: Range ヘッダ付きリクエストで 206 を返すこと。fixture は有効な MP4 バイナリが必要 (ゼロバイトファイルは 206 を返さない): `ffmpeg -f lavfi -i color=black:duration=0.1:size=16x16 -c:v libx264 tests/server/fixtures/hands/GX010085/video.mp4` で生成してコミット。`meta.json` の `video_source` をこの fixture パスに向ける。

---

### T3: フロントエンド `HandViewer` コンポーネント

**新規ファイル:**
- `frontend/src/lib/handsClient.ts` — 型定義:
  - `HandSignalFrame`: `{ pinch_m: number; cam_t: [number, number, number]; euler_deg: { yaw: number; pitch: number; roll: number }; depth_ok: boolean }` (pinch_depth_ok なし)
  - `HandEpisodeEntry`, `HandIndexDoc`, `HandSignalsDoc`
  - `HandViewer` は `useApiToggle()` を使わず `/api/hands/` を直接使う (static fallback がないため)。コメントで意図的な divergence を明示すること。
- `frontend/src/components/HandViewer.tsx`
- `frontend/src/components/__tests__/HandViewer.test.tsx`

変更ファイル:
- `frontend/src/App.tsx` — `?hand=<id>` を読んで `<HandViewer>` に切り替え
- `frontend/src/components/RunList.tsx` — 手エピソード一覧セクション追加

`HandViewer.tsx` の構造:
1. `useEffect` で `{apiBase}/index.json` (手用) + `{episode}/meta.json` + `{episode}/signals.json` を fetch。apiBase は `/api/hands/`。`currentTimeSec` state は `HandViewer` 自身が `useState` で保持し `VideoPlayer` の `onTimeChange` で更新する。
2. `index.json` に `episodeId` が含まれない → `<div>エピソードが見つかりません: {episodeId}</div>` を表示。
3. signals.json の `schema_version !== 2` → エラー表示: `"signals.json が古いフォーマットです。--signals-only --full-signals で再生成してください"`。
3. `currentTimeSec` → `currentFrame = Math.min(Math.round(currentTimeSec * fps), total_frames - 1)`。最終フレームの浮動小数点端数でインデックスが範囲外にならないようクランプ。
4. `VideoPlayer` に `videoUrl = ${apiBase}{episode}/video` を渡す。
5. `HandDataPanel` サブコンポーネント:
   - `signals["frame_" + String(currentFrame).padStart(6, "0")]` を参照。
   - 右手・左手それぞれ `cam_t xyz`, `euler_deg (roll/pitch/yaw)`, `pinch_m (mm 変換表示)` を表示。
   - `depth_ok=false` → 値をグレーアウト + `(推定)` バッジ。
   - フレームに手なし (`null`) → `"未検出"` 表示。
6. `/api/hands/index.json` が 503/network error → `<div>手のデータがありません</div>` (graceful degrade)。
7. `signals_ready=false` のエピソード → `"このエピソードは signals.json が未生成です"` 表示。

テスト (`HandViewer.test.tsx`):
- frame index 計算: `fps=30`, `currentTime=1.0s` → frame 30 のデータが表示される; `currentTime=total_frames/fps + 0.01` → `total_frames - 1` にクランプされること
- `depth_ok=false` でグレーアウトクラスが付く
- `schema_version=1` レスポンス時にエラーメッセージが表示される
- 503 レスポンス時に graceful degrade メッセージが表示される
- index.json に episodeId なし → "エピソードが見つかりません" が表示される
- 手 `null` フレームで "未検出" が表示される
- `currentTimeSec` state が HandViewer に正しく保持され VideoPlayer の onTimeChange で更新される

---

### T4: RunList への手エピソードリンク追加

**変更ファイル:** `frontend/src/components/RunList.tsx`
**新規ファイル:** `frontend/src/components/__tests__/RunList.test.tsx`

`/api/hands/index.json` を非同期 fetch し、成功時のみ手エピソード一覧を RunList の末尾に追加。失敗 (503/network error) は非表示。

- `signals_ready=true` → `/?hand=<id>&api=1` へのリンク
- `signals_ready=false` → グレーアウト + `(signals未生成)`

テスト (`RunList.test.tsx`、新規作成):
- `/api/hands/index.json` が返ったとき手エピソードリンクが表示される
- 503 のとき手エピソードセクションが表示されない
- `signals_ready=false` のとき `signals未生成` テキストが表示される

---

### T5: 統合確認

1. T1 コマンドで全エピソードの signals.json を v2 生成。
2. `uv run --extra server mimicanno serve --runs-root runs/so101_phase4_v5 --hands-root data/hands --cors-origin http://localhost:5173`
3. `pnpm dev` → `http://localhost:5173/?hand=GX010085&api=1`
4. 確認項目:
   - 動画が再生できること (Range request でシーク可)
   - フレーム進捗に合わせて手首位置・角度・ピンチ距離が更新されること
   - `depth_ok=false` フレームでグレーアウト + `(推定)` バッジが出ること
   - RunList ページに手エピソードリンクが表示されること

---

## 依存関係と実装順

T1 (データ生成) → T2 (サーバー実装) → T3・T4 (フロントエンド、並列可)

- T2 は T1 の出力ファイルを読むだけなのでコード実装は並列に進められるが、smoke test は T1 実行後に行う。
- T3 と T4 は互いに独立 (T3 は `HandViewer`、T4 は `RunList` への追加)。

---

## 完了基準

1. `uv run pytest tests/hand_pipeline/test_pipeline_signals.py` green
2. `uv run pytest tests/server/test_hands_routes.py` green
3. `pnpm test` (frontend) green (新規テストを含む)
4. T5 統合確認を手動で実施し、全項目 OK
5. `mypy mimicanno/` clean
