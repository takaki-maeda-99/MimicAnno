# SO101 Phase 4 finer-seg v4 バッチ結果 (T8)

Date: 2026-05-12
Related:
- `docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md` §6.5
- `docs/superpowers/plans/2026-05-11-phase4-finer-segmentation-plan.md` T8
- `2026-05-11-so101-gripper-scale-max.md` (scale_max=60 採用)
- `2026-05-11-so101-zc-resim-new-scale.md` (hyst=0.12 採用)
- `2026-05-11-so101-otsu-justification.md` (hyst 理論的裏付け)
- `runs/so101_phase4_v4/`
- `runs/so101_phase4_v3/` (比較対象)

---

## TL;DR

ZC detector は実データで仕様通りに candidate を生成している（mean 3.57 cands/ep, median 4）。
**しかし最終 segment 数は mean 2.78 と sim 予測 (4.83) を大きく下回り、spec §6.5 の exit criteria を満たさない**。

原因は ZC detector 側ではなく **Phase 4 smoother `_merge_same_label` が VLM の phase ラベルが同じ隣接 segment を collapse している** こと（23 ep 中 17 ep で `merge_same_label` op が走っていた）。

これは zc-resim ノートの sim が **detector 単体** で評価していて、下流の smoother を考慮していなかったために発生した予測ズレ。アルゴ自体の不具合ではない。

---

## 実行構成

```yaml
# mimicanno/configs/boundary/so101_zero_crossing.yaml
zero_crossing:
  enabled: true
  signal: gripper
  ref: midpoint
  hysteresis: 0.12
  span_eps: 0.05
  merge_window_sec: 0.0
  weight: 0.5
```

- gripper_scale_max: 60.0
- 入力: `data/SO101/`、ep 0-32 を 3 GPU 並列で実行（GPU0 ep0、GPU2 ep1-15、GPU3 ep16-32）
- 完走 23 ep（ep11-15, 33-35 は fps.unresolvable、v3 と同じ範囲）

---

## 全 ep 集計表

| ep | cands | zc cands | segs | merge_same_label 適用 | degrade |
|---|---|---|---|---|---|
| 000 | 4 | 4 | 2 | ✓ | – |
| 001 | 3 | 3 | 3 | ✓ | – |
| 002 | 3 | 3 | 4 | – | sam3_no_initial_detection |
| 003 | 4 | 4 | 5 | – | sam3_no_initial_detection |
| 004 | 3 | 3 | 3 | ✓ | – |
| 005 | 4 | 4 | 4 | ✓ | – |
| 006 | 3 | 3 | 3 | ✓ | – |
| 007 | 4 | 4 | 2 | ✓ | – |
| 008 | 4 | 4 | 2 | ✓ | – |
| 009 | 4 | 4 | 5 | – | sam3_no_initial_detection |
| 010 | **0** | **0** | **1** | – | sam3_no_initial_detection |
| 021 | 4 | 4 | 4 | ✓ | – |
| 022 | 4 | 4 | 1 | ✓ | – |
| 023 | 2 | 2 | 2 | ✓ | – |
| 024 | 5 | 5 | 2 | ✓ | – |
| 025 | 4 | 4 | 2 | ✓ | – |
| 026 | 2 | 2 | 3 | – | sam3_no_initial_detection |
| 027 | 4 | 4 | 3 | ✓ | – |
| 028 | 4 | 4 | 2 | ✓ | – |
| 029 | 5 | 5 | 2 | ✓ | – |
| 030 | 4 | 4 | 2 | ✓ | – |
| 031 | 4 | 4 | **5** | – | – |
| 032 | 4 | 4 | 2 | ✓ | – |

### 集約指標

| 指標 | zc-resim 予測 | v4 実測 | 達成 |
|---|---|---|---|
| mean cands / ep | – | 3.57 | – |
| mean segs / ep | 4.83 | **2.78** | ❌ |
| median segs | 5.0 | **2** | ❌ |
| seg ≥ 3 | 22/23 | **11/23** | ❌ |
| seg ≥ 5 | 20/23 | **3/23** | ❌ |
| ep10 が 1 segment | ✓ | ✓ (cands=0 で正しくスキップ) | ✅ |
| 全 ep が走る | ✓ | ✓ (23/23、v3 同等) | ✅ |

---

## 原因分析

### 観察

ZC candidate は十分な数出ているのに、annotation.json の segments がそれより少ない:

| ep | cands timestamps | final segment 境界 |
|---|---|---|
| ep0 | t=1.36, 3.37, 5.82, **6.62** | **6.62** のみ採用、他は消失 |
| ep24 | t=2.32, 4.28, 5.08, 6.82, **7.28** | **7.28** のみ採用 |
| ep31 | t=1.77, 3.93, 6.09, 6.61 | **全て採用** |

### 決定的証拠

`annotation.json: segments[*].smoothing_ops` を確認すると:

