# G1 — 26B variant SO101 smoke 結果 (2026-05-17)

**前回:** `2026-05-17-g1-batch-annotate-smoke-results.md` (4B PASS, 26B は VRAM 不足で skip 確定とした)
**今回:** A100 80GB (GPU=1) で 26B 再挑戦 → **PASS (mechanics)**、ただし planner-vs-4B 比較は config gap で incomplete
**Run root:** `/tmp/g1_smoke_26b/`
**Logs:** `/tmp/g1_smoke_26b/logs/`
**Wall clock:** ep0=305s (load 含), ep1=124s, total **429s (~7 min)** for 2 ep
**実行:** `GPU=1 START=0 END=1 RUNS_ROOT=/tmp/g1_smoke_26b LOGS_DIR=... VLM_DUMP_ROOT=... bash scripts/run_26B_so101.sh`

## チェックリスト判定

| 検証項目 | 結果 | 根拠 |
|---|---|---|
| 26B モデル load (Unsloth QLoRA + 4B base + adapter) | ✅ | `Loading weights: 100% 1013/1013 in 12s` (line 348)。adapter `models/gem4_26B_adapter` |
| A100 80GB に収まる | ✅ | **VRAM 52 GiB used / 55 GiB reserved** (peak max_over_time)。A6000 48GB では fit せず、80GB GPU 必須を実機確認 |
| SO101 で 2 ep 連続 annotate | ✅ | `episode_000000: OK`, `episode_000001: OK` 両方 exit=0 |
| SAM3 grounding 動作 | ✅ | ep0 `yellow tape` track mean=0.98 / ep1 `yellow roll of tape` mean=0.98。propagate_in_video 151 frames 全部走破 |
| planner (Gemma 4B + 26B QLoRA adapter) 動作 | ✅ | `_vlm_dumps/episode_*/_planner/call_000/response.txt` に JSON 出力あり |
| **planner 出力が segments に反映されるか** | ⚠ **不明** | annotation.json `segments` が **1 件のみ phase=idle** → boundary 検出 0 が直接原因 (下記) |

## 4B vs 26B の planner 出力比較 (ep0)

| 項目 | 4B (G3) | 26B (今回) | 評価 |
|---|---|---|---|
| `objects` | `["yellow tape", "white and green cylindrical bottle"]` | `["yellow tape"]` | 26B はテープのみに絞る (bottle は targets へ移動) |
| `targets` | `[]` | `["white bottle"]` | **26B が意味的に正しい** (bottle は配置先) |
| `tools` | `["robotic claw"]` | `["black robotic gripper"]` | 26B は色+具体的な道具名で記述精度↑ |
| SAM3 grounding 結果 | yellow tape 0.98, bottle 0.82 (2 tracks) | yellow tape 0.98 (1 track) | 26B は targets を grounding 対象から外したので tracks 数は減るが nuisance なし |

→ 26B planner は **slot 振り分け (objects vs targets) と語彙具体性で 4B より良い**。SO101 ep0 1 サンプルの所見だが gem4 chain の結果と合わせて再評価予定。

## ⚠ Root cause: segments=1 idle

26B run の annotation は ep0/ep1 とも `segments=[{phase: idle, verb: null, object: null, target: null}]` で degenerate。

原因は **planner 品質ではなく `scripts/run_26B_so101.sh` の config gap**:

```bash
# 26B 実行コマンド (run_26B_so101.sh L40-48):
mimicanno annotate --video ... --parquet ... --task ... \
    --robot generic --robot-config ... \
    --target-phase 4 --offline \
    --vlm-model "$VLM_MODEL" --vlm-device cuda \
    --sam3-checkpoint "$SAM3" --runs-root "$RUNS_ROOT" --force
    # ↑ --boundary-config / --smoother-config が未指定
```

`scripts/batch_so101_phase4_v5.sh` (G3 / 4B G1 で使う) は SO101 専用に:
- `--boundary-config mimicanno/configs/boundary/so101_zero_crossing.yaml`
- `--smoother-config mimicanno/configs/smoother/so101_zc_preserve.yaml`

を渡している。これらが無いと default boundary detector が走り、SO101 の細かい signal では **0 candidate** に丸まる → segment 1 件 idle に落ちる。

