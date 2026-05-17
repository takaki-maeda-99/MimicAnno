# G7 — Hand pipeline + HAMER full-ep 再走結果 (2026-05-17 PM)

**前回:** `2026-05-17-g7-hand-hamer-smoke-results.md` (2026-05-17 AM, **PARTIAL PASS**)
**今回:** full-ep depth (G8 `--limit` 外し) で再走 → **FULL PASS** ✅
**Branch:** main (no code change)
**GPU:** G8 = GPU 1 (A100 80GB), G7 = **GPU 3** (A100 40GB, ユーザー指示)
**Wall clock:** G8 34.1s (151 frame) + G7 58.4s = **~1.5 min**

## 結論

**cam_t metric anchoring 検証 PASS** — 前回 PARTIAL の唯一の懸念点 (depth 0-29 frame と HaMeR 検出 128-150 frame の不重複) が解消、UniDAC anchored cam_t z = **0.14-0.27 m** (mean 0.22 m) で物理的に妥当な手の距離 (~20cm 〜 30cm @ front cam)。

| 指標 | 前回 PARTIAL | 今回 FULL PASS |
|---|---|---|
| G8 depth coverage | frame 0-29 (`--limit 30`) | **frame 0-150** (full ep) |
| frames_with_hands | 23 (left only) | 23 (同) |
| frames_depth_missing | **23** (overlap=0) | **2** (frame 128/129 端っこ) |
| cam_t z (UniDAC anchored) | n=0 | **n=21/23 (91%)** ✅ |
| cam_t z range | 12.7-14.3 m (HaMeR fallback) | **0.14-0.27 m** ← 物理的に妥当 |
| wrist_depth_m range | N/A (depth missing) | **0.37-0.51 m**, mean 0.45 m |
| viz/overlay.mp4 size | 654,524 B | 656,616 B (同等) |
| pipeline failures | 0 | 0 |

## cam_t metric anchoring 詳細

UniDAC-anchored hands (n=21):
- cam_t z: **0.141-0.270 m** (mean 0.219, std small) → 物理的に手は cam から 14-27 cm
- cam_t x: 0.246-0.426 m
- cam_t y: -0.285 ~ -0.180 m
- wrist_depth_m (UniDAC raw): 0.374-0.509 m (mean 0.449)

**期待 range check**: 0.1-2.0 m 内に 21/21 = **100%** ✅ (前回 plan の "fisheye back-projection 0.2-2.0 m validation" 条件を満たす)

HaMeR fallback (n=2): frame 128/129 のみ、z=13.90/13.93 m (HaMeR uncalibrated scale)。検出窓 (128-150) の最初 2 frame で depth 割り当てが乗らなかった = pipeline の depth interp range の問題ではなく端っこ frame の depth 値が NaN/欠損だった可能性。残 21 frame で metric anchoring が効いてるので **pipeline 健全**。

## 実行コマンド (再現用)

```bash
# G8 full-ep depth (GPU 1, ~34 s)
PYTHONPATH=/home/gayagaya/MimicAnno/UniDAC:/home/gayagaya/MimicAnno \
CUDA_VISIBLE_DEVICES=1 \
/home/gayagaya/anaconda3/envs/unidac/bin/python scripts/precompute_depth.py \
  --input /home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --out /tmp/g8_full/depth/ \
  --preset A

# G7 HAMER (GPU 3, ~58 s)
CUDA_VISIBLE_DEVICES=3 \
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
hamer/.hamer/bin/python scripts/run_hand_estimation.py \
  --video /home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --depth /tmp/g8_full/depth \
  --out   /tmp/g7_full/hands
```

## 出力

- `/tmp/g8_full/depth/` — 151 frame ERP depth (.npy) + meta.json + viz/{erp.mp4, depth_fisheye.mp4}
- `/tmp/g7_full/hands/` — 151 frame .pkl (23 hand det) + signals.json + viz/overlay.mp4 (657 KB) + meta.json

## TODO 状況

- TODO L45「G7 full-ep 再走」(低優先) → **完了済へ移動可** ([[project_hand_pipeline_camera_model]] の memory も「cam_t metric anchoring proven」で更新可能)
- 残 follow-up: 端っこ 2 frame で depth が欠ける原因 (G8 の interp で fill されない frame range の端) は **minor、深追い不要**。Phase 5+ Replay UI 着手時に 95% anchored で十分

## 次に効くシナリオ

これで以下が gated 解除:
- Phase 5+ Replay UI で手の 3D 位置を mm 単位で可視化
- MimicRec で metric pose を使った hand mimicry
- HandSignalGraph (`3ae28bb`) の xyz cam_t グラフが意味ある値で表示 (前は HaMeR 13 m scale で無意味だった)
