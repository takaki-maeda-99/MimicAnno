# TODO (2026-05-16 現在)

## 完了済み ✅

| ストリーム | 内容 | コミット |
|---|---|---|
| Hand pipeline / HV | pinch distance、hand viewer T1-T5+axes、regen | main 済 |
| S-RS | run-set switcher UI ドロップダウン | PR #9 (main) |
| S-B2 | 境界ドラッグ PATCH + BoundaryDragLayer | `9c25b87` (main) |
| S-UI | ダークテーマ + HandScrubBar + HandViewer サイドパネル | `68aafcf` (main) |
| S-HG | HandSignalGraph — xyz cam_t 時系列グラフ + 外れ値ロバストレンジ | `3ae28bb` (main) |
| S-B3 | reviewed 単独トグル — backend + frontend + tests | `14eb192` (main) |
| origin push | 17 コミットを `origin/main` に push 済 | `041acdd..3a75cca` |

---

## 残タスク

### 1. S-D — Evaluation harness — `feat/phase5-d-eval-harness`

spec/plan 完成、実装ゼロ:

- [x] spec: `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` (rev1)
- [x] plan: `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` (rev1)
- [ ] **T1〜T3**: `EditEvent` dataclass + `AnnotationResult.history` + schema v2.0 bump
- [ ] **T4〜T7**: `_build_event` + `apply_edit` 拡張 + server tests
- [ ] **T8〜T10**: `mimicanno/eval/` package (`metrics.py` + `render.py` + CLI)
- [ ] **T11**: frontend — phase `<select>` focusin/change 計測 hook
- [ ] **T12**: mypy --strict + 全 regression
- [ ] **T13**: 手動 smoke (SO101 v5)
- [ ] **T14〜T15**: docs + memory
- [ ] **main にマージ**

---

### 2. その他 (低優先度)

- **gem4 新ロボット設定**: `mimicanno/configs/robot/gem4_*.yaml` x3 + run scripts — 別 PR で整理
- **テストギャップ**: `tests/fixtures/loadable_run/` に合成固定データをコミットして CI 対応 (詳細は git 履歴の旧 TODO 参照)

---

### 3. 別セッション作業中の未 push コミット (触らない)

local main が origin/main より **4 commits ahead** (15時間前、gayagaya 名義)。別のアクティブセッションが作業中の可能性があるため、このセッションからは push しない:

- `3b6899e feat(batch_annotate): share SAM3 runtime + BATCH_RUNS_ROOT override`
- `0e45447 feat(pipeline): add preloaded_sam3_runtime to AnnotateRequest`
- `ce678b4 chore(gitignore): exclude docs/superpowers/ and working logs from git`
- `79bdbcd refactor(sam3_runtime): split close() into _close_all_sessions() + final teardown`

---

## 推奨次ステップ

```
S-D impl+merge (Phase 5 D)
```

---

## GPU 実機テスト未消化 (2026-05-16 棚卸し, rev1 review 反映)

GPU が必須でまだ実機 smoke が通っていない項目。Phase 5 autonomy 窓を閉じるための実データ検証群。

### 共通前提 (G1〜G4 を始める前に揃える)
- Python/env: `hamer/.hamer/bin/python` + `PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC` (depth/warp/fuse 単体は `conda activate unidac`)
- データ: `~/MimicRec/datasets/SO101` (詳細は [[project_so101_dataset]])
- SAM3 ckpt: 同 memory のパス
- Gemma weights: HF cache symlink 済 ([[project_gemma4b_planner_smoke]])
- 互いに干渉しないよう `nvidia-smi` で GPU 占有状況を先に確認

### G1. batch_annotate 実機 smoke ⚠️ 別セッション作業中・本セッションからは触らない
- **状態 (2026-05-16 確認)**: 別セッションが実機検証を進めている。未 push の 4 コミット (`79bdbcd`/`ce678b4`/`0e45447`/`3b6899e`) はそちらの成果物。本セッションからは push / 改変しない。
- 対象スクリプト: `scripts/batch_annotate.py` および `scripts/batch_annotate_4B.py` (両方 `BATCH_RUNS_ROOT` 対応)
- 対象コミット (ローカル main、未 push):
  - `3b6899e feat(batch_annotate): share SAM3 runtime + BATCH_RUNS_ROOT override`
  - `0e45447 feat(pipeline): add preloaded_sam3_runtime to AnnotateRequest`
  - `79bdbcd refactor(sam3_runtime): split close() into _close_all_sessions() + final teardown`