**裏付け**: `boundaries.json` の `candidates: []` を確認 (26B ep0)。signals.json には channels=2 が記録されているので signal extraction 自体は動作。

VLM segment 推論 (`s_001/attempt_1/response.txt`) も `{"phase": "idle", "verb": null, ..., "evidence": "Robot is moving into position, but no manipulation of the tape has started."}` を返しており、これは **「1 セグ全体を見て idle」と判断した妥当な応答** (26B planner はちゃんと動いた)。

## 推奨フォローアップ

1. **`scripts/run_26B_so101.sh` に SO101 boundary/smoother config を追加** — 1 行追加で済む、別 PR で対応可:
   ```bash
   --boundary-config "$REPO/mimicanno/configs/boundary/so101_zero_crossing.yaml" \
   --smoother-config "$REPO/mimicanno/configs/smoother/so101_zc_preserve.yaml" \
   ```
   その後再走で 4B 4-5 セグ vs 26B segments を直接比較可能。
2. gem4 26B chain (本セッション継続中、PID 82185 起源) の結果が出たら、`scripts/batch_annotate.py` 側が boundary-config を渡しているか確認 (渡しているなら segments 比較可能なはず)。
3. 26B SO101 ep0/ep1 の planner response は `_vlm_dumps/_planner/` に保存済 — SFT 訓練データとして 4B 出力と diff を取れる ([[project_gemma_ft_pipeline]])。

## env 状況

- python: `/home/gayagaya/anaconda3/envs/unsloth_env/bin/python`
- torch: **2.10.0+cu128** (G3/4B 用の .venv は 2.11.0+cu130 と別系統)
- Unsloth 2026.4.8 + Gemma4 patch + flash_attention_2 はサポート外で sdpa にフォールバック (warning のみ、無害)
- **VRAM peak 52 GiB** → A100 80GB では余裕、A100 40GB / A6000 48GB では NG (前回 skip 確定の根拠は妥当)

## 結論

- **G1 26B SO101 PASS (実機 mechanics)** — 80GB GPU で 26B variant が end-to-end で動作することを実機確認。前回 TODO の「26B は VRAM 不足で別ホスト」は「80GB GPU が必要、本ホスト GPU 1 で OK」に更新。
- 4B vs 26B の **annotation richness 比較は config gap で incomplete** — `run_26B_so101.sh` 修正後に再走で fair compare 可能。
- planner 出力 (`tracking_plan` レベル) のみで見ると **26B は slot 振り分け+語彙具体性で 4B より良い** 兆候あり (1 サンプル所見、gem4 chain で再評価)。

---

## 2026-05-17 追記: config gap fix (Python side) shipped

**Branch**: `fix/26b-config-gap` (worktree `.claude/worktrees/26b-config-gap/`)
**Commit**: `b17dd21 fix(batch_annotate): load per-dataset boundary/smoother YAML via existing CLI loaders`

### 変更内容

`scripts/batch_annotate.py` の `BoundaryConfig.with_defaults()` / `SmootherConfig()` を per-dataset YAML 読み込みに切替。SO101 entry に 2 YAML 指定 (sibling shell `run_26B_so101.sh` 同等)。gem4 は None で default fallback (現走行影響なし)。

5 unit tests (`tests/test_batch_annotate_yaml_loading.py`):
- SO101 entry が両 YAML を declare
- gem4 entries は None 維持
- `load_boundary_config_yaml` が `zero_crossing.enabled=True` を返す (default は False)
- `load_smoother_config_yaml` が `gripper_zero_crossing` を preserve_sources に持つ (default は持たない)
- `main()` の config 構築 snippet 等価 path で同等値が AnnotationConfig に届く

TDD red 確認: fix なしで 4/5 fail、ありで 5/5 pass。

### End-to-end 26B SO101 smoke は GPU 制約で deferred

本セッション時点で全 4 GPU が RTX A6000 49 GiB。26B は ~52 GiB 必要 → どの GPU でも OOM。検証 run (`/tmp/g1_smoke_26b_v2/`, GPU=3) は load 中で kill (exit 143)。

