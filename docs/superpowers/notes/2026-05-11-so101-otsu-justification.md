# Otsu 法による Phase 4 finer-seg ZC パラメータの理論的裏付け

Date: 2026-05-11
Reference: `/home/gayagaya/lerobottest/lerobot-piper-analysis/gripper_threshold.py`
Related:
- `2026-05-11-so101-gripper-scale-max.md` (scale_max=60 への変更)
- `2026-05-11-so101-zc-resim-new-scale.md` (新スケール sweep で hyst=0.12 採用)
- `docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md`
- `images/2026-05-11-so101-otsu.png`

---

## 動機

これまで Phase 4 finer-seg の ZC 検出器パラメータ (`ref` と `hyst`) は経験的に決めていた:

- `ref = (max + min) / 2` (episode ごとの midpoint)
- `hyst = 0.12` (新スケールでの sweep の plateau 中央)

参照: `/home/gayagaya/lerobottest/lerobot-piper-analysis/gripper_threshold.py` で Otsu の二クラス判別法を gripper のしきい値選定に使う前例があり、これを応用して **統計的に最適なしきい値とその派生でヒステリシスも理論的に導く**ことを目的とする。

## Otsu の二クラス判別法

ヒストグラム上で **クラス間分散 σ_b² を最大化**するしきい値を選ぶ古典的手法 (Otsu 1979)。前提は **データが 2 つの cluster (例: open/closed) からなる bimodal 分布**。

```
σ_b² = w0(t) · w1(t) · (μ0(t) - μ1(t))²
```

t < しきい値、t ≥ しきい値の 2 クラスについて、各クラスの存在確率 w と平均 μ を計算し σ_b² を最大化する t* を選ぶ。

## SO101 全 36 ep への適用

- 入力: `/misc/dl00/gayagaya/MimicAnno/data/SO101/data/chunk-000/episode_*.parquet` の `observation.state.gripper_pos` (raw)
- 正規化: `(g - 0) / (60 - 0)` で [0, 1] に scale (今回採用した max=60)
- N = 5286 frame, 36 episode

### しきい値候補

| 候補 | 値 | 算出方法 |
|---|---|---|
| **Otsu pooled (全データ)** | **0.3337** | σ_b² 最大化 |
| Otsu per-ep 平均 | 0.3082 | 各 ep の Otsu の平均 |
| midpoint (pooled min/max) | 0.4811 | (max+min)/2 グローバル |
| mean (pooled) | 0.2302 | 全データ平均 |
| **per-ep midpoint mean** (現状の ref) | **0.3686** | (max+min)/2 を各 ep で計算した平均 |

→ Otsu と per-ep midpoint は ~0.03 しか違わない。**統計的にほぼ等価**。

### クラスタ統計 (Otsu pooled しきい値で分割)

| クラスタ | n | 比率 | μ | σ | max/min |
|---|---|---|---|---|---|
| closed (x < 0.334) | 3798 | 71.9% | 0.0953 | 0.0422 | max=0.3323 |
| open   (x ≥ 0.334) | 1488 | 28.1% | 0.5744 | 0.1130 | min=0.3358 |

- **inter-cluster separation**: μ_open - μ_closed = **0.4790**
- **clean margin (gap between clusters)**: min_open - max_closed = **+0.0035** (ほぼ接している)

### Hysteresis の理論的派生

しきい値が決まれば、cluster の広がりから hyst を導ける:

| 派生式 | 値 | ZC sim (seg≥5) |
|---|---|---|
| 2σ within-class (max=σ_open=0.113) | 0.226 | 7/23 (劣化) |
| 3σ within-class | 0.339 | 0/23 (壊滅) |
| min dist (Otsu→μ_cluster) | 0.238 | 7/23 |
| 0.5 × cluster_separation | 0.240 | 0/23 |
| **0.5 × min_dist(Otsu, μ_cluster)** | **0.119** | **20/23** ✓ |
| 0.25 × cluster_separation | 0.120 | 20/23 ✓ |
| **手動 sweep choice** | **0.12** | **20/23** ✓ |

### 重要な発見

手動 sweep で選んだ **hyst=0.12** は、以下 2 つの自然な data-driven 定義式と数値的に一致:

1. **`0.5 × min_dist(Otsu_threshold, μ_cluster)`** = 0.5 × 0.238 = 0.119
2. **`0.25 × cluster_separation`** = 0.25 × 0.479 = 0.120

→ 「シグナルが Otsu しきい値から **最近 cluster 中央までの半分** まで振れること」「**inter-cluster 距離の 1/4** だけ振れること」という二つの言い方ができる。これは

- **遷移を取り逃がさない**: 台形は full separation (0.48) を振れるので、1/4 程度の hyst は確実に通る
- **ノイズに発火しない**: 同 cluster 内のσ (max 0.113) よりは大きいので静止状態のジッタでは発火しない

を同時に満たす自然な選択。

逆に **3σ / 0.5·separation 系 (≈ 0.24) は静的フレーム分類向き**で、遷移検出にはきつすぎる (台形の半分振り切る前に次の crossing を要求 → 往復を取りこぼす)。

### Ref 選択の比較 (ZC sim)

`runs/so101_phase4_v3/` の signals を新スケール換算した上で各 ref で実行:

| config | mean seg | seg≥3 | seg≥5 |
|---|---|---|---|
| ref=midpoint per-ep, hyst=0.12 | 4.83 | 22/23 | 20/23 |
| ref=Otsu pooled (0.334), hyst=0.12 | 4.78 | 21/23 | 20/23 |
| ref=Otsu per-ep avg, hyst=0.12 | 4.74 | 22/23 | 20/23 |

3 案は実質同等。**per-ep midpoint の方が seg≥3 でわずかに勝る** (低 span ep で Otsu 固定だと範囲外になることがあるため)。

## 採用方針

- **ref = `midpoint` (per-ep) を継続採用**: Otsu と統計的に等価、追加計算なし、低 span ep でも範囲内に収まる
- **hyst = 0.12 を継続採用**: `0.5 × min_dist(Otsu, μ_cluster)` の data-driven 値と一致、sweep plateau の中央
- 将来 robot を変える場合の手順:
  1. 全 ep の正規化済み gripper を pool
  2. Otsu でしきい値 T を計算
  3. T 以下/以上の 2 cluster に分割し μ_closed, μ_open を計算
  4. `hyst = 0.5 × min(T - μ_closed, μ_open - T)` または `0.25 × (μ_open - μ_closed)`

これで Phase 4 finer-seg は **「手で決めた経験値」**ではなく **「Otsu + cluster 距離から導いた data-driven 値」** という地位を獲得する。

## Plot

`docs/superpowers/notes/images/2026-05-11-so101-otsu.png` に以下 4 パネルを保存:
- (a) pooled gripper histogram + 各しきい値候補
- (b) Otsu の目的関数 σ_b² カーブ
- (c) per-ep min/max range + Otsu しきい値
- (d) 推奨値テーブル
