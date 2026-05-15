# TODO (2026-05-16 現在)

## 完了済み ✅

| ストリーム | 内容 | コミット |
|---|---|---|
| Hand pipeline / HV | pinch distance、hand viewer T1-T5+axes、regen | main 済 |
| S-RS | run-set switcher UI ドロップダウン | PR #9 (main) |
| S-B2 | 境界ドラッグ PATCH + BoundaryDragLayer | `9c25b87` (main) |
| S-UI | ダークテーマ + HandScrubBar + HandViewer サイドパネル | `68aafcf` (main) |

---

## 残タスク

### 1. origin/main push

- [ ] `git push origin main` — local main が origin より ahead

---

### 2. S-B3 — reviewed 単独トグル — `feat/phase5-b-r3-reviewed-toggle`

実装済み・**未コミット** (working tree に uncommitted 状態):

- [x] spec: `docs/superpowers/specs/2026-05-16-phase5-b-r3-reviewed-toggle-design.md`
- [x] plan: `docs/superpowers/plans/2026-05-16-phase5-b-r3-reviewed-toggle-plan.md`
- [x] backend: `mimicanno/server/reviewed_repo.py`
- [x] backend route: `mimicanno/server/routes.py` 変更済
- [x] frontend: `frontend/src/lib/reviewedClient.ts`
- [x] frontend: `frontend/src/components/RunViewer.tsx`、`SegmentTable.tsx` 変更済
- [x] tests: `tests/server/test_routes_patch_reviewed.py`、`frontend/src/__tests__/reviewed-toggle.test.tsx`
- [ ] **コミット + テスト確認**
- [ ] **main にマージ**

---

### 3. S-D — Evaluation harness — `feat/phase5-d-eval-harness`

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

### 4. その他 (低優先度)

- **gem4 新ロボット設定**: `mimicanno/configs/robot/gem4_*.yaml` x3 + run scripts — B-r3 に同梱するか別 PR か判断
- **テストギャップ**: `tests/fixtures/loadable_run/` に合成固定データをコミットして CI 対応

---

## 推奨マージ順

```
origin/main push → S-B3 commit+merge → S-D impl+merge
```
