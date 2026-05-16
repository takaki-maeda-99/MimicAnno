# Phase 5 — autonomy exit summary (2026-05-16)

## What shipped

| Sub-project | 内容 | Commit |
|---|---|---|
| A. Persistence backend (read-only) | `mimicanno serve` + GET endpoints + 40 tests | (前 session、main 済) |
| A'. Hand Viewer backend | `/api/hands/` + `RunList` リンク | (前 session、main 済) |
| B. Edit UI (r1-r4) | phase relabel / boundary drag / reviewed toggle / labels (verb+object+target+flags) | `9c25b87` (r2) / `14eb192` (r3) / 他 |
| C. Parquet export | `mimicanno export` CLI | (前 session、main 済) |
| RS. Run-set switcher | UI dropdown + `?run_set=` propagation | PR #9 |
| Hand Viewer | T1-T5 + 3-axis overlay | main 済 |
| D. Eval harness | EditEvent + history + `mimicanno eval` + frontend timing | `3d8bb34` |
| Boundary route fix | `patch_boundary_route` missing `Depends(get_effective_root)` | PR #10 `679fbf9` |

## Real-data smoke (G2)

SO101 v5 で実走、Sonnet 4.6 session:
- 4 edit type × 計 17 history events
- `mimicanno eval runs/so101_phase4_v5/` で全 event 集計
- boundary fix (PR #10) が smoke で発見・修正

History 例 (eval CLI 出力から):
- relabel: 1
- boundary: 7
- reviewed: 5
- labels: 4

## 怪しかったところ / D r2 候補

D の adversarial review で出した 6 件 (D r2 で対応):
1. `client_edit_duration_ms` 上限なし → JS Number overflow リスク
2. Frontend `editStartRef` が全 edit type 共有 → cross-input focus で誤計測の可能性
3. `schema_version` の PATCH 経路保持 → 0.2.0 → 0.3.0 bump が cosmetic
4. PATCH-twice history order test 欠落
5. `--out` / `--format both` 未実装 (spec から削除済)
6. `label_agreement` の真の意味 (`label_source="human_edit"` のみカウントは approximation)

Frontend regression (D r2):
- `focusout` 時の t0 discard 未実装 (spec §3.5)
- `Math.max(0, ...)` clock-skew clamp 未実装

その他:
- G3 (autonomy exit smoke) は別フロー、`.venv` torch/CUDA mismatch で停止中、他セッションと .venv 共有
- G1 26B variant は手元 RTX A6000 48GB で VRAM 不足、別ホスト案件

## 未着手

- **Phase 5 E — MimicRec integration** (master spec §10 #38)
  - スコープ: `~/MimicRec/` 側で `save_annotations` swap-out + Replay page が A backend を叩く / 静的 `runs/` を読む
  - autonomy 窓の境界 (「shared infra outside this repo」) に近いので、新セッションで spec から起こす
- D r2 (上記 6 件) — 新 spec で議論

## Open questions for user

1. Phase 5 E に進む場合、新規 autonomy 窓を開くか? 開く場合の抜け条件は?
2. D r2 の優先順位 — `label_agreement` の意味付け修正は重要度高め (eval を実際に使い始める前に直す方が良い)
3. G3 .venv 問題 — 他セッションと調整して torch の固定方針を決めるか

## Autonomy window status

**CLOSED** as of 2026-05-16. 次の autonomy 窓を開けるか / どの spec から始めるかはユーザー判断。
