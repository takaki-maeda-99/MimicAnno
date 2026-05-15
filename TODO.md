# TODO

## Hand pipeline

- [x] **人差し指と親指の間の距離計測** (pinch distance)
  - `HandEstimate.pinch_distance_m` として実装済み (`|joints_local[4] - joints_local[8]|` [m])
  - cam_t 非依存 (MANO joints_local はメトリック): refine=True/False 両パスで計算
  - `signals.json` に per-frame 出力 (Gaussian smoothing σ=2frames, NaN-aware)
  - フォーマット: `{"schema_version": 1, "frame_NNNNNN": {"right": {"value": float, "depth_ok": bool}, "left": ...}}`

## MimicAnno UI

- [ ] **手の状態ビューア** (spec: `docs/superpowers/specs/2026-05-15-hand-viewer-design.md`, plan: `docs/superpowers/plans/2026-05-15-hand-viewer-plan.md`)
  - 上 70%: 元動画
  - 下 30%: 手首位置 (x, y, z)・手首の向き・親指–人差し指間の絶対距離 をフレームごとに表示
  - 計算はパイプライン済み (pkl / signals.json) → UI は読み込むだけでよい

  ### レイアウト
  ```
  ┌─────────────────────────────────────┐
  │                                     │
  │        元動画 (上 70%)              │
  │                                     │
  ├─────────────────────────────────────┤
  │  手の計測値パネル (下 30%)          │
  │                                     │
  │  [右手]  wrist xyz  / 向き / pinch  │
  │  [左手]  wrist xyz  / 向き / pinch  │
  └─────────────────────────────────────┘
  ```

  ### 表示項目と取得元
  | 項目 | 取得元 | 備考 |
  |------|--------|------|
  | 手首位置 x, y, z [m] | `HandEstimate.cam_t` | HaMeR カメラ座標系。UniDAC 深度補正済み (`wrist_depth_m` が非 None の場合) |
  | 手首の向き (Euler 角 or 回転行列) | `HandEstimate.global_orient` (3×3) | ロール・ピッチ・ヨーへの変換は UI 側で実施 |
  | 親指–人差し指 絶対距離 [m] | `HandEstimate.pinch_distance_m` | `depth_ok=True` のフレームのみ深度補正済み; それ以外は MANO メトリックスケール |

  ### データソース
  - per-frame: `data/hands/<episode>/frames/frame_NNNNNN.pkl` → `list[HandEstimate]`
  - 時系列 (smoothed): `data/hands/<episode>/signals.json`

  ### 実装上の注意
  - `depth_ok=False` のフレームは cam_t が HaMeR 擬似メトリックのため、xyz の絶対値は信頼性が低い (相対変化は有効)
  - 左手 MANO は右手の鏡像 (joint index は同一); global_orient の符号に注意
  - 計算自体はパイプライン実行時に完了しているため、UI は pkl / signals.json を読むだけでよい

---

## ワークツリー分割計画 (2026-05-15, rev3)

実際の状況 (`git status` 実測, HEAD=`7e6326c`):
- **T1+T2 shipped** (`d9718d7`, `7e6326c`)
- **T3/T4 in-progress (uncommitted on main)** — `frontend/src/App.tsx` `RunList.tsx` (M) + `HandViewer.tsx` `handsClient.ts` + 各 `__tests__/` (新規)
- 加えて `scripts/start_ui.sh`, `scripts/batch_gem4.sh`, submodule pointer bump (UniDAC/hamer), TODO.md (本ファイル) が untracked/M
- 既存 worktree: `MimicAnno-planner-fix` (`feat/planner-visual-prompts` @ `a5939b4`) は別件で稼働中

### 事前整理 (worktree を切る前に main で完結させる)
- [ ] **A0-0: 旧スクリプト出力の棚卸し & 掃除** (ディレクトリ汚染対策)
  - 対象:
    - `runs/` の世代物: `so101_phase4`/`_v2`/`_v3`/`_v3_export`/`_v4`/`_v5_smoke`, `piper_phase4`/`_zc`, `piper_smoke`, `sam3_local_smoke`/`_smoke_export`, `episode_000000__*`, `hamer`, `unidac_depth` 等 (現行は `_v5` のみ)
    - `data/depth/` (11G): 現行 `precompute_depth.py` が生成するレイアウトと一致しないエピソード
    - `data/video/` (19G): `data/video/new/` 以外の旧配置
  - **保護対象 (絶対消さない)**:
    - `_vlm_dumps/*.jsonl` — FT 学習データ ([[project_gemma_ft_pipeline]])。allowlist 方式で残す
    - `data/hands/<ep>/frames/*.pkl` — T1 (signals.json) の再生成元。HaMeR 推論は重い
  - 手順 (いきなり `rm` しない):
    1. 候補リスト + サイズ + mtime + `runs/index.json` 参照有無を `docs/cleanup-2026-05-15.md` に書き出してコミット
    2. ユーザー sign-off
    3. `git ls-files --others --ignored --exclude-standard` で `.gitignore` 済み確認
    4. `rm -rf`
  - 完了条件: `du -sh runs data/depth data/video data/hands` 削減量を記録 + 残ったものが「現行スクリプトで再生成可能」を明記

