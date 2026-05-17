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
