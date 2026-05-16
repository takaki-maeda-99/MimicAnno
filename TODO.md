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
| **S-D** | **Phase 5 D — EditEvent history + mimicanno eval CLI (minimal scope)** | **`3d8bb34` (main, PR D-merge)** |
| **fix-boundary-route** | `patch_boundary_route` Depends(get_effective_root) 欠落修正 + regression test | **`679fbf9` (main, PR #10)** |

---

## 残タスク

### 1. S-D — Evaluation harness — `feat/phase5-d-eval-harness` ✅ DONE

- [x] spec: `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` (rev1)
- [x] plan: `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` (rev1)
- [x] **T1〜T3**: `EditEvent` dataclass + `AnnotationResult.history` + annotation schema 0.3.0
- [x] **T4〜T7**: `event_builder.py` + 4 repo/route extensions + server tests
- [x] **T8〜T10**: `mimicanno/eval/` package (`metrics.py` + `render.py` + CLI)
- [x] **T11**: frontend timing hook (all 4 edit clients + SegmentTable onEditFocus + RunViewer editStartRef)
- [x] **T12**: mypy --strict + 全 regression (10 new tests + 210 existing, all pass)
- [x] **T13**: 手動 smoke (SO101 ep0 copy — PATCH reviewed 2500ms → history correct, eval CLI OK)
- [x] **T14〜T15**: docs (`2026-05-16-phase5-d-results.md`) + memory + TODO
- [ ] **main にマージ** (ユーザー判断待ち)

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
S-D main マージ → Phase 5 E (MimicRec integration)
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

### G2. Phase 5 D — SO101 v5 手動 smoke (T13) ⚠️ 別セッションの worktree が壊された — 要復旧
- **🚨 2026-05-16 23:?? ハンドオフ警告 (本セッションからの誤操作)**: ユーザー指示により D ブランチ merge + push 後、`feat/phase5-d-eval-harness` の **remote 削除に同意 → local 片付け中に `/misc/dl00/gayagaya/MimicAnno-phase5d` worktree を `rm -rf` してしまった**。`mimicanno serve` (PID 1460990) と `vite` (PID 1460389) はまだ動いているが、`.venv` / `node_modules` の中身は inode のみ生きている状態。**新しいファイルアクセス (server reload / import / hot reload) で fail する可能性**。
  - **何が起きたか**: TODO G2 の「触らない」警告を見落とし、merge 後の cleanup として worktree 削除を試行。NFS busy file で削除は不完全、`frontend/` ディレクトリ残骸あり。git からの worktree 認識は消えた (`git worktree list` に出ない、local branch も削除済)。
  - **D の中身は安全**: `feat/phase5-d-eval-harness` の全コミットは main の merge commit `3d8bb34` に統合済・origin push 済 (commit `3bdcb12..3d8bb34`)。remote D ブランチも削除済。**実装の loss はゼロ**。
  - **影響範囲**: 別セッションが phase5d worktree 内で稼働させていた server/vite + 未コミット変更 (frontend 3 ファイル)。未コミット変更は失われた可能性 (git stash 等で退避していなければ復旧不可)。
  - **復旧手順 (別セッション側で)**: (1) PID 1460990/1460389 を `kill`、(2) `rm -rf /misc/dl00/gayagaya/MimicAnno-phase5d` で残骸除去、(3) 必要なら `git worktree add ../MimicAnno-phase5d-new main` で新 worktree、(4) `uv sync` + `cd frontend && npm install` で env 再構築。
  - **smoke 自体は main で実行可能**: D は merge 済なので `/misc/dl00/gayagaya/MimicAnno` (main) で `mimicanno eval` も `mimicanno serve` も使える。新 worktree 不要なら main でやり直しても OK。
- **(古い状態) 2026-05-16 22:00 確認**: `/misc/dl00/gayagaya/MimicAnno-phase5d` worktree で別セッションが smoke 実行中。`mimicanno serve` (PID 1460990) + `vite` (PID 1460389) 稼働中、`/tmp/mimicanno-d-smoke.log` / `/tmp/vite-d-smoke.log` 出力中。frontend 3 ファイルに未コミット変更あり。
- **状態の補足**: D r1 実装は main に merge 済 (`3d8bb34`, 2026-05-16 23:?? 本セッション)。`mimicanno eval` CLI は main で利用可能。
- [ ] 前提: `feat/phase5-d-eval-harness` を main に merge (S-D 実装と合流) → `mimicanno eval` が CLI に現れることを `mimicanno --help` で確認
- [ ] 新規 run を annotate → `mimicanno serve` 起動 → frontend で relabel/boundary/reviewed/labels 4 種を編集
- [ ] `mimicanno eval <run>` で history が読まれ metrics + render が出ること
- [ ] phase `<select>` focusin/change hook の計測値が EditEvent に乗ること (history JSON を直接 grep して `dwell_ms` などのフィールド存在確認)
- annotate 部分のみ GPU、eval/edit 自体は CPU

### G3. autonomy exit 用 end-to-end 実データ sanity check ⏳ **本セッション (2026-05-16 後半) 再着手中**
- **🔧 状態 (2026-05-16 後半, 本セッション再開)**: 前セッション (22:45) の env blocker (`.venv` torch 2.11.0+cu130 vs driver 12.6) の解消を進めるため再着手。着手前に `nvidia-smi` で GPU 占有確認 + G1/G4 別セッションの稼働状況と env 共有方針を確認する。**他セッション (G1 batch_annotate / G4 gem4 smoke) と `.venv` を共有しているため、torch 差し替えは事前に handoff note + branch 状態を読んでから判断する** ([[feedback_handoff_conflict_check]])。
- **過去状態 (2026-05-16 22:45)**: GPU=6 (48GB free) で 3 ep やり直しを試行 → 全 ep exit 3 FAIL。原因: `.venv` の torch が `2.11.0+cu130` に更新されており、システムドライバ 560.35.05 / CUDA 12.6 と非互換 (`torch.cuda.is_available()=False`、"NVIDIA driver too old, found 12060"). **G4 (別セッション) が報告している env 問題と同根** (TODO G4 既知 env 問題② を参照)。`runs/g3_smoke_20260516_2238/` は空、ログ `/misc/dl00/gayagaya/MimicAnno/logs/g3_smoke_20260516_2238/episode_00000{0,1,2}_gpu6.log`。.venv は G1/G4 と共有のため独断で書き換えず、他セッションの env 調査結果待ち、だった。
- **過去の中断 (2026-05-16 22:28, 持ち越し参考)**: plan (`docs/superpowers/plans/2026-05-16-g3-autonomy-exit-smoke-plan.md`) 完成 + レビュー反映済。3 ep を background で開始 → 数分後ユーザー指示で停止。停止時点で ep0 + ep1 は annotate 完走 (`runs/g3_smoke_20260516_2226/episode_000000__e35061106394/`, `episode_000001__293f2420a2e4/`)、ep2 未着手。stale `index.json.lock` あり。
- 目的: CLAUDE.md autonomy 窓の抜け条件「実データラベリング妥当性確認」
- **note**: G1 の VRAM/teardown 検証点をここに織り込めば G1 を吸収できる可能性あり。判断は G1 着手時に。
- [ ] SO101 から 3〜5 ep を選び Gemma 4B planner + SAM3 + Phase 4 smoother v5 + 永続化を通しで実行
- [ ] 妥当性 rubric (全部満たすこと):
  - [ ] 各 ep で `unknown` phase が **< 20%**
  - [ ] phase 遷移が ep 内で**単調** (大きな往復が無い、または task 構造上説明可能)
  - [ ] SAM3 mask が overhead cam で各 frame に **1 個以上** 存在
- [ ] `_vlm_dumps/*.jsonl` が SFT 用に書き出されていること ([[project_gemma_ft_pipeline]])
- [ ] 「shipped したもの・怪しかったもの・残課題」を書面でハンドオフ

### G4. gem4 新ロボット 1 ep 通し  ⚠️ **本セッション作業中 (2026-05-16 後半・GPU7)・他セッションからは触らない**
- **状態 (2026-05-16, このセッション 後半)**: GPU7 (46GB free) を確保し `batch_annotate_4B.py --dataset gem4_pick_up_bottle --gpu 7 --start 0 --end 0` を `.venv/bin/python` 経由で実行中。BATCH_RUNS_ROOT=/tmp/g4_smoke_pick_up_bottle、ログ `/tmp/g4_smoke_logs/pick_up_bottle.log`。
- **既知の env 問題 (調査中)**: ① hamer python (3.10) は `StrEnum` 不可 → `.venv` (3.11) 必須。② `.venv` の torch が「NVIDIA driver too old (found 12060)」で `cuda_init` 失敗 → driver vs torch wheel 不整合。解消手段を検討中 (CUDA wheel 差し替え or 別 env)。
- **過去メモ (持ち越し参考)**: 計画は立てたが GPU が空いていなかったため実行に入る前に中止していた。yaml/データ/チェックボックスは未変更。
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

