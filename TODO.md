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
| 中 | **U-A3** | VLM dumps viewer (`_vlm_dumps/<episode_id>/` ツリーを RunViewer **右パネルのみ** に。VideoPlayer は触らない) | U-A1 と並列 dispatch 可 (master §2.4 のみ依存) | **branch pushed (b918c3e)**, PR 未作成 (gh CLI 無し) — master §2.4 を rev3 に書き換え済 (commander 承認、commit `3f484ad`)。code review pass (path-traversal fix 含む 17 件 backend + 12 frontend new test)。手動 PR open 要 |
| 中 | **U-A4** | SAM3 mask overlay (VideoPlayer の **canvas overlay 子のみ**。RunViewer 右パネルは触らない) | U-A1 と並列 dispatch 可 (master §2.5 のみ依存) | 未 |
| 中 | **U-A2** | Dataset summary (label 分布 / reviewed 率 dashboard tab) | U-A1 backend (§2.1) landed 後 | U-A1 待ち |
| 低 | **U-A5** | Site-wide progress badge (header に running jobs N) | U-A1 backend (§2.3 jobs API) landed 後 | U-A1 待ち |

#### U-A4 escalation (2026-05-17, agent `a3924de4`) — 司令塔判断待ち

Sub-Claude が dispatch §10.1「`tracks.json` schema を最初に確認、mask データ無ければ escalate」の明示指示通りに止まった。**code / branch / spec / plan いずれも未着手**。

**事実関係**:
- `tracks.json` の `samples[]` は `{bbox, frame, score, time_sec}` **のみ** — RLE / polygon 無し (例: `runs/so101_phase4_v5/episode_000021__b7d99709c19d/tracks.json`)
- **master spec L272「on-the-fly from tracks.json polygons/RLE」は disk reality と食い違い** — spec の事実誤認
- mask 自体は存在: `mimicanno/object_tracker/propagator.py:486-493` で `mask_image_size_px` set 時に per-frame RLE を `MaskCache` に集める → `mimicanno/pipeline.py:881-998` で `vlm_labeler` overlay 描画に消費 → **discard** (disk に書かれない transient)
- HTTP contract (§2.5: paths / 200/204/400/404 / RGBA PNG / meta.json shape) は **どの実装でも変わらない** → §2 改訂は不要

**3 択 (司令塔決定)**:

| | アプローチ | spec 変更 | pipeline 変更 | 既存 run の挙動 | コスト |
|---|---|---|---|---|---|
| **1. Pre-bake** (agent 推奨、§3.4 既 authorize) | `pipeline.py` を改修して MaskCache を `runs/<rs>/<canonical>/_masks/<frame>.png` に書き出す。spec L272 の文言だけ修正 (RLE/polygon → pre-baked PNG sidecar) | L272 のみ wording fix (§2 contract は不変) | あり (annotate path に sidecar emit 追加) | 再 annotate するまで 204 / 空 meta。one-shot backfill CLI を別途用意可 | annotate 再走必要 |
| 2. Spec 改訂 (tracks.json に RLE 追加) | §2.5 / §6 schema に RLE field 追加、on-the-fly 路線堅持 | **§2.5 / §6 改訂** (autonomy 閉じてるので要承認) | あり (propagator → tracks.json writer に RLE 追記) | 同じく再 annotate 要 | tracks.json ファイルサイズ増、schema 変更が U-A3 等他 sub-project に波及するか要確認 |
| 3. Bbox downgrade | mask やめて bbox 矩形を描く。spec §2.5 の「alpha = mask presence」を「bbox interior」に書き換え | **§2.5 contract 改訂** | 無し | 既存 run でそのまま動く | overlay の意味的価値が下がる (mask の精緻さが失われる) |

**司令塔観点 cross-cut**:
- **U-A3 も ESCALATED 中** ([[project_ua3_vlm_dumps_schema_drift]]、§2.4 の `*.jsonl` 記述が事実誤認)。master spec §2 / §3 / §6 にもう 1 ラウンド reviewer を入れて L272 + §2.4 + 他類似箇所をまとめて修正するのが効率的かもしれない
- U-A1 (catalog/jobs) は background 進行中・spec 整合は別問題
- 選択 1 を採る場合: pipeline.py への追記は U-A1 / U-A2 の job runner / dataset summary territory と微妙に近いが、annotate path に sidecar emit を足すだけなので衝突は小さいはず

