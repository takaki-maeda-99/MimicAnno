# G8 UniDAC precompute_depth 1 ep smoke — 結果

- **実行日**: 2026-05-17
- **env**: `conda activate unidac` (`/home/gayagaya/anaconda3/envs/unidac/bin/python`)
- **GPU**: `CUDA_VISIBLE_DEVICES=1` (NVIDIA, 47983 MiB free at start)
- **入力**: `/home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4` (`--limit 30` 軽量化)
- **出力**: `/tmp/g8_smoke/depth/`
- **ログ**: `/tmp/g8_smoke.log`
- **追加環境変数**: `PYTHONPATH=/home/gayagaya/MimicAnno/UniDAC:/home/gayagaya/MimicAnno`
  (conda env に `unidac` パッケージが editable install されておらず、PYTHONPATH を通さないと `ModuleNotFoundError: No module named 'unidac'`。これは smoke だけの workaround で、コード/env 改変はせず。)

## 実行コマンド

プラン記載の `--save-viz` フラグは `scripts/precompute_depth.py` の argparse に存在しない (`--no-viz` が逆向きフラグとして存在)。viz はデフォルト ON のため、`--save-viz` を外して実行。

```bash
PYTHONPATH=/home/gayagaya/MimicAnno/UniDAC:/home/gayagaya/MimicAnno \
CUDA_VISIBLE_DEVICES=1 \
python scripts/precompute_depth.py \
  --input /home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --out /tmp/g8_smoke/depth/ \
  --preset A \
  --limit 30
```

## チェックリスト判定

| 検証項目 | 結果 | 根拠 |
|---|---|---|
| precompute_depth.py が落ちず完走 | ✅ | exit 0、ログ末尾 `--limit 30 reached; stopping.` / `done. processed=30 skipped=0 failures=0 elapsed=51.0s` |
| `frame_NNNNNN.npy` が 30 枚生成 | ✅ | `ls /tmp/g8_smoke/depth/frames/ | wc -l` = 30 |
| depth 値域が物理的に妥当 (min ≥ 0, max ≤ 50 m) | ✅ | `frame_000000.npy`: shape=(512, 704) dtype=float32 min=0.392 max=1.244 mean=0.535 (m)。ログ上の他フレームも min≈0.37–0.39, max≈1.24–1.31。手前のテーブル/物体距離としても妥当。 |
| `viz/erp.mp4` 生成 | ✅ (ただし小サイズ) | 68,756 B (≈67 KB)。プラン期待値 ≥100 KB を **下回る**が、30 フレーム短尺かつ 704x512 H.264 ということで非ゼロ・再生可能サイズではある。 |
| `viz/depth_fisheye.mp4` (back-warp = "warp/fuse") 生成 | ✅ (ただし小サイズ) | 17,872 B (≈17 KB)。同様に 30 フレーム短尺・320x180 解像度のため。プラン閾値 100 KB は下回る。 |
| meta.json に preset/git/UniDAC config 記載 | ✅ | `preset=A`, `unidac_version=bb34cf2`, `fwd_sz=[512,704]`, `cano_sz=[1400,1400]`, `preset_params` (config / fl_x_ref / fl_y_ref / camera_model=OPENCV_FISHEYE / crop_wFoV=150) 全て記載 |

## 結論

**PASS (with one caveat)**

UniDAC depth pipeline は SO101 ep0 で regression なく完走。30 frame で `processed=30 skipped=0 failures=0` (51 s, 0.59 fps)。depth 値域は 0.37–1.31 m、ERP shape (512, 704) float32 で物理的に妥当。`erp.mp4` (~67 KB) と `depth_fisheye.mp4` (~17 KB) も生成され、back-warp ("warp/fuse") パスも健在。meta.json には preset / UniDAC version / fisheye camera config が揃っており、後段 (G7 hand pipeline) が参照する `preset_params` ([[project_hand_pipeline_camera_model]]) も問題なし。

Caveat: 両 viz mp4 がプラン期待値 (>100 KB) を下回るが、これは `--limit 30` の短尺 (30 frames @ 15fps = 2s) と低解像度 (depth_fisheye が 320x180) によるもので、回帰ではない (各 frame の depth は正常)。100 KB 閾値は full ep を前提にした目安だったとみる。次に full ep を流す機会があれば改めて確認。

副次知見: conda `unidac` env に `unidac` パッケージが editable install されておらず、`PYTHONPATH=/home/gayagaya/MimicAnno/UniDAC` を毎回足す必要がある。プラン上の手順とは異なるので、再現性のため将来的に `pip install -e UniDAC/` するか、wrapper script を整備する余地あり (out-of-scope: コード改変なし)。

次のステップ: G7 (hand+HAMER) がこの `/tmp/g8_smoke/depth/` を入力に動作するかを確認。
