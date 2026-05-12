# Piper Phase 4 ZC OFF vs ZC ON A/B 結果

Date: 2026-05-12
Dataset: `LegrandFrederic/Marker_pickup_piper` (Agilex Piper 7-DoF, 39 ep, 30 fps,
overhead `observation.images.secondary_0` camera, total 28685 frames)
Related:
- `docs/superpowers/specs/2026-05-12-phase4-smoother-source-aware-merge-design.md` (本 spec の根拠データ)
- `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` (SO101 同等比較)
- `mimicanno/configs/robot/piper_robot_config.yaml` (GenericAdapter v0.2.0)
- `mimicanno/configs/boundary/piper_zero_crossing.yaml` (Otsu キャリブ済み, hyst=0.12)
- `runs/piper_phase4/` (ZC OFF, n=39)
- `runs/piper_phase4_zc/` (ZC ON, n=39)

---

## TL;DR

Piper データに対し ZC detector を ON にすると mean segments/ep は
**1.00 → 2.31** に増え、boundary ガジェット自体は仕様通り動く。一方で
**29/39 ep (74%) で `merge_same_label` が発火** しており、SO101 T8 と
同じく "ZC が candidate を立てた直後に Phase 4 smoother が VLM 同一 phase 隣接
segment を collapse する" 現象が再現した。

これは本ブランチ
(`feat/phase4-smoother-source-aware-merge`) で改修対象としている smoother
ボトルネックが **SO101 固有ではなく、ZC + VLM の組み合わせに普遍** であることを
示しており、本 spec の方向性 (source-aware preserve) の妥当性を実データで裏付ける。

---

## 集約指標

| 指標 | ZC OFF | ZC ON | 変化 |
|---|---|---|---|
| 完走 ep | 39/39 | 39/39 | 同 |
| degraded (sam3_no_initial_detection) | 1 (ep14) | 1 (ep14) | 同 |
| coverage < 1.0 (track lost mid-episode) | 4 | 5 | +1 (ep20) |
| **mean n_segments / ep** | **1.00** | **2.31** | **+1.31** |
| **mean ZC candidates / ep** | 0.00 | 2.36 | +2.36 |
| segments ≥ 2 | 0 / 39 | **36 / 39** | +36 |
| segments ≥ 3 | 0 / 39 | 13 / 39 | +13 |
| segments ≥ 4 | 0 / 39 | 2 / 39 | +2 |
| **`merge_same_label` 発火 ep** | 0 / 39 | **29 / 39** | **+29** |

### VLM phase 分布

| phase | ZC OFF | ZC ON |
|---|---|---|
| approach_object | 36 | 40 |
| place_object | 0 | **35** |
| grasp_object | 3 | 8 |
| move_to_target | 0 | 5 |
| idle | 0 | 2 |

ZC ON で初めて `place_object` (35 segments で出現) と `move_to_target` (5
segments) が登場。task は "Pick up the marker and place it" なので VLM は
finer ウィンドウを与えると後半を正しく `place_object` と判定できている。
ZC OFF では全 ep が approach_object 一色 (3 ep だけ grasp_object) で、後半の
"place" 動作が完全に潜在化していた。

---

## SO101 T8 との比較

| 指標 | SO101 T8 (23 ep) | Piper (39 ep) |
|---|---|---|
| mean ZC candidates/ep | 3.57 | 2.36 |
| mean segments/ep | 2.78 | 2.31 |
| `merge_same_label` 発火率 | 17/23 = **74%** | 29/39 = **74%** |
| ZC candidate を VLM 同一 phase で潰す現象 | ✓ | ✓ |

**`merge_same_label` 発火率が 74% で一致** している点は偶然ではなく、
ZC が gripper の物理的遷移 (open↔close) で boundary を打つ → VLM が同じ
"approach_object" を返す傾向 → smoother が collapse、という連鎖が
robot/データセットに依存しない普遍パターンであることを示している。

