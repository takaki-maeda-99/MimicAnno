# SO101 `gripper_scale_max` の再調整 (100 → 60)

Date: 2026-05-11
Related:
- `tests/exports/fixtures/so101_robot_config.yaml`
- `mimicanno/configs/exports/so101_sarm.yaml`
- `README.md` / `README.ja.md` (SO101 example block)
- `docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md` (Q5)

---

## 背景

`GenericAdapter` の `gripper_scale_max` は SO101 の生 `observation.state.gripper_pos` を `(g - min) / (max - min)` で [0, 1] 正規化する際の上限値。SARM 学習の `gripper_normalized ∈ [0, 1]` 規約 (`gripper=0` 閉、`gripper=1` 開) に合わせるために導入された (Phase 5 export spec §2)。

初期値 `100.0` は **2026-04-30** に「SO101 gripper is reported in 0..100 units」という想定で採用された (commit `27d943d`)。同日 ep0 の実測 (4.258–38.837) が判明したが、「保守的」として 100 のまま維持された (commit `38fef93` のコメント `100 is conservative`)。

しかしこの設定により:

- 正規化後 gripper 値は実質 [0.04, 0.39] にしか広がらない (span ≈ 0.35)
- Phase 1-3 の boundary 検出しきい値 (`gripper_delta=0.30`) が過大になり全 23 ep で 0 boundary
- Phase 4 finer-seg spec で hysteresis を 0.05 に下げる必要が生じた

→ scale_max を実データに合わせて引き下げる。

---

## 実測 (`/misc/dl00/gayagaya/MimicAnno/data/SO101/data/chunk-000/`)

36 episode、計 5286 frame を `pyarrow.parquet` で読み込み:

```
global min: 3.9460
global max: 53.7902
p99.9:      52.3364
p99:        47.0405
p95:        41.0177
p50:         6.3344
p1:          3.9460
```

Top 5 max:

```
episode_000019  min=4.154  max=53.790  mean=17.616
episode_000030  min=4.465  max=52.336  mean=15.826
episode_000017  min=4.050  max=51.298  mean=12.848
episode_000031  min=4.361  max=47.664  mean=13.903
episode_000006  min=4.465  max=47.560  mean=25.864
```

**重要**: 当初「実最大 ~40」と判断していたが、それは ep0 (max=38.84) のみの観察。全 36 ep ではより広く、**実最大 53.79** に達する。

---

## 採用値: `gripper_scale_max = 60.0`

### 候補比較

| 候補 | 正規化後 span | 利点 | 欠点 |
|---|---|---|---|
| 100 (旧) | 0.50 | (旧) | 観測 max 比 1.86 倍で過大、Phase 1-3 boundary 検出を破壊 |
| **60 (採用)** | **0.83** | **観測 max +12% のヘッドルーム、丸めて綺麗** | (なし) |
| 55 | 0.91 | 観測 max に最接近 | 未収録 ep で 55 を超えると clip 発生 |
| 54 | clip 多発 | – | 既存データで clip |
| 動的 (per-ep max) | 1.00 ぴったり | ep 間正規化不要 | episode 間で意味が変わり SARM 学習で意図と異なる |

### 60 を選んだ根拠

1. **観測 max=53.79 に対し約 12% のヘッドルーム** (= 6 単位)。一般的なセンサー再キャリブレーション誤差や、未収録の極端な握り込みで多少超過しても clip しない
2. **丸めて綺麗な値** (10 単位刻みで人間が読みやすい)
3. **正規化後の値域は [0.066, 0.897]** で、両端に少しゆとりがあるが 0 / 1 の意味 (完全開 / 完全閉) と概念的に整合
4. **boundary 検出への副次効果**: span が 0.35 → 0.83 (2.4 倍) に拡大し、Phase 1-3 既存しきい値 (gripper_delta=0.30) のサイズ感に近づく。Phase 4 finer-seg の hyst も自然な値 (~0.12) に落ち着く見込み

### なぜ 55 や 100 にしなかったか

- **55**: ヘッドルームがほぼゼロ。新規収集データや別個体ロボットで 55 を超えるとサイレントに clip され、信号情報が失われる。clip された frame は |Δ|=0 となり boundary 検出器を欺く
- **100**: 過剰な保守性が今回の問題を生んだ。同じ過ちを繰り返さない

---

## 副作用と影響範囲

### 既存 run への影響
- `runs/so101_phase4_v1/`, `_v2/`, `_v3/` の出力は変化しない (input_hash 計算時の adapter config が変わるので、再走時は新しい canonical_name で別ディレクトリに出力される)
- 既存 export 出力 `runs/so101_phase4_v3_export/` も同様に不変

### Phase 4 finer-seg (`docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md`) への影響
- spec §2.1-§2.3 の統計表は **旧 scale_max=100 前提**。新 scale で再測定が必要
- spec §4.2 / §5.2 の `hysteresis=0.05` は span≈0.35 前提 → 新 span≈0.83 では **~0.12 程度** に上方修正される見込み
- 再シミュレーションして spec を更新するタスクが追加 (Phase 4 finer-seg plan T0 として先に走らせる)

### SARM 学習互換性
- 過去に SARM 学習を回した形跡なし (export データ生成済みだが訓練未着手)
- 影響なし

### README 表記
- `README.md` / `README.ja.md` の SO101 example block の `gripper_scale_max: 100.0` を 60.0 に更新

---

## 今後の運用方針

- **新規ロボット追加時は実データを 36+ episode 計測し、観測 max + 10-15% で `gripper_scale_max` を設定する**ことをルールとする
- `gripper_scale_min` は常に 0.0 (理論的下限) でよい
- 過去観測の range をコード/設定の近くにコメントで残す (本ノートをリンク)
- scale_max を将来変更する場合は (a) 既存 run / export と互換性チェック、(b) 依存する boundary 検出パラメータの再キャリブレーション、(c) 本ノートの更新版を作成