**次に検証する条件**:
- 80GB GPU (A100 等) 確保時、または
- gem4 26B chain 完了後にいずれかの A6000 が空き、かつ 26B が他経路 (例: 4B でも段組検証として) で代替可能なら 4B vs 4B+YAML 比較として実施

**Logical 検証は完了**: 4B 経路 (`scripts/batch_so101_phase4_v5.sh`) が同じ `load_*_yaml` を経由して proven に segments を生成しているため、YAML が AnnotationConfig まで届けば downstream pipeline は identical に振る舞う (本テストで届くこと verify 済)。

### gem4 への波及

gem4 boundary/smoother YAML はまだ書かれていないため、gem4 entries は None のまま (default fallback)。gem4 出力が degenerate に見える場合は別途 gem4-specific YAML を author する必要がある (将来 task)。

---

## 2026-05-17 追記: Re-run (GPU 0, config fix 効果検証) ✅

**Branch**: main (commit `7625a05` の `scripts/run_26B_so101.sh` 修正で十分、batch_annotate.py 側 fix は不要)
**Run root**: `/tmp/g1_smoke_26b_v2/`
**GPU**: 0 (A100 80GB)、別 GPU 上の gem4 chain と完全独立
**Wall clock**: ep0=286s (load 込み), ep1=172s, total **458s (~7.6 min)** for 2 ep
**VRAM peak**: ep0=55,177 MiB / ep1=55,056 MiB (90% threshold 73,728 まで余裕 18 GiB、watchdog kill 発火せず)

### 結果サマリ

| 指標 | v1 (config gap) | v2 (config fix) | 4B G3 比較 |
|---|---|---|---|
| ep0 segments | **1** (idle) | **5** | 4B 5 と一致 ✅ |
| ep0 boundaries | 0 | 4 | 4B 4 と一致 ✅ |
| ep1 segments | **1** (idle) | **4** | 4B 4 と一致 ✅ |
| ep1 boundaries | 0 | 3 | 4B 3 と一致 ✅ |

**config fix で boundary detector が正しく working、segments 数は 4B と完全一致** (boundary は VLM 非依存、signals 由来なので)。

### 4B vs 26B label 品質比較 (ep0)

| frame range | 4B phase | 4B verb | 26B v2 phase | 26B v2 verb |
|---|---|---|---|---|
| [0-19] | approach_object | None | **idle** | None |
| [20-49] | approach_object | None | approach_object | **approach** |
| [50-87] | approach_object | None | **grasp_object** | **grasp** |
| [88-98] | approach_object | None | **align_to_target** | **align** |
| [99-150] | place_object | place | **release_object** | **release** |

→ 26B は **(a) verb 全付き、(b) 物理的に正しい phase 順序 (idle→approach→grasp→align→release)、(c) "release_object" vs "place_object" でより具体的**。4B は 4 セグ全て `approach_object` で潰す傾向 (G3 ep1 R2_DEGENERATE と同じ問題)。

### ep1 (4B も degenerate なケース)

| frame range | 4B phase | 26B v2 phase | 26B v2 verb |
|---|---|---|---|
| [0-29] | approach_object | align_to_target | align |
| [30-55] | approach_object | align_to_target | align |
| [56-90] | approach_object | align_to_target | align |
| [91-150] | approach_object | release_object | release |

→ 4B は完全 degenerate (4 セグ全 `approach_object` verb=None)。26B も 3 セグ同一 (`align`) だが、最後 `release` で動作変化を検出 + verb 全付き。**26B 6 セグ中 26B のほうが degenerate 度低い**。

### 結論

- `scripts/run_26B_so101.sh` の boundary/smoother config 追加 (commit `7625a05`) は **期待通り効いた** — segment 数は 4B と完全一致、label 品質は明確に向上。
- v1 で観察された 「segments=1 idle」は config gap が単独原因で、26B planner 自体は健全 (本 v2 で実証)。
- 別セッション (b17dd21) の `batch_annotate.py` 側 YAML loader fix は **SO101 検証には不要だった** (shell script fix で十分)。ただし将来 gem4 用 boundary/smoother YAML を書いたとき、batch_annotate.py 経由でも届くようになる前置き fix として価値あり。
- TODO の「`run_26B_so101.sh` config gap」中優先タスクは本検証で **完了済へ移動可能**。