**次アクション (司令塔)**:
1. 3 択から決める (推奨: 1)
2. master spec L272 (および §2.4 if pre-bake) を rev3 として修正コミット → SHA を新 dispatch prompt に書く
3. agent `a3924de4` に SendMessage で「option X で続行、spec rev3 SHA は ...」と渡せば context 維持で resume 可能 (新 worktree 不要)。あるいは escalation 結果を踏まえた新 dispatch prompt を書き直して別 agent で start over

**深掘り済みファイル参照** (再調査不要):
- `mimicanno/object_tracker/propagator.py:486-493` — MaskCache 生成箇所
- `mimicanno/pipeline.py:881-998` — vlm_labeler への受け渡し
- `mimicanno/vlm_overlay.py` — mask 消費後 discard
- `runs/so101_phase4_v5/episode_000021__b7d99709c19d/tracks.json` — schema 実例

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
| ✅ | **Phase 6 core (eval v2)** | true planner_agreement metric + confusion matrix + by_source/confidence/phase + schema 0.4.0 | branch `worktree-phase6-eval-v2` (origin push 済、PR TBD)。詳細: `docs/superpowers/notes/2026-05-17-phase6-eval-v2-results.md`。残: Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec |
| 低 | **G7 full-ep 再走** | G8 `--limit` 無しで全フレーム depth 生成 → HAMER 再走で `cam_t` metric anchoring 確認 | 初回 PARTIAL の follow-up。優先度低 |
| 低 | **`_vlm_dumps` schema 変化対応** | per-call dir 構造化されたので SFT loader が読めるか確認 ([[project_gemma_ft_pipeline]])。<br>**SFT loader 場所 (2026-05-17 調査)**: `/home/gayagaya/QLoRA/gemma4_vla/data/phase_label_dataset.py` (`PhaseLabelDataset` クラス)。**別リポ**。entry `train_phase_label.py`、config `configs/qlora_{e4b,26B}_phase_label.yaml`。<br>**現状**: 両 config の `results_root` は `/home/gayagaya/QLoRA/runs/so101_phase4_v5/_gemini_results_*` を指していて、**Gemma の `_vlm_dumps` ではなく Gemini 3.1 Pro Preview 出力を読んでいる** → **schema 変化の実害ゼロ**。<br>**ギャップ (loader が `_vlm_dumps` を直接読めない理由)**: (1) loader は `episode_*__seg*/{prompt,response}.txt + keyframe_*.png` を期待、(2) `_vlm_dumps` は `episode_*/_planner/call_*/` の 2 階層 + keyframe 無し、(3) planner と labeler が混在。<br>**着手時の選択肢**: (a) このまま Gemini results 使用継続、(b) `scripts/aggregate_gemma_pairs.py` 拡張で `_vlm_dumps` → loader 互換 dir に変換、(c) `phase_label_dataset.py` 側を新 schema 対応 (別リポ作業)。<br>**着手条件**: Gemma self-distill loop を回す時に再検討。それまで保留。 | G6 で判明 |
| 中 | **26B config gap fix — E2E smoke ✅ shipped、merge ready** (2026-05-17 17:00 完了) | **背景**: 26B SO101 smoke で `segments=[{phase: idle}]` の degenerate 出力 (default boundary/smoother config が SO101 微弱グリッパー信号に反応せず)。4B vs 26B annotation richness fair compare の妨げ<br>**状態 (2026-05-17)**: branch `fix/26b-config-gap` (worktree `.claude/worktrees/26b-config-gap/`) に **code+test ship 済、寝かせ中**<br>**Shipped (`b17dd21`)**:<br>1. ✅ `scripts/run_26B_so101.sh` L49-50 — `--boundary-config` + `--smoother-config` 追加 (commit `7625a05`、本ブランチ前)<br>2. ✅ `scripts/batch_annotate.py` — `DATASETS` に optional `boundary_config` / `smoother_config` 追加、SO101 のみ 2 YAML 指定、gem4 は None で default fallback。`load_boundary_config_yaml` / `load_smoother_config_yaml` を `mimicanno.cli annotate` と同じパス経由で使用 (cli.py:175-176, 254-275)<br>3. ✅ `tests/test_batch_annotate_yaml_loading.py` — 5 unit tests passing (TDD red→green 確認済: fix なしで 4/5 fail、ありで 5/5 pass)。mypy: baseline 10 errors のまま、新規 0<br>**Deferred**: end-to-end 26B SO101 smoke は 80GB GPU 待ち。現環境全 4 GPU が RTX A6000 49GB で 26B (~52GB) OOM 確定。GPU 0-2 は **別ユーザー moriki の HSMR PoseEstimation** が占有中 (PID 1728670/1723238/1727047)、3 は free だが A6000<br>**Logical 検証は完了**: 4B 経路 (`batch_so101_phase4_v5.sh`) が同じ `load_*_yaml` を proven に通っているため、YAML が AnnotationConfig まで届けば downstream identical (本 unit test で届くこと verify 済)<br>**次に動かす条件**: 80GB GPU 確保時 → SO101 ep0+ep1 で `BATCH_RUNS_ROOT=/tmp/g1_smoke_26b_v2/` 実走 → `boundaries.json` candidates 非空 + segments ≥ 2 を確認 → smoke note "2026-05-17 追記" 節に結果追記 → main merge / PR 判断<br>**詳細**: `docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md` |
| 低 | **gem4 boundary/smoother YAML 作成 + 26B chain 再走** | **発見 (2026-05-17)**: 2026-05-16 完了済の gem4 26B chain (`runs/gem4_*_26B/`、3 datasets × ~210 ep) 全部 **degenerate**: `segments=1 phase=unknown`, `candidates=0` (SO101 と同じ root cause、boundary/smoother default が gem4 signals に反応せず)<br>**前提**: `mimicanno/configs/boundary/gem4_*.yaml` / `mimicanno/configs/smoother/gem4_*.yaml` 未作成 — SO101 (`so101_zero_crossing.yaml`) や Piper の同等品を gem4 用に書く必要あり<br>**Steps**:<br>1. gem4 (Franka Research 3 系) の gripper / velocity 信号特性を 1 ep 分プロット (`runs/gem4_*_26B/episode_000000__*/signals.json` から) して閾値レンジを決める<br>2. `mimicanno/configs/boundary/gem4_*.yaml` + `mimicanno/configs/smoother/gem4_*.yaml` 作成 (SO101 yaml を template に)<br>3. `scripts/batch_annotate.py` の DATASETS gem4 entries に boundary_config / smoother_config 設定 (`fix/26b-config-gap` branch 上でやるか別 branch かは判断)<br>4. 80GB GPU 確保時に 1 ep × 3 dataset で smoke、segments ≥ 2 + boundaries 非空 を確認<br>5. 全 chain 再走判断 (cost: 26B × 700 ep × ~7min ≈ 80h GPU time) | 低優先 (planner 出力 = `_vlm_dumps/*.jsonl` は degenerate 出力でも valuable な SFT data 候補)。本格再走は SFT loop 着手時 |
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
| `feat/ua-3-vlm-panel` | U-A3 VLM dumps viewer (7 commit 含 master §2.4 rev3 + code-review fix)。backend +17 test (254 pass)、frontend +12 vitest (135 pass)、mypy server clean | origin push 済 (`b918c3e`)、自己 code review APPROVED with fixes applied。**§2.4 rev3 を rewrite している点を PR body に明記要** (commander 承認済の commit `3f484ad`)。PR 作成: <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-3-vlm-panel> |

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

結果 note は `docs/superpowers/notes/2026-05-17-{g1,g6,g7,g8}-*-smoke-results.md` 等。各 G の詳細・surprise はそれぞれの note 参照。
**本セッション D r2 全完了サマリー**: `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`

---

## 推奨次ステップ

1. `docs/g-smoke-results` を PR 作成 → main マージ (`test/loadable-run-fixture` も同様)
2. ~~D r2 backend~~ ✅ DONE (`a7d5283` merge)
3. `run_26B_so101.sh` の config gap 修正 (中優先、26B vs 4B fair compare に必要)
4. Phase 5 E は MimicRec 配置待ちで保留 (低優先、autonomy 不要範囲のみ MimicAnno 単独で進められる)
