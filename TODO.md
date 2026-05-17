# TODO (2026-05-17 14:35 現在)

**Autonomy window: CLOSED 2026-05-16** — Phase 5 D shipped + SO101 v5 real-data smoke (17 events × 4 edit types) green。次窓を開ける場合はユーザー判断。

**Phase 5 D r2 全部完了 (2026-05-17)**: frontend (merge `b5050cc`) + backend (merge `a7d5283`) どちらも `origin/main` 反映済。本セッション全行動の summary は `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`。

---

## 残タスク

### U-A: Dataset processing & visualization UI (新規 initiative, 2026-05-17)

**Master spec**: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (rev2 commit `1ba138d`、Critical/Important/Minor 全消化済、Opus 再レビュー通過)

**実行方式**: 本セッション (司令塔) は **dispatch 管理のみ、コード作業はしない**。各 sub-project は **別 Claude セッションが spec+plan+impl まで完結**させる。司令塔の責務は (1) dispatch 時の context 用意、(2) 完了後の整合確認 + merge 順管理、(3) sub-project が master contract に変更を要求してきた時の調停。

**状態列の凡例**: `未` / `dispatched(<branch>)` / `PR#<n>` / `merged` / `blocked(<理由>)`

| 優先 | ID | 内容 | dispatch 順 | 状態 |
|---|---|---|---|---|
| 高 | **U-A1** | Catalog + Job kick (`/api/datasets` + `/api/jobs` + frontend `/datasets` `/jobs` + subprocess job runner) | **最初に dispatch** (backend 確定が他の起点) | dispatched(`feat/ua-1-catalog-jobs`, base `70a61f2`, agent `aba3901c`, background, 2026-05-17) |
| 中 | **U-A3** | VLM dumps viewer (`_vlm_dumps/<episode_id>/` ツリーを RunViewer **右パネルのみ** に。VideoPlayer は触らない) | U-A1 と並列 dispatch 可 (master §2.4 のみ依存) | ✅ **merged** (PR #14 → `9cdce19`) — 下表 (完了済み ✅) 参照 |
| 中 | **U-A4** | SAM3 mask overlay (VideoPlayer の **canvas overlay 子のみ**。RunViewer 右パネルは触らない) | U-A1 と並列 dispatch 可 (master §2.5 のみ依存) | **IN-PROGRESS but UNCOMMITTED** — branch `feat/ua-4-mask-overlay` local-only (tip `e909069` docs のみ)、impl 全部 stash 上。下節「U-A4 status 2026-05-17 確認」参照 → **司令塔判断 3 択** |
| 中 | **U-A2** | Dataset summary (label 分布 / reviewed 率 dashboard tab) | U-A1 backend (§2.1) landed 後 | U-A1 待ち |
| 低 | **U-A5** | Site-wide progress badge (header に running jobs N) | U-A1 backend (§2.3 jobs API) landed 後 | U-A1 待ち |

#### U-A4 status 2026-05-17 確認 — 司令塔判断 3 択

**前 escalation (rev2 3 択) は解決済**: master spec rev3 (`eb389ba` / merge `f9e2e1e`) で **option 1 (pre-bake) を mandate** に決定。`tracks.json` に RLE/polygon が無いので on-the-fly オプション削除。dispatch prompt も rev3 再発行済 (`e909069`、main 反映済)。

**現状 (本セッション確認、PR #14 merge 後)**:
1. **branch `feat/ua-4-mask-overlay`**: local のみ (origin push 無し)、tip `e909069` = docs only commit、impl commit ゼロ
2. **impl は 2 段階の stash に分散** (rebase / 整合確認必要):
   - `stash@{1}` (full, 14 ファイル / +1785 行): frontend (`MaskOverlay.tsx` 等), backend (`mimicanno/masks/sidecar.py` + `mask_routes.py`), `vlm_dumps.py` rev3 align 書き換え, tests 全部。**但し `pipeline.py` 改修無し**
   - `stash@{2}` (partial, 6 ファイル / +360 行): `pipeline.py` (+5, annotate-time に mask 書き出し), `vlm_dumps.py` rev3 align, `routes.py`, `VideoPlayer.tsx`。**frontend MaskOverlay / sidecar.py / mask_routes.py 無し**
   - 両 stash が `vlm_dumps.py` / `routes.py` / `VideoPlayer.tsx` で重複 → 機械的 pop で衝突確定
3. **⚠️ main に schema drift**: PR #14 で merge した `mimicanno/server/vlm_dumps.py` が rev3 spec と一致してない:

   | field | main の code (PR #14) | rev3 spec (eb389ba) |
   |---|---|---|
   | `kind` | `"planner" / "segment"` | `"planner" / "labeler"` |
   | `call_id` planner | `"_planner/call_NNN"` | `"call_NNN"` |
   | `call_id` segment | `"s_NNN/attempt_M"` | `"s_NNN__attempt_M"` |
   | `segment_ordinal` / `attempt` / `frame_url` / `keyframe_urls` / `request_json` | 無し | 必須 |
   | `failed` 判定 (segment) | response.txt missing or non-JSON | "later attempt_M+1 exists" |

   stash@{1} / @{2} の `vlm_dumps.py` 書き換えはこの drift を直す目的でもある。
4. **その他関連 stash** (本件無関係):
   - `stash@{0}` = "ua-3 rev3 test file"
   - `stash@{3}` = "stray ua-3 dispatch from parallel session"

**司令塔判断 3 択**:

| | アプローチ | 利点 | 欠点 |
|---|---|---|---|
| **A. 司令塔自身で fix-up** | rebase `feat/ua-4-mask-overlay` → main、stash@{1} apply → stash@{2} から `pipeline.py` 手動マージ、test 走らせて commit → push → PR | 既存作業 100% 継承、最短 | stash@{1}/@{2} 重複ファイルの衝突解決を commander がやる必要、context 切替コスト |
| **B. 新規 sub-Claude rev3 dispatch で start over** | stash を参考保存のまま放置、`docs/superpowers/dispatch/2026-05-17-ua-4-dispatch-prompt.md` (rev3) を新 agent に dispatch | fresh context、schema drift も込みで一貫実装可、コードレビュー独立 | 既存 stash の作業がほぼ無駄、wall clock 増 |
| **C. 本セッション (U-A3 dispatch session) に継承させる** | 私が stash@{1} を base に rev3 整合の rebase 作業 + 不足分 (pipeline.py emit) を統合 + tests + PR | 司令塔 context は守る、U-A3 で得た repo 知識を流用、コスト中 | A と同じ衝突解決を私がやる、U-A3 と U-A4 の責務混在 |

**並行課題 (どの選択でも対応必要)**:
- main の `vlm_dumps.py` schema drift — 独立 PR で先に直すか、U-A4 PR に同梱するかの判断。stash@{1} の rewrite を切り出して独立 PR にするのが contract drift の影響範囲としてクリーン (U-A3 frontend は rev3 schema 前提なら別途調整)。**フロントエンドが今 main で動いてるか** が要確認 (PR #14 の `VlmPanel.tsx` は old schema 期待のはずなので動いてる)。

**深掘り済みファイル参照** (再調査不要):
- `mimicanno/object_tracker/propagator.py:486-493` — MaskCache 生成箇所
- `mimicanno/pipeline.py:881-998` — vlm_labeler への受け渡し
- `mimicanno/vlm_overlay.py` — mask 消費後 discard
- `runs/so101_phase4_v5/episode_000021__b7d99709c19d/tracks.json` — schema 実例 (bbox/score のみ)
- master spec rev3 `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` §2.4 / §2.5 / §3.4
- dispatch prompt rev3 `docs/superpowers/dispatch/2026-05-17-ua-4-dispatch-prompt.md`

---

#### Dispatch 時に司令塔が sub-Claude に渡すもの (zero-context 想定の完全 brief)

**A. 設計参照**

1. master spec path: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (rev2 commit `1ba138d`) + 該当 sub-project セクション (§3.X) + **master §2 contract への準拠厳守**
2. master §8 テンプレに従って `docs/superpowers/specs/2026-05-XX-ua-<id>-design.md` を新規作成
3. 関連既存コードへの path 明示:
   - 共通: `mimicanno/server/routes.py` (catch-all は最後尾、新 route は前に register), `mimicanno/server/app.py` (CORS), `tests/server/conftest.py` (`tmp_runs_root_loadable` 等の frozen fixture)
   - U-A1: `mimicanno/cli.py`, `scripts/batch_annotate_4B.py`, frontend `frontend/src/components/RunList.tsx`
   - U-A3: `frontend/src/components/RunViewer.tsx` (右パネル領域のみ)
   - U-A4: `frontend/src/components/VideoPlayer.tsx` (canvas overlay の子要素のみ)
4. **触ってよい / ダメな範囲を明文化** (file collision 回避): U-A3 = RunViewer 右パネル / U-A4 = VideoPlayer canvas overlay / 互いに相手のコンポーネントは触らない

**B. 規約 / 環境**

5. **autonomy 窓 CLOSED (2026-05-16)**: sub-Claude は spec / plan / impl まで進めて良いが、**main への merge と destructive op はユーザー承認待ち**。PR push は OK
6. **`sudo` 絶対禁止** (memory `feedback_no_sudo.md`)。install 必要時は `uv`, `pip --user`, `pipx`, `conda`, `cargo install`, バイナリ `~/bin/` 直配置のみ
7. **test / lint コマンド**:
   - backend: `uv run pytest tests/server/ -v`, `uv run pytest tests/ -v` (full), `uv run mypy --strict mimicanno/`
   - frontend: `cd frontend && npm test` (vitest, jsdom)
   - 既存 baseline 252 passing + mypy strict clean を退行させないこと
8. **`.venv` 使い分け**: MimicAnno 本体の `.venv` (uv) は本 sub-project (server / frontend) で **使う**。CLAUDE.md にある「`.venv` 使わない」は Phase 3 pipeline (hand / depth) 用注記なので適用外
9. **U-A4 のみ追加**: `feedback_sam3_use_external_cam.md` (SAM3 grounding は overhead/external cam を使う) を読む。tracks.json が wrist cam ベースだと壊れるケースに注意

**C. Git 規約**

10. branch base: `origin/main` の最新 (dispatch 時の SHA を司令塔がメモ)
11. branch 命名: `feat/ua-<id>-<short>` (例: `feat/ua-1-catalog-jobs`, `feat/ua-3-vlm-panel`)
12. commit prefix: `feat(ua-<id>):` / `test(ua-<id>):` / `docs(ua-<id>):` で統一 (既存 convention 整合)
13. PR タイトル prefix: `feat(ua-<id>):` 、push 先は `origin`
14. **PR body 必須行**: `Touches master §2 contract: yes/no` (yes の場合は理由 + 提案差分を併記)。司令塔はこの行を grep で監視
15. **レビュー / merge**: 司令塔セッション (本セッションまたは継承先) が Opus subagent でレビュー → ユーザー最終承認 → merge。sub-Claude は self-merge しない
16. U-A3 / U-A4 が U-A1 着地前に impl 完了した場合: PR は待機可、merge 前に post-U-A1 main へ rebase

**D. 報告事項テンプレ (sub-Claude → 司令塔)**

17. spec path + plan path + impl 完了範囲 (機能 / file リスト)
18. テスト件数 (new / total / baseline 比)
19. master contract に変更要求があれば PR body と本報告の両方に flag
20. 未解決の risk / 既知の TODO

#### 司令塔の監視ポイント

- **contract drift**: sub-project PR の `Touches master §2 contract: yes` を grep で検出 → 停止 → master spec を先に revise → 当該 PR は revise 後 rebase
- **依存順序**: U-A2 / U-A5 を U-A1 backend landed 前に dispatch しない
- **merge 順序**: U-A1 → (U-A3 ∥ U-A4 任意順、rebase あり) → U-A2 → U-A5
- **file collision**: U-A3 / U-A4 が予定外の file (相手側 component, server/routes.py の同じ block 等) を触る PR を出したら一旦止める

#### Cross-session 継続

5 sub-project を 1 commander セッションで全部回すのは非現実的。**次の commander セッション**が resume するための情報源:

- 本 TODO §「U-A:」(状態列が source of truth)
- memory `project_ua_initiative.md` (initiative 概要 + 司令塔ロールの明示)
- master spec rev2 + 最新 rev (commit log で確認)

次の commander が引き継ぐ際の最初の作業: `git log --oneline | grep "feat(ua-" ` + `gh pr list --search "feat(ua-"` (gh 不可時は GitHub UI) で merged / open PR を棚卸し、状態列を更新してから次 dispatch を準備。

### その他

| 優先 | ID | 内容 | 状態・備考 |
|---|---|---|---|
| 低 | **Phase 5 E (そのうち)** | (A) `mimicanno export-undo` CLI、(B) integration contract 凍結 docs、(C) read-only Python client `mimicanno.client` | MimicRec 配置待ち。本リポ完結部分のみ着手可 |
| ✅ | **Phase 6 core (eval v2)** SHIPPED | true planner_agreement metric + confusion matrix + by_source/confidence/phase + schema 0.4.0、295 tests + mypy --strict clean。**PR #13 merged → `d2facf1` (origin/main 反映済)**。8 commits `eec623e..f811475`。spec は `docs/superpowers/specs/2026-05-17-phase6-eval-v2-design.md` 残存、plan + results note は worktree 削除で消失 (commits からの再構築は最小コスト)。残: Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec |
| 低 | **G7 full-ep 再走** | G8 `--limit` 無しで全フレーム depth 生成 → HAMER 再走で `cam_t` metric anchoring 確認 | 初回 PARTIAL の follow-up。優先度低 |
| 低 | **`_vlm_dumps` schema 変化対応** | per-call dir 構造化されたので SFT loader が読めるか確認 ([[project_gemma_ft_pipeline]])。<br>**SFT loader 場所 (2026-05-17 調査)**: `/home/gayagaya/QLoRA/gemma4_vla/data/phase_label_dataset.py` (`PhaseLabelDataset` クラス)。**別リポ**。entry `train_phase_label.py`、config `configs/qlora_{e4b,26B}_phase_label.yaml`。<br>**現状**: 両 config の `results_root` は `/home/gayagaya/QLoRA/runs/so101_phase4_v5/_gemini_results_*` を指していて、**Gemma の `_vlm_dumps` ではなく Gemini 3.1 Pro Preview 出力を読んでいる** → **schema 変化の実害ゼロ**。<br>**ギャップ (loader が `_vlm_dumps` を直接読めない理由)**: (1) loader は `episode_*__seg*/{prompt,response}.txt + keyframe_*.png` を期待、(2) `_vlm_dumps` は `episode_*/_planner/call_*/` の 2 階層 + keyframe 無し、(3) planner と labeler が混在。<br>**着手時の選択肢**: (a) このまま Gemini results 使用継続、(b) `scripts/aggregate_gemma_pairs.py` 拡張で `_vlm_dumps` → loader 互換 dir に変換、(c) `phase_label_dataset.py` 側を新 schema 対応 (別リポ作業)。<br>**着手条件**: Gemma self-distill loop を回す時に再検討。それまで保留。 | G6 で判明 |
| 中 | **26B config gap fix — E2E smoke ✅ shipped、merge ready** (2026-05-17 17:00 完了) | **背景**: 26B SO101 smoke で `segments=[{phase: idle}]` の degenerate 出力 (default boundary/smoother config が SO101 微弱グリッパー信号に反応せず)。4B vs 26B annotation richness fair compare の妨げ<br>**状態 (2026-05-17)**: branch `fix/26b-config-gap` (worktree `.claude/worktrees/26b-config-gap/`) に **code+test ship 済、寝かせ中**<br>**Shipped (`b17dd21`)**:<br>1. ✅ `scripts/run_26B_so101.sh` L49-50 — `--boundary-config` + `--smoother-config` 追加 (commit `7625a05`、本ブランチ前)<br>2. ✅ `scripts/batch_annotate.py` — `DATASETS` に optional `boundary_config` / `smoother_config` 追加、SO101 のみ 2 YAML 指定、gem4 は None で default fallback。`load_boundary_config_yaml` / `load_smoother_config_yaml` を `mimicanno.cli annotate` と同じパス経由で使用 (cli.py:175-176, 254-275)<br>3. ✅ `tests/test_batch_annotate_yaml_loading.py` — 5 unit tests passing (TDD red→green 確認済: fix なしで 4/5 fail、ありで 5/5 pass)。mypy: baseline 10 errors のまま、新規 0<br>**Deferred**: end-to-end 26B SO101 smoke は 80GB GPU 待ち。現環境全 4 GPU が RTX A6000 49GB で 26B (~52GB) OOM 確定。GPU 0-2 は **別ユーザー moriki の HSMR PoseEstimation** が占有中 (PID 1728670/1723238/1727047)、3 は free だが A6000<br>**Logical 検証は完了**: 4B 経路 (`batch_so101_phase4_v5.sh`) が同じ `load_*_yaml` を proven に通っているため、YAML が AnnotationConfig まで届けば downstream identical (本 unit test で届くこと verify 済)<br>**次に動かす条件**: 80GB GPU 確保時 → SO101 ep0+ep1 で `BATCH_RUNS_ROOT=/tmp/g1_smoke_26b_v2/` 実走 → `boundaries.json` candidates 非空 + segments ≥ 2 を確認 → smoke note "2026-05-17 追記" 節に結果追記 → main merge / PR 判断<br>**詳細**: `docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md` |
| 低 | **gem4 boundary/smoother YAML 作成 + 26B chain 再走** | **発見 (2026-05-17)**: 2026-05-16 完了済の gem4 26B chain (`runs/gem4_*_26B/`、3 datasets × ~210 ep) 全部 **degenerate**: `segments=1 phase=unknown`, `candidates=0` (SO101 と同じ root cause、boundary/smoother default が gem4 signals に反応せず)<br>**追加検証 (2026-05-17 PM)**: 本セッションで chain 再走 → 同じ degenerate 再現確認 → ユーザー判断で **中断**。中断時状態: `runs/gem4_pick_up_bottle_26B/` ep0-303 全更新 (5h40min, GPU 1)、`runs/gem4_open_the_jar_26B/` ep0-40 (v1) + ep41-57 (v2, 95% threshold) 更新、`runs/gem4_replace_the_cookie_26B/` 起動直後停止でほぼ未更新 (旧データ残)。`_vlm_dumps/` は出てるので SFT データとしては valuable。<br>**前提**: `mimicanno/configs/boundary/gem4_*.yaml` / `mimicanno/configs/smoother/gem4_*.yaml` 未作成 — SO101 (`so101_zero_crossing.yaml`) や Piper の同等品を gem4 用に書く必要あり<br>**Steps**:<br>1. gem4 (Franka Research 3 系) の gripper / velocity 信号特性を 1 ep 分プロット (`runs/gem4_*_26B/episode_000000__*/signals.json` から) して閾値レンジを決める<br>2. `mimicanno/configs/boundary/gem4_*.yaml` + `mimicanno/configs/smoother/gem4_*.yaml` 作成 (SO101 yaml を template に)<br>3. `scripts/batch_annotate.py` の DATASETS gem4 entries に boundary_config / smoother_config 設定 (`fix/26b-config-gap` branch 上でやるか別 branch かは判断)<br>4. 80GB GPU 確保時に 1 ep × 3 dataset で smoke、segments ≥ 2 + boundaries 非空 を確認<br>5. 全 chain 再走判断 (cost: 26B × 700 ep × ~7min ≈ 80h GPU time) | 低優先 (planner 出力 = `_vlm_dumps/*.jsonl` は degenerate 出力でも valuable な SFT data 候補)。本格再走は SFT loop 着手時 |
| 低 | gem4 設定整理 | `mimicanno/configs/robot/gem4_*.yaml` × 3 の clean-up | docs/別 PR |

### 後始末

- `/misc/dl00/gayagaya/MimicAnno-phase5d/frontend/node_modules/` — git 認識外、`rm -rf` でいつでも除去可
- `mimicanno serve` (PID 1063745) — so101_phase4_v5 配信で稼働継続中、別件なので触らない

---

## 未マージ PR 待ち

| branch | 内容 | 状態 |
|---|---|---|
| `test/loadable-run-fixture` | `tests/fixtures/loadable_run/` 凍結 + conftest 切替 (5 commit、224 passed) | origin push 済、Opus レビュー APPROVED (ブラウザで作成: <https://github.com/takaki-maeda-99/MimicAnno/pull/new/test/loadable-run-fixture>)。Title `test(fixtures): freeze loadable_run for CI (no real-data dependency)`、body 雛形は `docs/superpowers/plans/2026-05-17-loadable-run-fixture-plan.md` の Summary/Exit criteria 抜粋で十分 |
| `docs/g-smoke-results` | G6/G7/G8 GPU smoke 結果 (3 commit + TODO 更新) | origin push 済、PR 本文準備済 (ブラウザで作成: <https://github.com/takaki-maeda-99/MimicAnno/pull/new/docs/g-smoke-results>) |
| `docs/g4-gem4-smoke` | G4 gem4 smoke 結果 (commit `5f8faa2`) | 別セッション、status 確認要 |

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
| **G6** | Gemma 4B planner regression (`docs/g-smoke-results`) | `6ca0a43` |
| **G7** 🟡 | Hand+HAMER pipeline mechanics PASS、cam_t anchoring 未検証 (`docs/g-smoke-results`) | `633ca13` |
| **G8** | UniDAC precompute_depth (`docs/g-smoke-results`) | `158b647` |
| **U-A3** (2026-05-17) | VLM dumps viewer e2e: backend reader (`mimicanno/server/vlm_dumps.py`) + `GET /api/runs/{c}/vlm_dumps.json` + frontend `VlmPanel` + RunViewer 右スロット統合。master §2.4 を rev3 に書き換え (`*.jsonl` flat 想定 → run-set 直下 `_planner/`+`s_NNN/attempt_M/` ツリー)。code review pass (path-traversal fix 含む)。+17 backend tests (254 pass) / +12 vitest (135 pass) / mypy server strict clean | PR #14 → merge `9cdce19` (main) / spec `docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md` |

結果 note は `docs/superpowers/notes/2026-05-17-{g1,g6,g7,g8}-*-smoke-results.md` 等。各 G の詳細・surprise はそれぞれの note 参照。
**本セッション D r2 全完了サマリー**: `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`

---

## 推奨次ステップ

1. `docs/g-smoke-results` を PR 作成 → main マージ (`test/loadable-run-fixture` も同様)
2. ~~D r2 backend~~ ✅ DONE (`a7d5283` merge)
3. `run_26B_so101.sh` の config gap 修正 (中優先、26B vs 4B fair compare に必要)
4. Phase 5 E は MimicRec 配置待ちで保留 (低優先、autonomy 不要範囲のみ MimicAnno 単独で進められる)
