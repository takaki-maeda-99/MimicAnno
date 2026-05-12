# SO101 Phase 4 v5 (source-aware merge) — T9 results

Date: 2026-05-12
Spec: [`../specs/2026-05-12-phase4-smoother-source-aware-merge-design.md`](../specs/2026-05-12-phase4-smoother-source-aware-merge-design.md)
Plan: [`../plans/2026-05-12-phase4-smoother-source-aware-merge-plan.md`](../plans/2026-05-12-phase4-smoother-source-aware-merge-plan.md)
Predecessor: [`2026-05-11-so101-phase4-v4-results.md`](./2026-05-11-so101-phase4-v4-results.md)

## TL;DR

source-aware `_merge_same_label` の導入で SO101 23 ep 全件 で
**mean segs/ep 2.78 → 4.52**、**`merge_same_label` 発火 17/23 → 0/23**。
spec §6 exit criteria を全て満たし大幅に超達成。

## Run setup

- batch: `scripts/batch_so101_phase4_v5.sh` (T8a 透過 `SMOOTHER_CONFIG` 経由)
- boundary YAML: `mimicanno/configs/boundary/so101_zero_crossing.yaml` (v4 同一)
- smoother YAML: `mimicanno/configs/smoother/so101_zc_preserve.yaml`
  (`merge_same_label_preserve_sources: [gripper_zero_crossing]`)
- output: `runs/so101_phase4_v5/`
- 対象: 23 ep (0-10 + 21-32)
- 実行: GPU 0 (ep 0-10) + GPU 1 (ep 21-22) + GPU 3 (ep 23-32)、並列。
  GPU 1 は途中 Piper batch とのメモリ競合で ep23+ が OOM → GPU 3 にリダイレクト。
- 所要: スモーク 1m35s/ep、本走 ~1.5-2 min/ep。

## Smoke (ep0) 先行確認

| 指標 | v4 ep0 | v5 smoke ep0 |
|---|---|---|
| segments | 2 | **5** |
| `merge_same_label` 発火 | ✓ | **×** |
| `gripper_zero_crossing` 保持境界 | 0/4 | **4/4** |

→ preserve が単一 ep 完全機能。本走 GO サイン。

## Per-episode (v4 vs v5)

| ep | v4_segs | v5_segs | v4_merge_fired | v5_merge_fired | ZC cands | Δsegs |
|---:|---:|---:|:---:|:---:|---:|---:|
|  0 | 2 | 5 | ✓ | × | 4 | +3 |
|  1 | 3 | 4 | ✓ | × | 3 | +1 |
|  2 | 4 | 4 | × | × | 3 |  0 |
|  3 | 5 | 5 | × | × | 4 |  0 |
|  4 | 3 | 4 | ✓ | × | 3 | +1 |
|  5 | 4 | 5 | ✓ | × | 4 | +1 |
|  6 | 3 | 4 | ✓ | × | 3 | +1 |
|  7 | 2 | 5 | ✓ | × | 4 | +3 |
|  8 | 2 | 5 | ✓ | × | 4 | +3 |
|  9 | 5 | 5 | × | × | 4 |  0 |
| 10 | 1 | 1 | × | × | 0 |  0 |
| 21 | 4 | 5 | ✓ | × | 4 | +1 |
| 22 | 1 | 5 | ✓ | × | 4 | +4 |
| 23 | 2 | 3 | ✓ | × | 2 | +1 |
| 24 | 2 | 6 | ✓ | × | 5 | +4 |
| 25 | 2 | 5 | ✓ | × | 4 | +3 |
| 26 | 3 | 3 | × | × | 2 |  0 |
| 27 | 3 | 5 | ✓ | × | 4 | +2 |
| 28 | 2 | 5 | ✓ | × | 4 | +3 |
| 29 | 2 | 5 | ✓ | × | 5 | +3 |
| 30 | 2 | 5 | ✓ | × | 4 | +3 |
| 31 | 5 | 5 | × | × | 4 |  0 |
| 32 | 2 | 5 | ✓ | × | 4 | +3 |

## Aggregate

| 指標 | v4 | v5 | 目標 (spec §5.3) | 判定 |
|---|---|---|---|---|
| n eps | 23 | 23 | — | — |
| mean ZC cands/ep | 3.57 | **3.57** | 3.57 (不変) | ✅ 完全一致 |
| **mean segs/ep** | 2.78 | **4.52** | ≥ 4.0 | ✅ 達 (+1.74) |
| **seg ≥ 3 ep** | 11/23 | **22/23** | ≥ 18/23 | ✅ 大幅超 |
| seg ≥ 5 ep (参考) | 3/23 | **16/23** | — | — |
| **`merge_same_label` 発火 ep** | 17/23 | **0/23** | ≤ 5/23 | ✅ 完全消滅 |
| ep10 が 1 segment (cands=0) | ✓ | ✓ | ✓ | ✅ |
| ep31 (5 seg) 維持 | ✓ | ✓ | ✓ | ✅ |

唯一 seg<3 の ep23 (3segs ちょうど未満ではないが) → 実際は **ep23 = 3 segs**、
全 ep が `seg ≥ 3` の領域 (ep10 を除く)。ep10 は ZC cands=0 のため
保守的に 1 segment のまま (期待通り、ベースの VLM 出力が単一相)。

## Exit criteria (spec §6)

1. ✅ 全単体テスト green (798 passed in 24s including 10 preserve tests + 12 config tests)
2. ✅ T9 で mean segs/ep ≥ 4.0 (実績 4.52)、seg≥3 が 18/23 ep 以上 (実績 22/23)
3. ✅ `merge_same_label_preserve_sources=()` (既定) で T8 v4 を再実行不要 ―
   algebraic 等価性で証明済 (`test_smoother_config.py::test_preserve_sources_default_canonical_bytes_pinned`)
4. ✅ 同上
5. ✅ 本ノート

## Viterbi (Op 3) 相互作用 (spec §7)

`merge_same_label` の発火が **全 ep で 0 件**。よって Op 3 後の `_merge_same_label`
follow-up が再 collapse を試みた挙動は **本走では一度も観測されず**。
spec §7 のリスク (Viterbi 後の再 collapse) は preserve がそのまま機能していて
顕在化しなかった。

ただし「Op 3 が phase を変えた」場合の挙動は今回 collapse 経路が起動しないので
直接観察できていない。`tests/unit/test_smoother_preserve_sources.py::test_preserve_after_viterbi_relabel`
で unit-level に検証済。

## Source 名 typo 警告 (spec §3.5)

batch 中 WARNING 出力なし → `gripper_zero_crossing` は全 ep で実際に観測されており、
typo / mismatch なし。

## Phase 5 sub-project autonomy 進捗

sub-project: Phase 4 smoother source-aware merge → **完了**。
exit criteria 全達のため次サブプロジェクト (Phase 5 A. Persistence backend)
に着手可能 (autonomy window 継続)。
