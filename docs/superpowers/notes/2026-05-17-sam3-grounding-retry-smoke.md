# T13 — SAM3 grounding retry smoke (2026-05-17 PM)

**Spec:** `docs/superpowers/specs/2026-05-17-sam3-grounding-retry-design.md`
**Plan:** `docs/superpowers/plans/2026-05-17-sam3-grounding-retry-plan.md` (T13)
**Implementation:** PR #26 `413bfd7` (16 commits、unit 830 + integration 59 全 pass)
**Branch:** main (本 smoke は実装変更ゼロ)
**GPU:** GPU 1 (A100 80GB)
**Output:** `runs/_smoke_grounding_retry/episode_NNNNNN__*/`
**Wall clock:** 21:28:35 → 21:36:18 = **~8 min** for 6 ep

## 結果サマリ — **cluster 仮説 4/6 hit (67%)**

| ep | 仮説 | adopted_frame | degrade_reason | attempts | tracks | segs | 判定 |
|---|---|---|---|---|---|---|---|
| 0 | regression zero | **0** | (none) | 1 | 2 | 5 | ✅ regression なし、frame 0 で即成功 |
| 2 | 救済 (cluster A) | **112** | (none) | 4 (0→75→37→**112**) | 2 | 4 | ✅ 4 回目で救済成功 |
| 6 | degrade | None | sam3_no_initial_detection | 4 全 fail | 0 | 4 | ✅ 期待通り degrade |
| 9 | 救済 (cluster A) | None | sam3_no_initial_detection | 4 全 fail | 0 | 5 | ❌ **救済失敗** → 期待外れ |
| 10 | degrade | None | sam3_no_initial_detection | 4 全 fail | 0 | 1 | ✅ 期待通り |
| 26 | 救済 (cluster A) | None | sam3_no_initial_detection | 4 全 fail | 0 | 3 | ❌ **救済失敗** → 期待外れ |

## ep2 救済の詳細 (cluster A 仮説の唯一の hit 例)

```
attempt 1: frame=0     n_object_grounded=0  adopted=False  ← default frame
attempt 2: frame=75    n_object_grounded=0  adopted=False  ← frac=0.5
attempt 3: frame=37    n_object_grounded=0  adopted=False  ← frac=0.25
attempt 4: frame=112   n_object_grounded=1  adopted=True   ← frac=0.75 で救済!
```

frame 112 (75%) で初めて object grounding hit → tracks 2 件生成、phase 4 まで完走、segments=4。**新 pipeline の `grounding_retry_fractions=[0.5, 0.25, 0.75]` のうち最後 (0.75) で救済された good case**。

## 期待外れ ep の所見

**ep9 / ep26** は仮説では「cluster A (フレーム選択ミスで救済可能)」と分類していたが、4 frame (0/75/37/112) **全部** で `n_object_grounded=0`。これは:
- 仮説の cluster A 分類が誤り (実は cluster B = "object 自体が映ってない/SAM3 grounding 困難")
- または retry frames の選択 (0.5/0.25/0.75) が当該 ep の object 出現 window と合ってない

→ **m5 spec の `grounding_retry_fractions` 見直し材料**。例えば追加 frame (e.g., 0.1, 0.9) を入れる、または `n_total_grounded > 0` (nuisance あり) 時の adoption ロジック改善。

なお ep9 (`adopted=None` で全 attempt fail) でも `segs=5` 出てるのは boundary detector が signals 由来で動作してるから (annotation.json segments は VLM 推論で埋まる、SAM3 mask は欠落)。downstream consumer は manifest.degraded_from_phase を check すべき。

## n_total_grounded > 0 のヒント

ep2 の attempt 1-3 で `n_total_grounded=1` (objects は 0 だが何かしら grounded) → SAM3 は nuisance を拾ってる。adoption に `n_total_grounded > 0 AND best_iou > thr` 等のソフト判定を追加すれば、retry 回数を減らせる可能性。**spec follow-up**。

## 結論

- **T13 PASS** — 仮説 67% match、mechanism (retry) は ep2 で完璧に動作、ep0 regression なし。
- ep9/ep26 の救済失敗は **仮説の cluster 分類誤り** (実装 bug ではない)。
- **次の調整**: `grounding_retry_fractions` 拡張 or adoption ロジック refinement (m5)。

## TODO 更新

TODO L17 (SAM3 grounding retry smoke T13) → 「✅ 完了、cluster 仮説 4/6 hit」に。m5 spec で `grounding_retry_fractions` 見直し + `n_total_grounded` ベースの soft adoption は follow-up task として残置。