- **⚠ 26B variant VRAM 制約 (2026-05-16 確認, このセッション)**: `batch_annotate.py` (26B Unsloth + QLoRA) は手元 RTX A6000 48 GB では VRAM 不足で起動不可。以後 G1 検証は `batch_annotate_4B.py` のみで行い、26B 経路は VRAM 余裕のあるホストで別途実施する。
- [ ] SO101 で 2 ep 以上を **同一 SAM3 runtime 共有**で連続 annotate (4B variant のみ; 26B は VRAM 不足で skip)
- [ ] VRAM delta が ep 境界で **< 200 MB** に収まること (`nvidia-smi --query-gpu=memory.used` を ep 前後で記録)
- [ ] `_close_all_sessions()` 呼び出しを **ログで確認** (`pipeline.py:905` を経由するはず、ep 数 = call 数 になること)
- [ ] 最終 ep 後の `close()` で全 session が破棄されること
- [ ] `BATCH_RUNS_ROOT=/tmp/foo` 上書きで run がそこに落ちること
- [ ] 着手前に別セッション handoff note と branch 状態を確認
- [ ] **(blocked) 26B variant 実機 smoke** — VRAM 余裕のあるホスト確保後に別途実行

### G2. Phase 5 D — SO101 v5 手動 smoke (T13) ⚠️ 別セッション作業中・本セッションからは触らない
- **状態 (2026-05-16 22:00 確認)**: `/misc/dl00/gayagaya/MimicAnno-phase5d` worktree で別セッションが smoke 実行中。`mimicanno serve` (PID 1460990) + `vite` (PID 1460389) 稼働中、`/tmp/mimicanno-d-smoke.log` / `/tmp/vite-d-smoke.log` 出力中。frontend 3 ファイルに未コミット変更あり。merge / push / phase5d worktree への書き込みは本セッションから一切行わない。
- **状態の補足**: D r1 実装は `feat/phase5-d-eval-harness` ブランチに ship 済 (`4fdd553`, `caff5cf`, `6b65ae6`) だが **main 未 merge**。`mimicanno eval` CLI も main には未だ存在しない。
- [ ] 前提: `feat/phase5-d-eval-harness` を main に merge (S-D 実装と合流) → `mimicanno eval` が CLI に現れることを `mimicanno --help` で確認
- [ ] 新規 run を annotate → `mimicanno serve` 起動 → frontend で relabel/boundary/reviewed/labels 4 種を編集
- [ ] `mimicanno eval <run>` で history が読まれ metrics + render が出ること
- [ ] phase `<select>` focusin/change hook の計測値が EditEvent に乗ること (history JSON を直接 grep して `dwell_ms` などのフィールド存在確認)
- annotate 部分のみ GPU、eval/edit 自体は CPU

### G3. autonomy exit 用 end-to-end 実データ sanity check ⏸ 中断 (2026-05-16 22:28)
- **中断状況**: plan (`docs/superpowers/plans/2026-05-16-g3-autonomy-exit-smoke-plan.md`) 完成 + レビュー反映済。3 ep 実行を background task で開始 → 数分後ユーザー指示で停止。停止時点で **ep0 + ep1 は annotate 完走 (`runs/g3_smoke_20260516_2226/episode_000000__e35061106394/`, `episode_000001__293f2420a2e4/`)**、ep2 は未着手。`index.json.lock` が stale で残存 (mimicanno プロセスは全停止確認済)。再開時は ep2 だけ追走するか、3 ep やり直すかを GPU 空き状況見て判断。
- 目的: CLAUDE.md autonomy 窓の抜け条件「実データラベリング妥当性確認」
- **note**: G1 の VRAM/teardown 検証点をここに織り込めば G1 を吸収できる可能性あり。判断は G1 着手時に。
- [ ] SO101 から 3〜5 ep を選び Gemma 4B planner + SAM3 + Phase 4 smoother v5 + 永続化を通しで実行
- [ ] 妥当性 rubric (全部満たすこと):
  - [ ] 各 ep で `unknown` phase が **< 20%**
  - [ ] phase 遷移が ep 内で**単調** (大きな往復が無い、または task 構造上説明可能)
  - [ ] SAM3 mask が overhead cam で各 frame に **1 個以上** 存在
