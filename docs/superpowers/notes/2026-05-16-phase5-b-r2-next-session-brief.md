# Phase 5 B r2 — 次セッションへの指示書

Date: 2026-05-16
Worktree: `/misc/dl00/gayagaya/MimicAnno-phase5b-r2`
Branch: `feat/phase5-b-r2-boundary-drag` (origin/main `9f1dd06` から分岐)

---

## このセッションで何ができていて、何が残っているか

**Done (未 commit、3 ファイル):**
- `docs/superpowers/specs/2026-05-15-phase5-b-r2-boundary-drag-design.md`
- `docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md`
- `docs/superpowers/notes/2026-05-16-phase5-b-r2-spec-plan-handoff.md`

**Not done:** 実装は 1 行も書いていない。plan T0 (audit) から開始。

---

## 着手手順 (worktree 内で Claude を起動した直後にやること)

1. **branch 衛生確認** (memory `feedback_handoff_conflict_check`):
   ```
   git -C /misc/dl00/gayagaya/MimicAnno-phase5b-r2 branch -v
   git -C /misc/dl00/gayagaya/MimicAnno-phase5b-r2 log --oneline -10
   git -C /misc/dl00/gayagaya/MimicAnno-phase5b-r2 status
   ```
   HEAD が `feat/phase5-b-r2-boundary-drag` で、上記 3 ファイルが
   untracked であることを確認。

2. **未 commit の 3 ファイルを 1 commit にまとめる** (spec/plan/handoff は
   セット):
   ```
   git add docs/superpowers/specs/2026-05-15-phase5-b-r2-boundary-drag-design.md
   git add docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md
   git add docs/superpowers/notes/2026-05-16-phase5-b-r2-spec-plan-handoff.md
   git commit -m "docs(phase5-b-r2): spec + plan + handoff for boundary drag edit"
   ```
   本 brief 自体 (next-session-brief.md) は別 commit、または最後の
   results note とまとめて。

3. **spec → plan の流れを読む** (この順):
   - spec: `docs/superpowers/specs/2026-05-15-phase5-b-r2-boundary-drag-design.md`
   - plan: `docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md`
   - 既に独立レビュー 2 周を反映済み。**もう一度レビューする必要は無い**

4. **plan T0 (audit) を実行**:
   - `tests/server/conftest.py` で `real_so101_run` (またはそれ相当の
     SO101 ep0 rsync fixture) の有無を grep
   - `frontend/src/__tests__/` で r1 が `vi.fn` ベースか `msw` ベースかを
     確認 (一番近い既存テストファイルを開いて読む)
   - 結果を plan §3 の T11 / T14 セクションに 1–2 行追記して commit

5. **以降は plan の T1 → T18 を順に**。各 task は「失敗テスト → 実装 →
   green」の TDD で、1 task = 1 commit。

---

## 進めかたの規約 (本プロジェクトの慣習)

- **uv 経由で実行**: `uv run pytest tests/ -q` / `uv run --extra server mypy mimicanno/server` / `uv run mimicanno serve`
- **フロントは pnpm**: `cd frontend && pnpm test`
- **autonomy window は終了済み** (memory `phase-5-sub-project-status-2026-05-14`)。
  以下は **都度ユーザー確認**:
  - `runs/so101_phase4_v5/` 配下を破壊する操作 (drag smoke は worktree
    内の tmp copy で行う、本物は読み取り専用扱い)
  - 共有インフラ / `~/MimicRec/datasets/` への書き込み
  - `git push --force` / 大規模 reset
- **可逆なローカル作業 (新 file 作成 / test 追加 / TDD コミット) は
  逐次自走 OK**
- **既存挙動を絶対に壊さない**: r1 PATCH route / read endpoint / 既存
  1170+ tests は green を維持

---

## ゴール再掲 (spec §6 / plan §0)

1. PATCH `/api/runs/<name>/boundaries/<id>` happy path round-trip
   against `runs/so101_phase4_v5/`
2. +22 新規テスト全 green (17 server unit + 2 integration + 3 frontend)
3. status-code matrix 完備: 200 / 400 ×4 / 404 / 405 / 412 / 415 / 428
4. uvicorn-in-process race test 「正確に [200, 412]」
5. r1 / r2 / auto-pipeline hash 3 空間 disjoint pin
6. 既存 1170+ tests green
7. mypy --strict clean over `mimicanno/server`
8. Frontend smoke: 内側境界 3 本を 5 frame ずつ drag → reload で persist
9. JSON schema 変更なし
10. notes `2026-05-16-phase5-b-r2-results.md` + memory 更新

---

## 完了 (hand-back) 時にやること

1. branch を origin に push、PR を上げる (`gh pr create`)
2. `docs/superpowers/notes/2026-05-16-phase5-b-r2-results.md` に
   curl 結果 + UI スクショ + 観察された挙動を貼る
3. memory に `project_phase5_b_r2_shipped.md` 新規、
   `phase-5-sub-project-status-2026-05-14` の B 行を r2 SHIPPED に更新
4. ユーザーへ「ship した / 何が確認できた / 何が open question か」を
   報告

---

## 困ったら見る場所

- r1 の同等実装: `mimicanno/server/edit_repo.py`, `mimicanno/server/routes.py` の PATCH `/segments/`、`tests/server/test_routes_patch.py`、`tests/server/test_patch_concurrent.py`
- r1 frontend の同等実装: `frontend/src/lib/editClient.ts` (相当)、`frontend/src/components/RunViewer.tsx` 内の phase `<select>` 経路、`frontend/src/__tests__/`
- r1 spec / plan / results: `docs/superpowers/specs/2026-05-13-phase5-B-edit-relabel-design.md`, `docs/superpowers/plans/2026-05-13-phase5-B-edit-relabel-plan.md`, smoke 結果は `docs/superpowers/plans/2026-05-14-phase5-b-r1-ui-smoke-plan.md`

---

## 並列の他 worktree との衝突可能性

`TODO.md:84-116` 参照:
- `MimicAnno-hand-viewer` (`feat/hand-viewer`) — 触る場所が
  `frontend/src/lib/handsClient.ts` + `HandViewer.tsx` + `RunList.tsx`、
  r2 が触る `RunViewer.tsx` / `TimelineRuler.tsx` (新規) と直接衝突は
  しないが、`RunList.tsx` は両方 touch する可能性あり。マージ時に
  注意
- `MimicAnno-phase5d` (`feat/phase5-d-eval-harness`) — B writable API
  に依存するので r2 マージ後。直接衝突なし
