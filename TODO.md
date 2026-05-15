# TODO (2026-05-16 現在)

## 完了済み ✅

| ストリーム | 内容 | コミット |
|---|---|---|
| Hand pipeline / HV | pinch distance、hand viewer T1-T5+axes、regen | main 済 |
| S-RS | run-set switcher UI ドロップダウン | PR #9 (main) |
| S-B2 | 境界ドラッグ PATCH + BoundaryDragLayer | `9c25b87` (main) |
| S-UI | ダークテーマ + HandScrubBar + HandViewer サイドパネル | `68aafcf` (main) |
| S-HG | HandSignalGraph — xyz cam_t 時系列グラフ + 外れ値ロバストレンジ | `3ae28bb` (main) |
| S-B3 | reviewed 単独トグル — backend + frontend + tests | `14eb192` (main) |
| origin push | 17 コミットを `origin/main` に push 済 | `041acdd..3a75cca` |

---

## 残タスク

### 1. S-D — Evaluation harness — `feat/phase5-d-eval-harness`

spec/plan 完成、実装ゼロ:

- [x] spec: `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` (rev1)
- [x] plan: `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` (rev1)
- [ ] **T1〜T3**: `EditEvent` dataclass + `AnnotationResult.history` + schema v2.0 bump
- [ ] **T4〜T7**: `_build_event` + `apply_edit` 拡張 + server tests
- [ ] **T8〜T10**: `mimicanno/eval/` package (`metrics.py` + `render.py` + CLI)
- [ ] **T11**: frontend — phase `<select>` focusin/change 計測 hook
- [ ] **T12**: mypy --strict + 全 regression
- [ ] **T13**: 手動 smoke (SO101 v5)
- [ ] **T14〜T15**: docs + memory
- [ ] **main にマージ**

---

### 2. その他 (低優先度)

- **gem4 新ロボット設定**: `mimicanno/configs/robot/gem4_*.yaml` x3 + run scripts — 別 PR で整理
- **テストギャップ**: `tests/fixtures/loadable_run/` に合成固定データをコミットして CI 対応 (詳細は git 履歴の旧 TODO 参照)

---

## 推奨次ステップ

```
S-D impl+merge (Phase 5 D)
```