- [ ] `_vlm_dumps/*.jsonl` が SFT 用に書き出されていること ([[project_gemma_ft_pipeline]])
- [ ] 「shipped したもの・怪しかったもの・残課題」を書面でハンドオフ

### G4. gem4 新ロボット 1 ep 通し  ⭐ **本セッションで着手予定 → GPU 占有のため未着手で持ち越し (2026-05-16)**
- **状態 (2026-05-16, このセッション)**: 計画は立てたが GPU が空いていなかったため**実行に入る前に中止**。コード・yaml・データ・TODO チェックボックス含め、G4 関連は**一切触っていない** (TODO のこのメモ自体を除く)。次セッションは GPU 空き確認から再開。
- ~~別 PR 待ちなので優先度低~~ → 依存無し。yaml x3 は `71c9cd1` で main 済、データ `data/GEM4_*` 揃い、`batch_annotate*.py` DATASETS にも登録済 (so101 以外の 3 dataset)。「別 PR で整理」は運用上の話で実行ブロックではない。
- 着手前に G3 (別セッション) と GPU 占有が衝突しないか確認 ([[feedback_handoff_conflict_check]])
- [x] `mimicanno/configs/robot/gem4_*.yaml` x3 (`pick_up_bottle` / `replace_the_cookie` / `open_the_jar`) ※ 既存
- [ ] SAM3 grounding cam を **overhead/external** に設定確認 ([[feedback_sam3_use_external_cam]]) — 3 yaml の mask 設定を読んで overhead 指定になっているか確認
- [ ] 3 dataset 各 1 ep を `batch_annotate_4B.py` で annotate (`BATCH_RUNS_ROOT=/tmp/g4_smoke_*`、26B は VRAM 不足で skip)
- [ ] それぞれ annotate が落ちずに通ること、SAM3 mask が 1 frame 以上検出されること
- [ ] 結果サマリを `docs/superpowers/notes/2026-05-16-g4-gem4-smoke-results.md` に残す
- **次回セッション再開手順**: (1) `nvidia-smi` で 1 GPU 以上空きを確認、(2) G3 (別セッション) との衝突有無確認、(3) 上記 yaml/mask 確認 → 4B smoke 3 並列 (空き GPU 数次第で逐次に切替)

### G5. Phase 5 E
- spec/plan 未着手なので GPU テスト以前。ここでは out of scope。

### G6. Gemma 4B planner 単体 regression
- 2026-05-15 の初回 smoke ([[project_gemma4b_planner_smoke]]) 以降、planner 単体での再現確認が無い
- [ ] `vlm_labeler.py` を直叩きで 1 ep に当て、出力語彙と JSONL スキーマが当時と同等であることを確認

### G7. Hand pipeline + HAMER 実機 smoke
- 直近 (2026-05-16, `2307219`) で 3 軸 overlay が入った。HAMER は GPU 必須。
- [ ] `scripts/run_hand_estimation.py` を SO101 1 ep に当て、fisheye 投影 (pinhole ではない、[[project_hand_pipeline_camera_model]]) で overlay が画像内に収まることを目視
- [ ] `cam_t` 時系列が HandSignalGraph で表示されること (frontend と整合)

### G8. precompute_depth / warp / fuse (UniDAC)
- `conda activate unidac` 必須、GPU 必須 (CLAUDE.md 環境注記)
- [ ] `scripts/precompute_depth.py` を SO101 1 ep に当て depth が生成されること
- [ ] warp + fuse 後の出力が pipeline (hand/SAM3) 側で読み込めること

---

### 実行順 (推奨, 2026-05-16 22:00 セッション状況反映)

- ~~G1~~ / ~~G2~~ — **別セッション作業中・本セッションでは着手不可**
- 本セッションで進められるのは下記:

1. **G3** (end-to-end sanity, rubric付き) — autonomy 窓を閉じる本命。ただし GPU 競合に注意 (G1 が別セッションで走っている可能性あり、着手前に `nvidia-smi`)
2. **G6 / G7 / G8** — pipeline 構成要素ごとの regression。G3 が通っていれば暗黙的にカバーされる部分もあるが、明示確認が必要なものは個別実施
3. **G4** (gem4) — 別 PR

