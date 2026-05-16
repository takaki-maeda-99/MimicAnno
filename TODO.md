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

### G1. batch_annotate 実機 smoke (最優先)
- 対象スクリプト: `scripts/batch_annotate.py` および `scripts/batch_annotate_4B.py` (両方 `BATCH_RUNS_ROOT` 対応)
- 対象コミット (ローカル main、未 push):
  - `3b6899e feat(batch_annotate): share SAM3 runtime + BATCH_RUNS_ROOT override`
  - `0e45447 feat(pipeline): add preloaded_sam3_runtime to AnnotateRequest`
  - `79bdbcd refactor(sam3_runtime): split close() into _close_all_sessions() + final teardown`
- [ ] SO101 で 2 ep 以上を **同一 SAM3 runtime 共有**で連続 annotate (両 variant)
- [ ] VRAM delta が ep 境界で **< 200 MB** に収まること (`nvidia-smi --query-gpu=memory.used` を ep 前後で記録)
- [ ] `_close_all_sessions()` 呼び出しを **ログで確認** (`pipeline.py:905` を経由するはず、ep 数 = call 数 になること)
- [ ] 最終 ep 後の `close()` で全 session が破棄されること
- [ ] `BATCH_RUNS_ROOT=/tmp/foo` 上書きで run がそこに落ちること
- [ ] 着手前に別セッション handoff note と branch 状態を確認

### G2. Phase 5 D — SO101 v5 手動 smoke (T13)
- **状態の補足**: D r1 実装は `feat/phase5-d-eval-harness` ブランチに ship 済 (`4fdd553`, `caff5cf`, `6b65ae6`) だが **main 未 merge**。`mimicanno eval` CLI も main には未だ存在しない。
- [ ] 前提: `feat/phase5-d-eval-harness` を main に merge (S-D 実装と合流) → `mimicanno eval` が CLI に現れることを `mimicanno --help` で確認
- [ ] 新規 run を annotate → `mimicanno serve` 起動 → frontend で relabel/boundary/reviewed/labels 4 種を編集
- [ ] `mimicanno eval <run>` で history が読まれ metrics + render が出ること
- [ ] phase `<select>` focusin/change hook の計測値が EditEvent に乗ること (history JSON を直接 grep して `dwell_ms` などのフィールド存在確認)
- annotate 部分のみ GPU、eval/edit 自体は CPU

### G3. autonomy exit 用 end-to-end 実データ sanity check
- 目的: CLAUDE.md autonomy 窓の抜け条件「実データラベリング妥当性確認」
- **note**: G1 の VRAM/teardown 検証点をここに織り込めば G1 を吸収できる可能性あり。判断は G1 着手時に。
- [ ] SO101 から 3〜5 ep を選び Gemma 4B planner + SAM3 + Phase 4 smoother v5 + 永続化を通しで実行
- [ ] 妥当性 rubric (全部満たすこと):
  - [ ] 各 ep で `unknown` phase が **< 20%**
  - [ ] phase 遷移が ep 内で**単調** (大きな往復が無い、または task 構造上説明可能)
  - [ ] SAM3 mask が overhead cam で各 frame に **1 個以上** 存在
- [ ] `_vlm_dumps/*.jsonl` が SFT 用に書き出されていること ([[project_gemma_ft_pipeline]])
- [ ] 「shipped したもの・怪しかったもの・残課題」を書面でハンドオフ

### G4. gem4 新ロボット 1 ep 通し
- 別 PR 待ちなので優先度低
- [ ] `mimicanno/configs/robot/gem4_*.yaml` x3 を書く
- [ ] SAM3 grounding cam を **overhead/external** に設定 ([[feedback_sam3_use_external_cam]])
- [ ] 1 ep でも annotate が落ちずに通ること

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

### 実行順 (推奨, review 後)

1. **G1** (batch_annotate) — 未 push コミット検証。G3 に吸収できる場合は G3 内で実施
2. **G3** (end-to-end sanity, rubric付き) — autonomy 窓を閉じる本命
3. **G2** (S-D smoke) — その前に `feat/phase5-d-eval-harness` を main に merge
4. **G6 / G7 / G8** — pipeline 構成要素ごとの regression。G3 が通っていれば暗黙的にカバーされる部分もあるが、明示確認が必要なものは個別実施
5. **G4** (gem4) — 別 PR

