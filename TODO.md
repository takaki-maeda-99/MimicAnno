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

## ワークツリー分割計画 (2026-05-15, rev4 — 2026-05-16 更新)

**マスター計画 (出口基準・依存 DAG・リスク表):** `docs/superpowers/plans/2026-05-15-worktree-coordination-plan.md` (rev2 reviewed, `637d036`)

実際の状況 (HEAD=`637d036`):
- **Hand Viewer T1〜T4 shipped** on main (`d9718d7`, `7e6326c`, `2ab7f7b`)
- A0-* (事前整理) **すべて完了** (詳細は下記)
- worktree 4 本稼働中: `main` / `MimicAnno-hand-viewer` / `MimicAnno-phase5b-r2` / `MimicAnno-phase5d` (+ 別件 `MimicAnno-planner-fix`)
- `feat/hand-viewer` worktree は T3/T4 main 取り込みに伴い main 同期済 (uncommitted 破棄、`reset --hard main`)
- ディスク掃除済: 約 **24G 削減** (`9145e33`, 詳細は `docs/cleanup-2026-05-15.md`)

### 事前整理 (完了) ✅

- [x] **A0-0**: 旧出力掃除 (`docs/cleanup-2026-05-15.md` 記録、`9145e33`)。runs 11G→2.7G、data/video 19G→3G、合計 ~24G 削減。`_vlm_dumps/aggregated/*.jsonl` は `_vlm_dumps_archive/2026-05-15/` へ退避
- [x] **A0-1**: 未コミットファイル仕分け完了。T2 は `7e6326c`、T3/T4 は `2ab7f7b`、scripts/TODO は `111befe`、cleanup docs は `e789058`/`9145e33`、coordination plan は `637d036`
- [x] **A0-2**: submodule (UniDAC/hamer/sam3) commit + push 済 (UniDAC `bb34cf2`, hamer `2b05f6c`)、pointer bump `adc0547`
- [x] **A0-3**: `git fetch --prune`、`fix/phase5-a-video-streaming` 削除、`fix/phase5-b-r1-dev-followup` (PR #8) も merge `0bf0318` 取込後に `git branch -D` 済
- [x] **A0-4**: `feat/hand-viewer` remote 状態確認済 (local-only、衝突なし)

### Day 0 prereqs (新 worktree セッション起動前)

マスター計画 §-1 より:
- [x] **origin/main を push** (2026-05-16 完了、`45d8dae` push 済み)
- [x] **各 worktree branch を main に rebase** (feat/run-set-switcher / feat/phase5-b-r2-boundary-drag / feat/phase5-d-eval-harness を `45d8dae` 起点に揃え済み)
- [x] **各 worktree で submodule init + pnpm install** (全 3 worktree 完了。`npm install` ではなく `pnpm install --frozen-lockfile` を使用)

### 並列ストリーム

詳細はマスター計画参照。3 ストリームすべて独立 (DAG レビュー反映)。

| ID | Worktree | ブランチ | 残作業 |
|---|---|---|---|
| **S-HV** | `MimicAnno-hand-viewer` | `feat/hand-viewer` | T5 smoke + regen (T1-T4 は main 済) |
| **S-B2** | `MimicAnno-phase5b-r2` | `feat/phase5-b-r2-boundary-drag` | spec → plan → impl (境界ドラッグ) |
| **S-D** | `MimicAnno-phase5d` | `feat/phase5-d-eval-harness` | spec → plan → impl (eval harness、Phase 5 A read-only API を消費し B2 と並列可) |
| **S-RS** | ✅ SHIPPED | `feat/run-set-switcher` | UI ドロップダウンで runs/ 直下のサブディレクトリを切り替え (2026-05-16) |

### 各 worktree でやること

#### S-HV (hand-viewer) ✅ main マージ済 (`5f2e8fb`)
- [x] **HV-T5**: smoke 完了 + ブラウザ 4 項目確認済 (2026-05-16)
- [x] **HV-axes**: wrist XYZ 軸 canvas overlay 実装済 (`2307219`、`feat/hand-viewer-axes` ブランチ)
- [x] **HV-regen**: 全 9 episode を v2 で再生成済み (2026-05-15 23:48、T1 実行時に同時生成。全 ep schema_v=2、cam_t/euler_deg/depth_ok/pinch_m 確認済み)

#### S-B2 (phase 5 B r2: 境界ドラッグ)
- [x] **B2-spec**: `docs/superpowers/specs/2026-05-16-phase5-b-r2-boundary-drag-design.md` 完成・push済 (`3925d23`)
- [x] **B2-spec-review**: 独立レビュー 12 件反映済
- [x] **B2-plan**: `docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md` 完成・push済
- [ ] **B2-impl**: PATCH endpoint 拡張 + `BoundaryDragLayer.tsx` + `RunViewer.tsx` hook + tests
- [ ] **B2-smoke**: SO101 v5 + Piper v5 で境界編集 → 保存 → 再読込が往復することを確認
- [ ] **B2-future**: r3 reviewed 単独トグル / r4 object edit は別 PR

#### S-D (Phase 5 D: Evaluation harness)
- [x] **D-spec**: `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` 完成・push済 (`69d4d27`)
- [x] **D-spec-review**: 独立レビュー反映済
- [x] **D-plan**: `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` 完成・push済
- [ ] **D-impl-backend**: eval CLI/サーバー側 (B2 と並列可)
- [ ] **D-impl-frontend**: 結果表示 UI (B2 マージ後)

#### S-RS (run-set switcher) ✅ SHIPPED (2026-05-16)
- [x] **RS-impl**: `GET /api/run-sets` エンドポイント追加
- [x] **RS-impl**: `/api/runs/` に `?run_set=` クエリパラメータ対応
- [x] **RS-impl**: `--runs-root` に親ディレクトリを渡した時にサブディレクトリを自動検出
- [x] **RS-impl**: `RunList.tsx` 上部にドロップダウン追加、選択を URL `?run_set=` に反映
- [x] **RS-smoke**: so101(23) / piper(39) 切り替え確認、traversal ブロック確認

### マージ順 (master plan §3)
1. S-HV (smoke 完了次第、最短マージ)
2. S-B2 (impl + smoke 完了後)
3. S-D (B2 マージ後に frontend 統合)

---

## テストギャップ: loadable fixture の frozen 化

**現状:** `tests/server/` の約 59 テストが実行環境に `runs/so101_phase4_v5/episode_000000__e35061106394/` が存在しない場合にスキップされる。

```
SKIPPED: loadable fixture source missing: .../runs/so101_phase4_v5/episode_000000__e35061106394;
         this dev box only — CI should commit a frozen fixture instead.
```

**原因:** `tests/server/conftest.py` の `tmp_runs_root_loadable` fixture がリポジトリ外の実データ (`runs/` ディレクトリ) をコピーして使っているため。実データは大きく `.gitignore` 対象なので CI では常にスキップになる。

**本来の姿:** `tests/fixtures/loadable_run/` 以下に小さな合成済み固定データ (annotation.json / boundaries.json / signals.json / tracks.json + manifest.json) をコミットし、`conftest.py` の `_REAL_SO101_RUN` をそこへ向ける。実データのコピーは不要 (スキーマ的に正しければ十分)。

**修正手順:**
1. `runs/so101_phase4_v5/episode_000000__e35061106394/` から 5 アーティファクトをコピー
   ```
   cp runs/so101_phase4_v5/episode_000000__e35061106394/{manifest,annotation,boundaries,signals,tracks}.json \
      tests/fixtures/loadable_run/
   ```
2. `tests/server/conftest.py` の `_REAL_SO101_RUN` を変更:
   ```python
   _REAL_SO101_RUN = Path(__file__).resolve().parent.parent / "fixtures" / "loadable_run"
   ```
3. `tests/fixtures/loadable_run/` を `git add` してコミット

**優先度:** 低 (ローカル開発では実データがあるので実害なし)。ただし CI を将来追加するなら必須。

### 司令塔 (S-MAIN = このセッション) の責務
- 各ストリームの完了 notes/handoff をレビュー、マージ承認
- `MEMORY.md` index 編集はここのみ (他ストリームは `project_*.md` の新規ファイル作成のみ、index 追加要求は notes 経由)
- 全ストリーム完了後に `docs/superpowers/notes/2026-05-1X-multi-worktree-summary.md` で handoff