- [ ] **A0-1: 未コミットファイルの所属確定** (実測ベース)
  - T2 関連 (M: `mimicanno/cli.py`, `mimicanno/server/app.py`, `tests/server/test_serve_cli.py` + 新規: `mimicanno/server/hands_routes.py`, `tests/server/test_hands_routes.py`, `tests/server/fixtures/`) → **hand-viewer worktree** へ移して continue
  - `docs/superpowers/specs/2026-05-15-hand-viewer-design.md`, `docs/superpowers/plans/2026-05-15-hand-viewer-plan.md` → hand-viewer worktree (T1 と一緒に push し忘れているので持っていく)
  - `docs/superpowers/plans/2026-05-15-phase5-b-r1-smoke-wrapup-plan.md`, `docs/superpowers/notes/2026-05-15-phase5-b-r1-handoff.md` → main に直接コミット (済作業の記録)
  - `scripts/start_ui.sh`, `scripts/batch_gem4.sh` → 用途確認のうえ main へ
  - `TODO.md` 変更 (本ファイル) → main にコミット
- [ ] **A0-2: submodule dirty 状態の解消** — `UniDAC`, `hamer` の `m` フラグ。worktree は `.git/modules` を共有するので、新 worktree にも dirt が引き継がれる。**worktree 切る前に解消必須**
- [ ] **A0-3: ローカル古ブランチ整理** — `fix/phase5-a-video-streaming`, `fix/phase5-b-r1-dev-followup` がマージ済みなら削除 + `git fetch --prune`
- [ ] **A0-4: `feat/hand-viewer` の remote 状態確認** — 既に push されている場合は新 worktree 作成時に衝突。必要なら remote 側を削除 (要 sign-off) または既存を再利用

### 並列ストリーム (それぞれ worktree を切る)

レビューで「hand-viewer を T1+T2 と T3+T4 で 2 worktree に分けるのは過剰 (単一開発者ではマージオーバーヘッドが上回る)」と指摘あり → **hand-viewer は 1 worktree に統合**。

| Worktree | ブランチ | スコープ | 依存 |
|---|---|---|---|
| `MimicAnno-hand-viewer` | `feat/hand-viewer` | Hand Viewer T3+T4+T5 (T1/T2 取り込み済、T3/T4 uncommitted を移送) | なし |
| `MimicAnno-phase5b-r2` | `feat/phase5-b-r2-boundary-drag` | Phase 5 B r2 (境界ドラッグ編集) — spec/plan 起こしから | なし |
| `MimicAnno-phase5d` | `feat/phase5-d-eval-harness` | Phase 5 D (Evaluation harness) — spec 起こしから | B writable API |

### 各 worktree でやること

#### hand-viewer (T3–T5)
- [ ] **HV-T3**: `frontend/src/lib/handsClient.ts` + `HandViewer.tsx` + テスト (進行中, main 上 uncommitted → worktree へ移送)
- [ ] **HV-T4**: `RunList.tsx` 拡張 + テスト (進行中)
- [ ] **HV-T5**: 統合 smoke (`mimicanno serve` + `pnpm dev`、`?hand=GX010085&api=1`)
- [ ] **HV-regen**: A0-0 で `data/hands/<ep>/frames/` を**温存した上で** 全 episode signals.json v2 再生成 (`--signals-only --full-signals`)

#### phase5-b-r2 (Edit UI 継続)
- [ ] **B2-spec**: 境界ドラッグの spec 起こし (`docs/superpowers/specs/YYYY-MM-DD-phase5-b-r2-boundary-drag-design.md`)
- [ ] **B2-plan**: 実装 plan
- [ ] **B2-impl**: PATCH endpoint 拡張 + UI ドラッグハンドル
- [ ] (将来) r3: reviewed 単独トグル、r4: object edit

#### phase5-d (Evaluation harness)
- [ ] **D-spec**: phase 5 当初 spec から D 部分を抜き出して詳細化
- [ ] **D-plan + impl**: 後続

### 完了条件 / マージ順
1. A0-* (main 整理) を先に commit/push
2. hand-viewer T1+T2 → main マージ
3. hand-viewer-frontend (T3+T4) → main マージ (T5 smoke 後)
4. phase5-b-r2 / phase5-d は独立にマージ可