```
ep0  seg0: ops=['merge_same_label']  phase=approach_object
ep0  seg1: ops=[]                    phase=place_object

ep24 seg0: ops=['merge_same_label']  phase=approach_object
ep24 seg1: ops=[]                    phase=place_object

ep31 seg0: ops=[]  phase=idle
ep31 seg1: ops=[]  phase=approach_object
ep31 seg2: ops=[]  phase=grasp_object
ep31 seg3: ops=[]  phase=approach_object
ep31 seg4: ops=[]  phase=place_object
```

ep0/ep24 は **複数の ZC boundary を跨ぐ間ずっと VLM が `approach_object` を返している** ため、`mimicanno/smoother.py::_merge_same_label` が隣接同 phase segment を一つに collapse している。

ep31 だけ最後まで 5 segment 残ったのは、VLM が idle → approach → grasp → approach → place と毎回ラベルを変えたから。

degraded ep (ep2/3/9/26) で逆に segment 数が多いのは、VLM labeler が走らず phase=None のままで merge 判定が走らないため。

### 結論

- **ZC detector は spec / sim 通りに動作している** (3.57 cands/ep)
- **問題は ZC ではなく VLM labeler の phase 粒度** が粗いこと（grasp_object と approach_object/place_object を一連の動作として `approach_object` でラベリングしてしまう）
- spec の "seg≥3 を 22/23 ep" 目標は、smoother を経由した pipeline 出力には適用できない。zc-resim sim は detector 単体評価で、smoother を含めていなかった

---

## 判断と次手

### Exit criteria 達成状況

- 量的指標 (spec §6.5 seg数): ❌ 達成せず
- ep10 安全性 (span_eps によるスキップ): ✅
- 環境変化への頑健性 (gripper_scale_max=60 で正常動作): ✅
- 全 ep 走行率 (v3 同等): ✅

### Phase 4 finer-seg の真の状態

「ZC detector を追加することで、原理上 finer segmentation が可能な base 構造になった」 は達成。
「実データで mean 5 segment/ep が得られる」 は **未達**。 ボトルネックは ZC ではなく VLM ラベル粒度。

### 取りうる選択肢

1. **VLM プロンプトを finer 化** (`approach_object` を grasp 段階別に細分化、e.g. `pre_grasp_approach` / `post_grasp_approach`)
   - 影響範囲: `mimicanno/vlm_labeler.py` の phase enum / prompt
   - 既存 phase ラベル分類 v1 を破壊する大きな変更
2. **Phase 4 smoother の `_merge_same_label` を boundary 由来別に振る舞いを変える**
   - 例: source に `gripper_zero_crossing` を含む boundary では merge_same_label を抑制
   - 影響範囲: smoother + config (`merge_same_label_skip_sources`)
3. **min_segment_duration_sec / merge logic を再調整**
   - 効果は限定的、根本原因は phase ラベル粒度
4. **現状を accept し spec を改訂**: ZC は base 構造として持つ、finer-seg は VLM 改善後の future work とする

### 推奨

**選択肢 1 と 2 のハイブリッド**:

- 短期 (今 sprint 内): 選択肢 2 を実装。ZC 由来 boundary を保持するオプションを smoother に追加し、再走で mean segs が予測値に近づくか確認
- 中期: 選択肢 1。VLM の phase enum を grasp 状態軸 (object_held: yes/no) で finer 化し、approach_object を更に細分化

---

## 補足: degraded ep の取り扱い

`sam3_no_initial_detection` で degrade した 5 ep (ep2/3/9/10/26) は VLM labeler を経由しないため segment が ZC 出力に近い形で残る。これは「smoother が悪さしていない」 証拠でもある。

degraded ep を除いた 18 ep の mean segs は 2.56、seg≥3 は 7/18 = 39%。VLM が走っているほど smoother で collapse される傾向。

---

## アーティファクト

- 出力: `runs/so101_phase4_v4/episode_*/`（23 ep）
- ログ: `logs/batch_so101_v4/`、`logs/v4_gpu{0,2,3}*.out`
- 比較対象 v3: `runs/so101_phase4_v3/`（同 23 ep、detector OFF、1 segment/ep）

### 代表 ep のセグメント時刻

```
ep0  v3: [0.0-10.07]                          (1 seg)
ep0  v4: [0.0-6.62] [6.62-10.07]              (2 seg, merge_same_label)
ep24 v3: [0.0-10.0]                           (1 seg)
ep24 v4: [0.0-7.28] [7.28-10.0]               (2 seg, merge_same_label)
ep31 v3: [0.0-10.0]                           (1 seg)
ep31 v4: [0.0-1.77] [1.77-3.93] [3.93-6.09] [6.09-6.61] [6.61-10.0]  (5 seg ✅)
```

ZC enabled の効果は v3 比で明らかに segment 増加 (mean 1.0 → 2.78)。ただし sim 予測には到達せず。
