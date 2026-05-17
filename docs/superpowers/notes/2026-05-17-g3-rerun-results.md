# G3 — autonomy exit smoke 再走結果 (2026-05-17)

**前回:** `2026-05-16-g3-autonomy-exit-smoke-results.md` (GPU=2 で実施、torch/driver mismatch 復旧後の初回)
**今回:** GPU=2 で再走、`.venv` torch 2.11.0+cu130 → `cuda_available=True` (前回と同状況)
**Run root:** `runs/g3_smoke_20260517_1353/`
**Logs:** `logs/g3_smoke_20260517_1353/`
**Wall clock:** ep0=108s, ep1=97s, ep2=58s, total **263s (~4.5 min)** ← 前回 5.5 min より速い
**実行:** ep0/1/2 を直列で `scripts/batch_so101_phase4_v5.sh` (boundary=so101_zero_crossing, smoother=so101_zc_preserve)

## 結論

**再現性 PASS**。前回 (2026-05-16) と同じ rubric 結果 — pipeline mechanics は決定論的に動作、唯一のばらつきは planner 出力 (Gemma 4B の温度由来)。

| ep | R1 unknown | R2 monotonic | R3 SAM3 | 備考 |
|---|---|---|---|---|
| 0 | PASS (0%) | PASS (2 unique: approach_object×4 + place_object) | PASS (yellow tape=0.98, white bottle=0.82) | 前回と同パターン、tracks 2 件 |
| 1 | PASS (0%) | **FAIL_DEGENERATE** (`approach_object`×4) | PASS (yellow tape=0.98, white bottle=0.98) | 前回と同 (planner が 4 セグ全部 approach に丸める) |
| 2 | PASS (0%) | PASS (2 unique: approach_object×3 + idle) | **FAIL_NO_TRACKS_FILE** | 前回と同 (planner 由来の SAM3 grounding miss) |

## 前回との差分

- **Wall clock −16%**: 前回 5.5 min → 今回 4.5 min。原因不明だが GPU=2 (A100 40GB) 占有度・他プロセス無し条件は同じ。SAM3 warm cache の可能性。
- **planner 出力の言い回し微差**: 前回 ep0 は `"objects": ["yellow tape", "white and green cylindrical bottle"]` / 今回も同じ `["yellow tape", "white and green cylindrical bottle"]` (完全一致)。Gemma 4B 出力は今回 deterministic に再現。
- **autonomy exit 判定**: 前回時点と同じく (2) 実データ妥当性 PASS + (3) 書面ハンドオフ PASS。窓は既に 2026-05-16 で CLOSED 済 ([[project_phase5_d_shipped]] TODO.md L3)。今回は **検証目的 (env 復旧確認 + 再現性確認)** で再走。

## env 状況

- **torch 2.11.0+cu130 で `cuda_available=True`** — 前回と同。.venv は G1/G4 と共有なので独断書き換えはしてない (前回判断踏襲)。
- nvidia driver 12.6 + cu130 wheel の組合せ依然動作 (mechanism は未解明)。

## 残課題 (本ノート発生分なし、引き継ぎのみ)

- ep1 R2_DEGENERATE / ep2 R3_NO_TRACKS_FILE は planner-side で SFT loop の責務 ([[project_gemma_ft_pipeline]])。pipeline-side fix の予定はない。
- 関連 G7 full-ep 再走 (HAMER cam_t metric anchoring 検証) は依然優先度低で TODO 残置。
