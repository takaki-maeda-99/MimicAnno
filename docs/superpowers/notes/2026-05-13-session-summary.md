# セッション作業まとめ (2026-05-12 → 2026-05-13)

休憩前の引き継ぎノート。並行 Piper セッションとの競合があるため、再開時は
必ず [[feedback_handoff_conflict_check]] に従って branch/handoff note を
確認すること。

---

## 完了したもの

### 1. Phase 4 smoother source-aware merge sub-project ✅ SHIPPED

**ブランチ**: `feat/phase4-smoother-source-aware-merge` (commit `e4f658e`)

**実装**: `SmootherConfig.merge_same_label_preserve_sources` で ZC 由来 boundary を Op 1 merge から保護。

**SO101 23 ep T9 結果**:
| 指標 | v4 | v5 | 目標 |
|---|---|---|---|
| mean segs/ep | 2.78 | **4.52** | ≥ 4.0 |
| seg ≥ 3 | 11/23 | **22/23** | ≥ 18/23 |
| merge_same_label 発火 | 17/23 | **0/23** | ≤ 5/23 |

spec exit criteria 全達。詳細: `docs/superpowers/notes/2026-05-12-so101-phase4-v5-results.md`
memory: [[project_phase4_v5_shipped]]

### 2. Phase 5 A persistence backend spec + plan ✅ commit 済 (`525e041`)

- spec: `docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md`
- plan: `docs/superpowers/plans/2026-05-12-phase5-A-persistence-backend-plan.md`
- どちらも general-purpose サブエージェント独立レビューを 1 回ずつ通して反映済み
- スコープ: read-only ファーストリリース (GET /api/runs/* + /healthz)、書き込みは B sub-project へ deferral

### 3. Phase 5 A T1-T8 実装 ✅ commit 済 (`0ec9c90`, `79c2796`)

- T1: `[server]` extra (fastapi+uvicorn) + httpx dev + mypy overrides
- T2: `mimicanno/server/errors.py` — `{error,message}` envelope + 汎用 Exception handler (stack non-leak)
- T2.5: `tests/server/conftest.py` 共有 fixtures (tmp_runs_root, free_port, etc)
- T3: `mimicanno/server/runs_repo.py` — allow-list 5 ファイル、canonical_name regex、traversal guard、100ms × 3 retry
- T4: `mimicanno/server/routes.py` — 2 GET + /healthz + ETag (manifest のみ) + FileResponse streaming
- T5: `mimicanno/server/app.py` — FastAPI factory + CORS middleware
- T6: `mimicanno/cli.py` に `mimicanno serve` 追加
- T7: 並行 publish race テスト
- T8: mypy --strict clean + 全 regression green (**1070 passed, 6 skipped, 0 failed**)

### 4. ドキュメントとメモリ更新

- `docs/superpowers/notes/2026-05-12-smoother-source-aware-merge-status.md` (現状サマリ、Piper A/B 結果も追記済)
- `docs/superpowers/notes/2026-05-12-so101-phase4-v5-results.md` (T9 results)
- `docs/superpowers/notes/2026-05-13-server-on-piper-branch-incident.md` (本セッションでのインシデント)
- memory:
  - [[project_phase4_v5_shipped]] 新規
  - [[project_phase5_status]] 新規 (A/B/D/E status、A は今 IN-PROGRESS)
  - [[feedback_plan_before_implement]] 新規 (autonomy でも計画レビュー必須)
  - [[feedback_handoff_conflict_check]] 新規 (並行作業との衝突回避)
  - [[project_smoother_bottleneck]] を「解決済」表記に更新

---

## 残タスク (Phase 5 A、再開時に着手)

| # | タスク | 状態 | 注記 |
|---|---|---|---|
| T9 | README + `mimicanno/server/README.md` | pending | server セクションを既存 README に追記、内部開発者ドキュメントを新規 |
| T10 | 手動 smoke + results note | pending | `runs/so101_phase4_v5/` で serve 起動、curl で各 endpoint、結果を notes へ |
| T11 | memory 更新 (A SHIPPED 化) | pending | `project_phase5_status.md` の A を SHIPPED に、新 `project_phase5_a_shipped.md` |

---

## 並行セッションの状況

**Piper portability セッション** が同時並行で動いていた:
- `feat/piper-portability` ブランチで `8bb2d4e feat(piper): port MimicAnno pipeline to Agilex Piper dataset`
- LegrandFrederic/Marker_pickup_piper 39 ep で adapter v0.2.0 検証
- `merge_same_label` 発火率 74% (29/39) で SO101 (17/23 = 74%) と完全一致 → smoother bottleneck が robot 非依存と実証
- handoff note `2026-05-13-phase5-a-server-wip-handoff.md` を立てて私の WIP を保護

---

## インシデント (本セッション中、resolved)

### 1. server commit が Piper branch に誤配置 → 修復済
詳細: `docs/superpowers/notes/2026-05-13-server-on-piper-branch-incident.md`
- 原因: 並行セッションが HEAD を Piper ブランチに動かしたのを検知せず commit
- 修復: 並行セッションが Plan A (cherry-pick → smoother branch、Piper を 8bb2d4e に reset) を実行
- 現状: 正常 (`79c2796` が smoother branch に乗っている)

### 2. reset --hard 中の YAML 一瞬消失 → batch 16 ep FAIL → 再走可能
詳細: `docs/superpowers/notes/2026-05-13-yaml-vanish-during-reset-incident.md` (Piper セッション報告)

---

## 再開時のチェックリスト

休憩から戻ったら **必ず順番に**:

1. `git branch --show-current` — `feat/phase4-smoother-source-aware-merge` にいるか?
   違ったら `git checkout feat/phase4-smoother-source-aware-merge`
2. `git log --oneline -5` — `79c2796` (T2-T8) が見えるか? 見えなければ branch がズレている
3. `ls docs/superpowers/notes/*handoff*.md *wip*.md` で新しい占有マーカーが立っていないか
4. `git status --short` で untracked / modified が何か残っていないか
5. Phase 5 A T9 (README) から再開

---

## 未コミットの作業 (休憩前)

```
?? docs/superpowers/notes/2026-05-13-server-on-piper-branch-incident.md  ← 私が書いた
?? docs/superpowers/notes/2026-05-13-yaml-vanish-during-reset-incident.md ← Piper セッションが書いた
```

両方とも未 commit。次回 commit するときは branch が正しいか必ず確認。

---

## ブランチ俯瞰

```
main (9b062b8)
 │
 ├── feat/phase4-smoother-source-aware-merge (HEAD: 79c2796, [ahead 1 of origin])
 │     ├── e4f658e  Phase 4 smoother source-aware merge sub-project (SHIPPED)
 │     ├── 525e041  Phase 5 A spec + plan
 │     ├── 0ec9c90  Phase 5 A T1 (server extra)
 │     ├── 9a82423  WIP handoff note (Piper session)
 │     └── 79c2796  Phase 5 A T2-T8 (cherry-pick after incident repair)
 │
 └── feat/piper-portability (HEAD: 8bb2d4e)
       └── 8bb2d4e  Piper port + 39 ep validation
```
