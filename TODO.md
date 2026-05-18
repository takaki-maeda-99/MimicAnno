# TODO (2026-05-17)

**Autonomy window: CLOSED 2026-05-16**。Phase 5 D + SO101 v5 real-data smoke green。次窓を開ける場合はユーザー判断。

最新の shipment 履歴と詳細サマリは auto-memory (`MEMORY.md`) と `git log` 参照。本 TODO は **未完タスクのみ** を保持する。

---

## 残タスク

### One-shot env setup + start_ui hardening ✅ **完了 (2026-05-17 PM)** — feat/setup-serve-scripts → main (FF, 14 commits)

- `scripts/setup_envs.sh` を idempotent orchestrator に書き直し: `submodules → core → unidac → frontend → weights`。flags: `--all` (default), `--core/--unidac/--frontend/--weights`, `--skip-weights`。
- 新規 `scripts/lib/{log,preflight}.sh` + `scripts/setup/*.sh` で責務分離。`STEP_OK/FAIL/USER` exit code, `dry_run_short_circuit` helper, `SETUP_DRY_RUN=1` で CI smoke。
- gated HF DL を `hf download` (← `huggingface-cli` は廃止) で SAM3 snapshot + Gemma 4 (`google/gemma-4-E2B-it`) を取得。HF auth は `HF_TOKEN` env or `hf auth login`。
- `scripts/start_ui.sh`: deps check (`.venv/bin/mimicanno` + `frontend/node_modules/.modules.yaml`) + `lsof` port probe + `kill -- -$$` で vite 孫プロセス孤児を防止 + `pnpm run dev --port` (pnpm v11 で `--` separator は禁。詳細は memory `feedback-pnpm-v11-arg-separator`)。
- `scripts/setup/submodules.sh`: SSH→HTTPS rewrite を `git -c url.insteadOf=...` でコマンド単位スコープ化 (global config leak 防止)。
- README.md / README.ja.md の Install セクションを `bash scripts/setup_envs.sh` 一発に書き換え。
- smoke 完走: `--all` 2.5s / `SETUP_DRY_RUN=1 --all` 短絡 / `--core --frontend` 選択 / start_ui の `/healthz` + `/api/runs/index.json` 200 + Ctrl-C 孤児なし。
- 既知 minor (Won't fix): summary 表で SKIP/PASS 区別なし (全 step 改修要のため見送り)。
- 関連 memory: `project-setup-envs-shipped`, `reference-hf-cli-deprecated`, `feedback-pnpm-v11-arg-separator`。

### SAM3 grounding retry smoke (T13) ✅ **完了 (2026-05-17 PM)** — cluster 仮説 4/6 hit (67%)

- **結果ノート**: `docs/superpowers/notes/2026-05-17-sam3-grounding-retry-smoke.md`
- **実行**: GPU 1 で 6 ep × ~1.3 min ≈ 8 min、`runs/_smoke_grounding_retry/`
- **mechanism PASS**: ep2 で 4 回目 (frame 112, frac=0.75) で救済成功 (`adopted=True, n_object_grounded=1`)、ep0 regression なし (frame 0 即成功)
- **仮説外れ**: ep9/ep26 は cluster A (救済可能) と分類してたが 4 frame 全部 `n_object_grounded=0` → 実は cluster B (object 自体 SAM3 grounding 困難)
- **follow-up (任意)**: m5 spec で `grounding_retry_fractions=[0.5, 0.25, 0.75]` 拡張 (0.1, 0.9 追加など)、`n_total_grounded > 0` ベースの soft adoption ロジック
- **GPU 要件残存**: 別サーバー実行は不要になった (本ホスト A100 80GB で 8 min smoke 完走、4B+SAM3 で 12-15 GB 確認)

- 実装 T1–T12 は PR #26 (`413bfd7`) で main マージ済 (unit 830 + integration 59 pass)
- 残り: 別サーバーで GPU 確保次第、so101_4B の degraded 5 ep (`ep2/6/9/10/26`) + regression 用 ep0 を再生成、`adopted_frame_index`/attempts を記録
- 実行コマンド例:
  ```bash
  CUDA_VISIBLE_DEVICES=<idx> uv run --extra sam3 mimicanno annotate \
    --episode ~/MimicRec/datasets/SO101/data/chunk-000/episode_000002.parquet \
    --task "Put the tape into the bottle" \
    --vlm-model google/gemma-3-4b-it \
    --sam3-checkpoint <memory project_so101_dataset 参照> \
    --runs-root runs/_smoke_grounding_retry/
  ```
- 結果次第で `grounding_retry_fractions` のチューニング判断
- 詳細仕様: `docs/superpowers/specs/2026-05-17-sam3-grounding-retry-design.md` (local, gitignored)

**Final review nice-to-haves (smoke 後に検討):**
- I1: `_count_missing_mask_frames` の call site (`pipeline.py:1135`) が hardcoded `0`、`segment_keyframes` 配線で実数化
- M3: frame 0 success path の `propagation_direction="forward", anchor=0` assert integration test
- I3: `mimicanno/schema.py` の `_UNSET: Any` を `NewType` 化で型安全性向上
- M1: `adopted_frame_idx` (Python) vs `adopted_frame_index` (manifest) 命名統一
- M4: `fixtures.py:178` の `propagation_direction: str` → `Literal["forward","both"]`
- M5: `_extract_frame_at:293` の `except Exception` を I/O 例外限定に
- M6: `test_retry_total_failure_returns_none` のハードコード `[0,75,37,112]` を parametrize

### Phase 5 E — MimicRec 配置待ち（低優先）

(A) `mimicanno export-undo` CLI、(B) integration contract 凍結 docs、(C) `mimicanno.client` read-only Python client。本リポ完結部分は autonomy 不要範囲で着手可。

### `_vlm_dumps` → SFT loader 対応（SFT loop 着手時）

- SFT loader 場所: **別リポ** `/home/gayagaya/QLoRA/gemma4_vla/data/phase_label_dataset.py`
- 現状: 両 config (`qlora_{e4b,26B}_phase_label.yaml`) は Gemini 3.1 Pro Preview 出力 (`_gemini_results_*`) を読んでおり、Gemma `_vlm_dumps` 未対応 → schema 変化の **実害ゼロ**
- ギャップ: loader は `episode_*__seg*/{prompt,response}.txt + keyframe_*.png` 期待、`_vlm_dumps` は `episode_*/_planner/call_*/` の 2 階層 + keyframe 無し、planner/labeler 混在
- 選択肢:
  - (a) Gemini results 使用継続
  - (b) `scripts/aggregate_gemma_pairs.py` を拡張して loader 互換 dir 生成
  - (c) `phase_label_dataset.py` 側を新 schema 対応 (別リポ作業)
- 関連 memory: `project_gemma_ft_pipeline`, `reference_sft_loader_location`

### gem4 boundary/smoother YAML 作成 + 26B chain 再走（低優先）

- 発見 (2026-05-17): `runs/gem4_*_26B/` (3 datasets × ~210 ep) 全て `segments=1 phase=unknown candidates=0` の degenerate (default boundary/smoother が gem4 信号に反応せず、SO101 と同じ root cause)
- 中断状態: `runs/gem4_pick_up_bottle_26B/` ep0-303 / `runs/gem4_open_the_jar_26B/` ep0-57 / `runs/gem4_replace_the_cookie_26B/` 起動直後停止
- `_vlm_dumps/` は出ているので SFT データとしては valuable
- Steps:
  1. gem4 (Franka Research 3) の gripper/velocity 信号特性を 1 ep プロット (`signals.json` から閾値レンジ決め)
  2. `mimicanno/configs/boundary/gem4_*.yaml` + `mimicanno/configs/smoother/gem4_*.yaml` 作成 (SO101 yaml を template)
  3. `scripts/batch_annotate.py` の DATASETS gem4 entries に config 設定
  4. 80GB GPU 確保時に 1 ep × 3 dataset smoke (`segments ≥ 2` + boundaries 非空)
  5. 全 chain 再走判断 (cost: 26B × 700 ep × ~7min ≈ 80h GPU time)

### gem4 設定整理（低優先）

`mimicanno/configs/robot/gem4_*.yaml` × 3 の clean-up（docs/別 PR）。

### SAM3 grounding retry 改善 (T13 follow-up、低優先)

**背景**: T13 smoke (`docs/superpowers/notes/2026-05-17-sam3-grounding-retry-smoke.md`) で cluster 仮説 4/6 hit。仮説外れの ep9/ep26 は 4 frame (0/75/37/112) 全部 `n_object_grounded=0`。retry mechanism は ep2 で完璧に動作確認済 (frame 112, frac=0.75 で救済) なので、改善の余地は frame 選択 + adoption ロジック側。

**改善案 (m5 spec で扱う)**:
1. **`grounding_retry_fractions` 拡張** — 現在 `[0.5, 0.25, 0.75]`。`[0.1, 0.9]` 追加で episode 端 (object が一瞬だけ映る ep) もカバー
2. **`n_total_grounded > 0` ベースの soft adoption** — ep2 attempts 1-3 で `n_object_grounded=0` だが `n_total_grounded=1` (nuisance あり)。soft 判定 (`best_iou > thr` 等) で retry 回数を減らせる可能性

**着手条件**: m5 spec 起こす時、or T13 smoke の degrade rate が許容できなくなった時 (現状 6/6 中 3 ep degrade = 50% で許容範囲)。

---

## 後始末（残り）

- `/misc/dl00/gayagaya/MimicAnno-phase5d/frontend/node_modules/` — git 認識外、稼働 server 無いので無害だがいつでも `rm -rf` 可
- `mimicanno serve` (PID 1063745) — 停止済（再起動の有無は不定、`ps` 要確認）

---

## 推奨次ステップ

1. SAM3 grounding retry smoke (T13) — 別サーバー GPU 待ち
2. gem4 boundary/smoother YAML 作成（gem4 26B chain degenerate 解消、低優先）
3. Phase 5 E は MimicRec 配置待ち
4. Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec から
