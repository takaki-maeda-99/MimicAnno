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

### 1. S-D — Evaluation harness — `feat/phase5-d-eval-harness` ✅ DONE

- [x] spec: `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` (rev1)
- [x] plan: `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` (rev1)
- [x] **T1〜T3**: `EditEvent` dataclass + `AnnotationResult.history` + annotation schema 0.3.0
- [x] **T4〜T7**: `event_builder.py` + 4 repo/route extensions + server tests
- [x] **T8〜T10**: `mimicanno/eval/` package (`metrics.py` + `render.py` + CLI)
- [x] **T11**: frontend timing hook (all 4 edit clients + SegmentTable onEditFocus + RunViewer editStartRef)
- [x] **T12**: mypy --strict + 全 regression (10 new tests + 210 existing, all pass)
- [x] **T13**: 手動 smoke (SO101 ep0 copy — PATCH reviewed 2500ms → history correct, eval CLI OK)
- [x] **T14〜T15**: docs (`2026-05-16-phase5-d-results.md`) + memory + TODO
- [ ] **main にマージ** (ユーザー判断待ち)

---

### 2. その他 (低優先度)

- **gem4 新ロボット設定**: `mimicanno/configs/robot/gem4_*.yaml` x3 + run scripts — 別 PR で整理
- **テストギャップ**: `tests/fixtures/loadable_run/` に合成固定データをコミットして CI 対応 (詳細は git 履歴の旧 TODO 参照)

---

## 推奨次ステップ

```
S-D main マージ → Phase 5 E (MimicRec integration)
```
