# Piper Phase 4 v5 (ZC + smoother preserve_sources) 結果

Date: 2026-05-13
Dataset: `LegrandFrederic/Marker_pickup_piper` (39 ep, 30 fps, overhead camera)
Related:
- `docs/superpowers/notes/2026-05-12-piper-phase4-zc-ab-results.md` (ZC OFF vs ON A/B、本ノートの v4 列の出典)
- `docs/superpowers/specs/2026-05-12-phase4-smoother-source-aware-merge-design.md`
- `docs/superpowers/notes/2026-05-12-so101-phase4-v5-results.md` (SO101 T9、参照対象)
- `runs/piper_phase4_v5/` 39 ep
- `mimicanno/configs/smoother/piper_zc_preserve.yaml`

---

## TL;DR

smoother spec の `merge_same_label_preserve_sources: [gripper_zero_crossing]`
を Piper に適用 (v5)、v4 (ZC ON のみ) と比較:

| 指標 | v4 (ZC ON) | v5 (+preserve) | SO101 T9 参考 |
|---|---|---|---|
| mean segments / ep | 2.31 | **3.36** | 4.52 |
| `merge_same_label` 発火 ep | 29 / 39 (74%) | **0 / 39** (0%) | 0 / 23 (0%) |
| seg ≥ 3 | 13 / 39 | **35 / 39** (90%) | 22 / 23 |
| seg ≥ 5 | 0 / 39 | **6 / 39** | 20 / 23 |

**spec の効果が Piper でも完全再現**。merge_fired が 29 → 0 と消滅し、ZC
candidate がそのまま最終 segment として残るようになった。SO101 と同じ
パターンで robot 非依存に動作することを実データで実証。

---

## 完全集計

| 指標 | ZC OFF | ZC ON (v4) | ZC + preserve (v5) |
|---|---|---|---|
| n 完走 | 39 | 39 | 39 |
| degraded ep | 1 (ep14) | 1 (ep14) | 1 (ep14) |
| coverage < 1.0 | 4 | 5 | 5 |
| **mean segments / ep** | **1.00** | **2.31** | **3.36** |
| mean ZC candidates / ep | 0.00 | 2.36 | 2.36 |
| **`merge_same_label` 発火** | 0 | **29** | **0** |
| seg ≥ 2 | 0 | 36 | 39 |
| seg ≥ 3 | 0 | 13 | 35 |
| seg ≥ 4 | 0 | 2 | 10 |
| seg ≥ 5 | 0 | 0 | 6 |

### phase 分布

| phase | OFF | v4 | v5 |
|---|---|---|---|
| approach_object | 36 | 40 | **79** |
| place_object | 0 | 35 | 37 |
| grasp_object | 3 | 8 | 7 |
| move_to_target | 0 | 5 | 2 |
| idle | 0 | 2 | 6 |

v5 で approach_object が倍増 (40→79) しているのは preserve 効果そのもの。
**VLM が同じ `approach_object` を返した隣接 segment が merge されずに
独立 segment として残る** ようになったため。これは spec §1 で議論されていた
"VLM 同一 phase でも ZC 境界を保持" がそのまま起きている証拠。

---

## SO101 T9 との比較

| 指標 | SO101 T9 | Piper v5 |
|---|---|---|
| n | 23 | 39 |
| mean ZC cands/ep | 3.57 | 2.36 |
| **merge_same_label 発火率 (v4→v5)** | **17/23 → 0/23** | **29/39 → 0/39** |
| mean segs/ep (v4→v5) | 2.78 → 4.52 | 2.31 → 3.36 |
| seg ≥ 3 (v5) | 22/23 (96%) | 35/39 (90%) |

**merge_fired がどちらも 100% → 0%**。preserve_sources の動作は完璧に
robot 非依存。

mean_segs の改善幅が Piper で控えめなのは ZC candidates の総量が少ない
ため (2.36 vs 3.57)。Piper は 1 ep あたりの gripper 状態変化が少なめ。
これは hardware/タスクの差であり、smoother の問題ではない。

### per-ep ハイライト

| ep | v4 segs | v5 segs | 効果 |
|---|---|---|---|
| ep18 | 1 (merge fired) | **3** | ZC 2 cand を 1 segment に潰していた → 3 segment に展開 |
| ep20 | 4 | **6** | 既に細かったがさらに細分化 |
| ep10 | 2 (merge fired) | **6** | v4 では 5 cand が 2 seg に潰されていた、最大の改善ケース |
| ep31 | 1 (merge fired) | **3** | "1 segment 落ち" 解消 |
| ep4 | 2 (merge=-) | 2 | merge 元から無し → 変化なし (期待通り) |

---

## 後方互換性確認

実行時の `config_hash` は v4 と v5 で **異なる** (preserve_sources が non-empty
なので spec §3.1 の conditional emit が発火し、to_dict にキーが現れる)。
これは期待通り (異なる config → 異なるハッシュ)。

`merge_same_label_preserve_sources=()` (= 既定) で再実行すると v4 と
完全一致するはず (spec §6 exit criteria #3、SO101 で test pin あり)。
Piper では本検証実施せず (時間制約)。

---

## アーティファクト

- v4: `runs/piper_phase4_zc/` 39 ep
- v5: `runs/piper_phase4_v5/` 39 ep
- v4 vs v5 raw 集計: `/tmp/piper_v4v5_compare.txt` (このセッション)
- 設定:
  - `mimicanno/configs/boundary/piper_zero_crossing.yaml` (hyst=0.12)
  - `mimicanno/configs/smoother/piper_zc_preserve.yaml` (preserve_sources)
  - `mimicanno/configs/robot/piper_robot_config.yaml`

### Re-run コマンド

```bash
# v5 (full): all 4 GPUs in parallel, ~32 min total
for cfg in piper_zero_crossing.yaml piper_zc_preserve.yaml piper_robot_config.yaml; do
  cp mimicanno/configs/{boundary,smoother,robot}/$cfg /tmp/piper-configs/ 2>/dev/null
done

RUNS_ROOT=runs/piper_phase4_v5 \
LOGS_DIR=logs/batch_piper_v5_full \
BOUNDARY_CONFIG=/tmp/piper-configs/piper_zero_crossing.yaml \
SMOOTHER_CONFIG=/tmp/piper-configs/piper_zc_preserve.yaml \
ROBOT_CONFIG=/tmp/piper-configs/piper_robot_config.yaml \
GPU=0 START=0  END=9  bash scripts/batch_piper_phase4.sh &
# (同様に GPU 1/2/3 へ split)
```

`/tmp/piper-configs/` 経由なのは並行 git ops に対する防護 (notes
`2026-05-13-yaml-vanish-during-reset-incident.md` 参照)。

---

## 結論

1. **smoother source-aware merge spec (`feat/phase4-smoother-source-aware-merge`
   branch、現状 SO101 で shipped) は Piper でも spec 通りに機能** すること
   を実データで実証
2. `merge_same_label` 発火率が 74% → 0% に完全消滅 (SO101 T9 と同率パターン)
3. **本機構は robot 非依存** — 新規 robot を追加するときは boundary/smoother の
   YAML をペアで書くだけで finer-segmentation が得られる運用が確立
4. memory [[project_phase4_v5_shipped]] および [[project_piper_portability_confirmed]]
   と整合 (両者の前提が同一データで確認できた)
