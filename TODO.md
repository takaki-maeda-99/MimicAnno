# TODO (2026-05-17 evening, post-U-A cleanup)

**Autonomy window: CLOSED 2026-05-16** — Phase 5 D shipped + SO101 v5 real-data smoke (17 events × 4 edit types) green。次窓を開ける場合はユーザー判断。

**Major shipments (2026-05-17)**:
- Phase 5 D r2: frontend (`b5050cc`) + backend (`a7d5283`) — summary `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`
- Phase 6 core (eval v2): PR #13 (`d2facf1`) — true planner_agreement + confusion matrix + schema 0.4.0
- **U-A initiative**: 7 PRs (#12, #14-#18, #20) — dataset processing & visualization UI、下表参照
- **26B config gap fix**: PR #19 (`0d65616`) — `scripts/batch_annotate.py` boundary/smoother YAML passthrough。本セッションで GPU 0 (A100 80GB) で E2E smoke proven (commit `869be5b`)、26B SO101 で segments=5/4 と 4B 一致
- **G7 full-ep 再走 ✅ FULL PASS** (`37b5964`, GPU 1+3): cam_t metric anchoring 検証通過 — UniDAC anchored 0.14-0.27 m (21/23 frame)、wrist_depth_m 0.37-0.51 m。これで **以下が gated 解除**:
  - Phase 5+ Replay UI で手の 3D 位置を mm 単位で可視化
  - MimicRec で metric pose を使った hand mimicry
  - HandSignalGraph (commit `3ae28bb`) の xyz cam_t グラフが意味ある値で表示 (前は HaMeR fallback 13 m scale で無意味)
  - 詳細: `docs/superpowers/notes/2026-05-17-g7-full-ep-rerun-results.md`

---

## 残タスク

### U-A: Dataset processing & visualization UI ✅ **完了 (2026-05-17)**

**Master spec**: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (rev3、Opus 多段レビュー通過)

**全 7 PR merged** (5 sub-project + 1 routing follow-up + 1 schema fix):

| ID | 内容 | PR | merge commit |
|---|---|---|---|
| **U-A1** | Catalog + Job kick (`/api/datasets` + `/api/jobs` + frontend `/datasets` `/jobs` + subprocess job runner) | #12 | `1624af5` |
| U-A1 follow-up | `?page=datasets` / `?page=jobs` routing in App.tsx | #15 | `88b9324` |
| **U-A3** | VLM dumps viewer (RunViewer 右パネル) | #14 | `9cdce19` |
| U-A3 rev3 schema fix | `kind: labeler` + `frame_url`/`keyframe_urls`/`request_json` 整合 | #17 | `cc6aa5e` |
| **U-A2** | Dataset summary (label 分布 dashboard tab) | #16 | `bba681e` |
| **U-A4** | SAM3 mask overlay (pre-bake sidecar + canvas overlay) | #18 | `e6e9b2f` |
| **U-A5** | Site-wide progress badge (header + polling) | #20 | `747c5e7` |

**初期 dispatch では各 sub-project が古い main から分岐 → main に 7 file pollution + ua-1 PR #15 / Phase 6 rollback を伴う diff** が発生。司令塔が 4 branches に対し force-push-reconstruct で recovery (`backup/ua-*-pre-clean` tag で safety net、現在は cleanup 済)。教訓: agent dispatch 前に `git fetch && git log origin/main` で base 確認、`isolation: "worktree"` 使用時も agent worktree base SHA を verify。

**初期セッション資料** (commander session orchestration 履歴):
- `docs/superpowers/dispatch/2026-05-17-pr-creation-index.md` (5 PR 一覧)
- `docs/superpowers/dispatch/2026-05-17-ua-*-pr-body.md` (各 PR body)
- `docs/superpowers/dispatch/2026-05-17-ua-*-dispatch-prompt.md` (各 dispatch brief、historical)
- memory `project_ua_initiative.md`


### その他

| 優先 | ID | 内容 | 状態・備考 |
|---|---|---|---|
| 低 | **Phase 5 E (そのうち)** | (A) `mimicanno export-undo` CLI、(B) integration contract 凍結 docs、(C) read-only Python client `mimicanno.client` | MimicRec 配置待ち。本リポ完結部分のみ着手可 |
| ✅ | **Phase 6 core (eval v2)** SHIPPED | true planner_agreement metric + confusion matrix + by_source/confidence/phase + schema 0.4.0、295 tests + mypy --strict clean。**PR #13 merged → `d2facf1` (origin/main 反映済)**。8 commits `eec623e..f811475`。spec は `docs/superpowers/specs/2026-05-17-phase6-eval-v2-design.md` 残存、plan + results note は worktree 削除で消失 (commits からの再構築は最小コスト)。残: Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec |
| ~~低~~ | ~~**G7 full-ep 再走**~~ ✅ **FULL PASS (2026-05-17 PM)** — G8 (GPU 1, 34s) + G7 (GPU 3, 58s) 完走、cam_t z anchored 0.14-0.27 m (21/23 frame UniDAC anchored、残 2 frame 端っこのみ fallback)、wrist_depth_m 0.37-0.51 m。期待 range 0.1-2.0 m 内 100%。詳細 `docs/superpowers/notes/2026-05-17-g7-full-ep-rerun-results.md`。これで Phase 5+ Replay UI / MimicRec hand mimicry / HandSignalGraph (3ae28bb) の metric 表示が gated 解除 |
| 低 | **`_vlm_dumps` schema 変化対応** | per-call dir 構造化されたので SFT loader が読めるか確認 ([[project_gemma_ft_pipeline]])。<br>**SFT loader 場所 (2026-05-17 調査)**: `/home/gayagaya/QLoRA/gemma4_vla/data/phase_label_dataset.py` (`PhaseLabelDataset` クラス)。**別リポ**。entry `train_phase_label.py`、config `configs/qlora_{e4b,26B}_phase_label.yaml`。<br>**現状**: 両 config の `results_root` は `/home/gayagaya/QLoRA/runs/so101_phase4_v5/_gemini_results_*` を指していて、**Gemma の `_vlm_dumps` ではなく Gemini 3.1 Pro Preview 出力を読んでいる** → **schema 変化の実害ゼロ**。<br>**ギャップ (loader が `_vlm_dumps` を直接読めない理由)**: (1) loader は `episode_*__seg*/{prompt,response}.txt + keyframe_*.png` を期待、(2) `_vlm_dumps` は `episode_*/_planner/call_*/` の 2 階層 + keyframe 無し、(3) planner と labeler が混在。<br>**着手時の選択肢**: (a) このまま Gemini results 使用継続、(b) `scripts/aggregate_gemma_pairs.py` 拡張で `_vlm_dumps` → loader 互換 dir に変換、(c) `phase_label_dataset.py` 側を新 schema 対応 (別リポ作業)。<br>**着手条件**: Gemma self-distill loop を回す時に再検討。それまで保留。 | G6 で判明 |
| ~~中~~ | ~~**batch_annotate.py YAML passthrough — 4B 検証**~~ ✅ **26B で代替検証済 (2026-05-17 PM)** — 本セッションで GPU 0 (A100 80GB) で `batch_annotate.py --dataset so101` を 26B 実走 (commit `869be5b` で note 追記済)。ep0/ep1 ともに `segments=5/4`, `boundaries=4/3` で `run_26B_so101.sh` 経路と完全一致 → **YAML が AnnotationConfig まで届くことを 26B コードパス上で proven**。4B 検証は redundant (同じコードパスを通る、より弱い検証になるだけ) | **代替検証の詳細**: `docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md` の「追記 (3): batch_annotate.py 経路 E2E smoke ✅」節。**26B 本走 GO 条件 (80GB GPU で SO101 ep0+ep1 が segments ≥ 2)** は既に満たした |
| ~~中~~ | ~~**26B config gap fix**~~ ✅ **MERGED (PR #19, commit `0d65616` on main 2026-05-17 18:54)** — `fix/26b-config-gap` branch (b17dd21) は **redundant、削除可**。merge は別経路 `fix/batch-annotate-yaml-passthrough` 経由 (中身は完全同一: scripts/batch_annotate.py +41 line / tests/test_batch_annotate_yaml_loading.py +165 line) | **背景**: 26B SO101 smoke で `segments=[{phase: idle}]` の degenerate 出力 (default boundary/smoother config が SO101 微弱グリッパー信号に反応せず)。4B vs 26B annotation richness fair compare の妨げ<br>**状態 (2026-05-17)**: branch `fix/26b-config-gap` (worktree `.claude/worktrees/26b-config-gap/`) に **code+test ship 済、寝かせ中**<br>**Shipped (`b17dd21`)**:<br>1. ✅ `scripts/run_26B_so101.sh` L49-50 — `--boundary-config` + `--smoother-config` 追加 (commit `7625a05`、本ブランチ前)<br>2. ✅ `scripts/batch_annotate.py` — `DATASETS` に optional `boundary_config` / `smoother_config` 追加、SO101 のみ 2 YAML 指定、gem4 は None で default fallback。`load_boundary_config_yaml` / `load_smoother_config_yaml` を `mimicanno.cli annotate` と同じパス経由で使用 (cli.py:175-176, 254-275)<br>3. ✅ `tests/test_batch_annotate_yaml_loading.py` — 5 unit tests passing (TDD red→green 確認済: fix なしで 4/5 fail、ありで 5/5 pass)。mypy: baseline 10 errors のまま、新規 0<br>**Deferred**: end-to-end 26B SO101 smoke は 80GB GPU 待ち。現環境全 4 GPU が RTX A6000 49GB で 26B (~52GB) OOM 確定。GPU 0-2 は **別ユーザー moriki の HSMR PoseEstimation** が占有中 (PID 1728670/1723238/1727047)、3 は free だが A6000<br>**Logical 検証は完了**: 4B 経路 (`batch_so101_phase4_v5.sh`) が同じ `load_*_yaml` を proven に通っているため、YAML が AnnotationConfig まで届けば downstream identical (本 unit test で届くこと verify 済)<br>**次に動かす条件**: 80GB GPU 確保時 → SO101 ep0+ep1 で `BATCH_RUNS_ROOT=/tmp/g1_smoke_26b_v2/` 実走 → `boundaries.json` candidates 非空 + segments ≥ 2 を確認 → smoke note "2026-05-17 追記" 節に結果追記 → main merge / PR 判断<br>**詳細**: `docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md` |
| 低 | **gem4 boundary/smoother YAML 作成 + 26B chain 再走** | **発見 (2026-05-17)**: 2026-05-16 完了済の gem4 26B chain (`runs/gem4_*_26B/`、3 datasets × ~210 ep) 全部 **degenerate**: `segments=1 phase=unknown`, `candidates=0` (SO101 と同じ root cause、boundary/smoother default が gem4 signals に反応せず)<br>**追加検証 (2026-05-17 PM)**: 本セッションで chain 再走 → 同じ degenerate 再現確認 → ユーザー判断で **中断**。中断時状態: `runs/gem4_pick_up_bottle_26B/` ep0-303 全更新 (5h40min, GPU 1)、`runs/gem4_open_the_jar_26B/` ep0-40 (v1) + ep41-57 (v2, 95% threshold) 更新、`runs/gem4_replace_the_cookie_26B/` 起動直後停止でほぼ未更新 (旧データ残)。`_vlm_dumps/` は出てるので SFT データとしては valuable。<br>**前提**: `mimicanno/configs/boundary/gem4_*.yaml` / `mimicanno/configs/smoother/gem4_*.yaml` 未作成 — SO101 (`so101_zero_crossing.yaml`) や Piper の同等品を gem4 用に書く必要あり<br>**Steps**:<br>1. gem4 (Franka Research 3 系) の gripper / velocity 信号特性を 1 ep 分プロット (`runs/gem4_*_26B/episode_000000__*/signals.json` から) して閾値レンジを決める<br>2. `mimicanno/configs/boundary/gem4_*.yaml` + `mimicanno/configs/smoother/gem4_*.yaml` 作成 (SO101 yaml を template に)<br>3. `scripts/batch_annotate.py` の DATASETS gem4 entries に boundary_config / smoother_config 設定 (`fix/26b-config-gap` branch 上でやるか別 branch かは判断)<br>4. 80GB GPU 確保時に 1 ep × 3 dataset で smoke、segments ≥ 2 + boundaries 非空 を確認<br>5. 全 chain 再走判断 (cost: 26B × 700 ep × ~7min ≈ 80h GPU time) | 低優先 (planner 出力 = `_vlm_dumps/*.jsonl` は degenerate 出力でも valuable な SFT data 候補)。本格再走は SFT loop 着手時 |
| 低 | gem4 設定整理 | `mimicanno/configs/robot/gem4_*.yaml` × 3 の clean-up | docs/別 PR |

### 後始末

- `/misc/dl00/gayagaya/MimicAnno-phase5d/frontend/node_modules/` — git 認識外、`rm -rf` でいつでも除去可
- `mimicanno serve` (PID 1063745) — so101_phase4_v5 配信で稼働継続中、別件なので触らない
- agent-locked worktrees `.claude/worktrees/agent-a8b2893e*` / `agent-ae08b633*` — sub-agent 由来、本体 PR は merged 済、解放手続きは agent ツール経由 (commander touch しない)
- `fix/26b-config-gap` worktree — PR #19 で別経路 merged、本 branch は redundant、いつでも削除可

---

## 未マージ PR 待ち

(なし、全て merged 2026-05-17 evening)

---

## 完了済み ✅

| ストリーム | 内容 | コミット / PR |
|---|---|---|
| S-RS | run-set switcher UI ドロップダウン | PR #9 |
| S-B2 | 境界ドラッグ PATCH + BoundaryDragLayer | `9c25b87` |
| S-UI | ダークテーマ + HandScrubBar + HandViewer サイドパネル | `68aafcf` |
| S-HG | HandSignalGraph (xyz cam_t 時系列) | `3ae28bb` |
| S-B3 | reviewed 単独トグル | `14eb192` |
| S-D | Phase 5 D EditEvent history + `mimicanno eval` CLI | `3d8bb34` |
| fix-boundary-route | `patch_boundary_route` Depends 修正 | PR #10 (`679fbf9`) |
| test-fixtures | `tests/fixtures/loadable_run/` 凍結 | `cf05727`/`59b1151`/`8292811` |
| **D r2 frontend timing** | **3 regression 修正 (Date.now → performance.now / cross-input Map ref / focusout discard) + 8 new tests** | **merge `b5050cc` (main)** |
| **D r2 backend hardening** (2026-05-17) | **B1 schema_version PATCH upgrade / B2 history order test / B3 `label_agreement`→`human_touched_fraction` rename+脚注 / B4 `client_edit_duration_ms` 600,000ms cap。15 new tests / 252 passing / mypy --strict clean** | **merge `a7d5283` (main)** |
| **G1** | batch_annotate 4B smoke (SAM3 runtime 共有 + `BATCH_RUNS_ROOT`) | `3b6899e` etc. (origin/main 済) |
| **G2** | Phase 5 D SO101 v5 UI smoke (17 events × 4 edit types) | autonomy exit 内 |
| **G3** | autonomy exit e2e sanity (SO101 3 ep) | `runs/g3_smoke_20260516_2252/` |
| **G3 再走** (2026-05-17) | 同条件再現性 PASS、wall 4.5 min (前回 5.5 min)、planner 出力 deterministic 一致 | `runs/g3_smoke_20260517_1353/` / note `2026-05-17-g3-rerun-results.md` |
| **G1 26B SO101** (2026-05-17) | A100 80GB で 26B mechanics PASS (VRAM 52 GiB)、2 ep × 7 min。planner 品質は 4B より良い兆候 (bottle→targets, gripper 具体化) | `/tmp/g1_smoke_26b/` / note `2026-05-17-g1-26b-so101-smoke-results.md` |
| **G6** | Gemma 4B planner regression | PR #24 → `1fc5c30` (`4b14639`) |
| **G7** 🟡 | Hand+HAMER pipeline mechanics PASS、cam_t anchoring 未検証 | PR #24 → `1fc5c30` (`0ed0892`) |
| **G8** | UniDAC precompute_depth | PR #24 → `1fc5c30` (`922a146`) |
| **Phase 6 core (eval v2)** (2026-05-17) | true `planner_agreement` metric + confusion matrix + by_source/confidence/phase breakdown + schema 0.4.0、295 tests + mypy --strict clean。spec `docs/superpowers/specs/2026-05-17-phase6-eval-v2-design.md` 残存 (plan + results note は worktree 削除で消失) | **PR #13 → `d2facf1` (main)** |
| **U-A1** Catalog + Job kick (2026-05-17) | `/api/datasets` + `/api/jobs` + frontend `/datasets` `/jobs` ページ + subprocess job runner | **PR #12 → `1624af5`** |
| **U-A1 follow-up** routing (2026-05-17) | App.tsx `?page=datasets` / `?page=jobs` 配線 + 5 vitest | **PR #15 → `88b9324`** |
| **U-A3** VLM dumps viewer (2026-05-17) | backend reader (`mimicanno/server/vlm_dumps.py`) + `GET /api/runs/{c}/vlm_dumps.json` + frontend `VlmPanel` + RunViewer 右スロット統合。master §2.4 を rev3 に書き換え。+17 backend / +12 vitest | **PR #14 → `9cdce19`** |
| **U-A3 rev3 schema fix** (2026-05-17) | `kind: labeler` + `call_id` 形式 + `segment_ordinal`/`attempt`/`frame_url`/`keyframe_urls`/`request_json` 整合。+32 backend / +11 vitest | **PR #17 → `cc6aa5e`** |
| **U-A2** Dataset summary (2026-05-17) | `GET /api/datasets/{name}/summary` + Summary dashboard tab。`label_diversity` = distinct phase 数。+13 backend / +8 vitest | **PR #16 → `bba681e`** |
| **U-A4** SAM3 mask overlay (2026-05-17) | annotate-time `_masks/<frame>.png` sidecar + backend routes + VideoPlayer canvas overlay (per-track color/alpha/toggle)。+20 backend / +14 vitest | **PR #18 → `e6e9b2f`** |
| **U-A5** Site-wide progress badge (2026-05-17) | header `JobsBadge` ポーリング (4s)、`?page=jobs` link。+11 vitest | **PR #20 → `747c5e7`** |
| **26B config gap fix** (2026-05-17) | `scripts/batch_annotate.py` で robot YAML を `load_boundary_config_yaml` / `load_smoother_config_yaml` 経由で AnnotationConfig へ届ける + 5 unit tests。E2E は 26B SO101 で `segments=5/4` 確認済 | **PR #19 → `51f4f0d`** |

結果 note は `docs/superpowers/notes/2026-05-17-{g1,g6,g7,g8,g1-26b}-*-smoke-results.md` / `2026-05-17-session-summary-d-r2-complete.md` 等参照。

---

## 推奨次ステップ

1. gem4 boundary/smoother YAML 作成 (gem4 26B chain の degenerate 解消、低優先)
2. Phase 5 E は MimicRec 配置待ちで保留 (低優先、autonomy 不要範囲のみ MimicAnno 単独で進められる)
3. Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec から
