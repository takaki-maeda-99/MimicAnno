# SO101 ZC sim 再走 (new gripper_scale_max=60) — hyst 既定値の決定

Date: 2026-05-11
Related:
- `2026-05-11-so101-gripper-scale-max.md` (scale 変更の根拠)
- `docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md` §2-§4 (本ノートで更新元)
- `docs/superpowers/plans/2026-05-11-phase4-finer-segmentation-plan.md` T0

---

## 目的

`gripper_scale_max` を 100 → 60 に変更した影響を Phase 4 finer-seg の zero-crossing detector に反映する。

- 旧スケール (max=100, span≈0.35) で決めた `hyst=0.05` は新スケール (max=60, span≈0.59) には小さすぎる/逆に大きすぎる可能性
- 新スケールで sweep して安全 plateau の中央値を採用

## 方法

`runs/so101_phase4_v3/episode_*/signals.json` の gripper signal は旧スケール出力。再走せずに **`new = clip(old * 100/60, 0, 1)`** で新スケール相当を作る (raw → /100 → ×100/60 = /60 の数学的同値変換、smoothing は v3 のまま継承)。

23 ep について `detect_gripper_zero_crossing(gripper, t, span_eps=0.05, hyst=H, ref=midpoint)` を H ∈ {0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25} で sweep。

## 結果

### Gripper 統計の変化

| 指標 | 旧 (max=100) | 新 (max=60) | 倍率 |
|---|---|---|---|
| mean span | 0.354 | 0.589 | 1.66× |
| median span | 0.378 | 0.630 | 1.67× |
| max span | 0.479 | 0.798 | 1.67× |
| pooled p99 \|Δ\| | 0.076 | 0.127 | 1.67× |
| pooled max \|Δ\| | 0.080 | 0.134 | 1.67× |

理論通り 100/60 = 1.667 倍。clip による情報損失なし (生 max 53.79 < 60)。

### Hyst sweep (新スケール、23 ep)

| hyst | mean seg | median | seg≥3 | seg≥5 | 評価 |
|---|---|---|---|---|---|
| 0.05 | 4.91 | 5.0 | 22/23 | 21/23 | plateau 端 (低側) |
| 0.08 | 4.91 | 5.0 | 22/23 | 21/23 | plateau |
| 0.10 | 4.83 | 5.0 | 22/23 | 20/23 | plateau |
| **0.12** | **4.83** | **5.0** | **22/23** | **20/23** | **plateau 中央 — 採用** |
| 0.15 | 4.52 | 5.0 | 22/23 | 17/23 | plateau 端 (高側) |
| 0.18 | 4.22 | 5.0 | 22/23 | 14/23 | 劣化開始 |
| 0.20 | 3.91 | 4.0 | 21/23 | 11/23 | 劣化 |
| 0.25 | 3.30 | 3.0 | 20/23 | 4/23 | 過剰除外 |

### Per-ep at hyst=0.12

| ep | span | n_b | segs | コメント |
|---|---|---|---|---|
| ep0  | 0.576 | 4 | 5 | 典型 2 サイクル |
| ep10 | 0.000 | 0 | 1 | 壊れ ep、span_eps で正しくスキップ |
| ep23 | 0.587 | 2 | 3 | 1 サイクル ep (元から cycles=2) |
| ep24 | 0.603 | 6 | 7 | 3 サイクル ep |
| ep29 | 0.551 | 6 | 7 | **旧スケール hyst=0.10 では 4 だった (新スケール改善)** |

その他は 4 boundaries / 5 segments で均一。

### ep0 比較プロット

`docs/superpowers/notes/images/2026-05-11-ep0-zc-new-scale.png`

旧 (hyst=0.05) と新 (hyst=0.12) で **完全に同じ 4 boundary 時刻** (1.36 / 3.40 / 5.82 / 6.62s)。アルゴリズムは線形スケーリングに対して時刻保存的であることを確認。

## 採用値

`mimicanno/configs/boundary/so101_zero_crossing.yaml` (実装時に作成) のデフォルト:

```yaml
zero_crossing:
  enabled: true
  signal: gripper
  ref: midpoint
  hysteresis: 0.12          # plateau 中央。span≈0.59 の 20% 相当
  span_eps: 0.05
  merge_window_sec: 0.0
  weight: 0.5
```

### hyst=0.12 を選んだ理由

1. **plateau の中央**: hyst ∈ [0.05, 0.15] 全てで seg≥3 を 22/23 ep 達成。中央値 0.12 が **両端からの距離が最大** = キャリブレーション余裕が大きい
2. **新スケール span の ~20%**: span≈0.59 の 1/5 程度で、grasp 動作 (台形の片側振れ幅 ~0.3) に対し十分小さくノイズ (|Δ|<0.05) は確実に除外
3. **将来 scale を別値に変えても比例 scaling しやすい**: 「hyst ≈ 0.2 × mean_span」というルールが立つ

## spec / plan 更新項目

1. spec §2.3 のシミュレーション表 → **新スケール基準で書き換え** (本ノートの sweep 表)
2. spec §4.2 の default `hysteresis: 0.05` → **`0.12`** に変更
3. spec §5.2 YAML 例の `hysteresis: 0.05` → **`0.12`**
4. spec §8 Q5 の「実装時に再キャリブレーションが必要」を「本ノートで決定済み」に更新
5. plan T0 を **完了** マーク

## 補足: scale_max 変更後の signals.json の取り扱い

`runs/so101_phase4_v3/` は旧スケールで生成済み。実装後に新スケールで再走する際、output は `runs/so101_phase4_v4/` (input_hash が変わるので canonical_name が変わる)。本ノートの sim は旧 v3 signals を数学的に新スケールへ変換して評価したもので、新スケールで pipeline を再走したものではない。**実装後の T8 (SO101 23 ep バッチ実行) で実 pipeline 経由の値と一致することを確認する必要がある**。

> **2026-05-12 追記**: T8 で確認したところ、ZC detector の candidate 数は本 sim の予測 (mean ~4) とほぼ一致 (実測 3.57) したが、最終 segment 数は Phase 4 smoother の `_merge_same_label` で大きく縮約された (mean 2.78)。本 sim は **detector 単体の評価で smoother を含めていない** ため、segment 数の予測としては不適切だった。詳細: `2026-05-11-so101-phase4-v4-results.md`。