Piper の方が mean candidates が低い (3.57 → 2.36) のは:
- gripper 軸 1 本のみ (eef なし → `eef_velocity_valley` 等 disabled)
- 1 ep の動作回数が少ない (Piper はワンショット pickup 中心、SO101 は
  tape を入れる動作で gripper の動きが多めの傾向)

---

## 代表 ep ケーススタディ

### ep10: ZC 5 cand → final 2 segment (smoother で 3 個 collapse)
- OFF: `[approach_object]`
- ON cands=5, segs=2: `[approach_object, place_object]`
- merge_same_label fired: YES (5 candidates のうち 3 個が同 phase 隣接で消えた)

### ep20: ZC 5 cand → final 4 segment (smoother で 1 個 collapse)
- OFF: `[approach_object]`
- ON cands=5, segs=4: `[approach_object, grasp_object, move_to_target, place_object]`
- merge_same_label fired: YES
- 一番きれいに細分化できた代表例

### ep4: ZC 1 cand → final 2 segment (collapse 無し)
- OFF: `[approach_object]`
- ON cands=1, segs=2: `[approach_object, place_object]`
- merge_same_label fired: NO
- ZC 1 個でちょうど phase 切り替わる ideal なケース

### ep18: ZC 2 cand → final 1 segment (全 collapse)
- OFF: `[grasp_object]`
- ON cands=2, segs=1: `[approach_object]`
- merge_same_label fired: YES
- ZC が 2 candidate 立てたが VLM が両端 approach 判定 → smoother が collapse して
  1 segment、しかも label まで OFF と変わってしまった (grasp → approach)
- これは本 spec で `merge_same_label_preserve_sources` を効かせると
  `[approach, approach]` で残るはずだが、VLM 出力次第ではむしろ悪化する例。
  smoother spec の test plan §5.1 ケース #7 の "全 boundary が preserve" 想定。

---

## Phase 5 SARM 学習への含意

ZC OFF run は実質的に全 ep が 1 segment、VLM 学習データとして単一 phase の
グローバル特徴しか提供できない。ZC ON run は per-segment phase label が
3-4 通りに分かれるので、Gemma 4 の SFT データとしての価値が格段に高い。

ただし **smoother が collapse しているせいで** ON でも mean 2.31 segments/ep
止まり。spec の改修 (`merge_same_label_preserve_sources: [gripper_zero_crossing]`)
を入れた T9 相当の Piper 再走では mean 3.5+ segments/ep を期待 (29 ep の
collapse が抑制される)。

---

## アーティファクト

- ZC OFF: `runs/piper_phase4/` 39 ep
- ZC ON: `runs/piper_phase4_zc/` 39 ep
- VLM dumps: `runs/piper_phase4{,_zc}/_vlm_dumps/`
- batch script: `scripts/batch_piper_phase4.sh`
- preprocessing: `scripts/prep_piper_episodes.py` (HF 単一 parquet/mp4 → per-episode)
- robot config: `mimicanno/configs/robot/piper_robot_config.yaml`
- boundary config: `mimicanno/configs/boundary/piper_zero_crossing.yaml`

### Re-run コマンド

```bash
# ZC OFF baseline
GPU=1 START=0  END=19 bash scripts/batch_piper_phase4.sh
GPU=3 START=20 END=38 bash scripts/batch_piper_phase4.sh

# ZC ON
RUNS_ROOT=runs/piper_phase4_zc \
LOGS_DIR=logs/batch_piper_zc \
BOUNDARY_CONFIG=mimicanno/configs/boundary/piper_zero_crossing.yaml \
GPU=1 START=0 END=19 bash scripts/batch_piper_phase4.sh
```

## 補足: SAM3 grounding camera 選択

本セッション中の発見: 当初 `observation.images.main` (wrist 視点) を使ったが
SAM3 が "marker" を全く検出できず (0/13 prompt で 0 det)。`observation.images.secondary_0`
(overhead 視点) に切り替えで grounding 0.94 まで上昇。新 robot を追加する
ときの教訓: **wrist cam ではなく external static cam を使うべき** (SO101 の
`observation.images.front` と同じ運用)。
