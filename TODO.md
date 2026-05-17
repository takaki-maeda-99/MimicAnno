# TODO (2026-05-17 14:35 現在)

**Autonomy window: CLOSED 2026-05-16** — Phase 5 D shipped + SO101 v5 real-data smoke (17 events × 4 edit types) green。次窓を開ける場合はユーザー判断。

**Phase 5 D r2 全部完了 (2026-05-17)**: frontend (merge `b5050cc`) + backend (merge `a7d5283`) どちらも `origin/main` 反映済。本セッション全行動の summary は `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`。

---

## 残タスク

| 優先 | ID | 内容 | 状態・備考 |
|---|---|---|---|
| 低 | **Phase 5 E (そのうち)** | (A) `mimicanno export-undo` CLI、(B) integration contract 凍結 docs、(C) read-only Python client `mimicanno.client` | MimicRec 配置待ち。本リポ完結部分のみ着手可 |
| ✅ | **Phase 6 core (eval v2)** | true planner_agreement metric + confusion matrix + by_source/confidence/phase + schema 0.4.0 | branch `worktree-phase6-eval-v2` (origin push 済、PR TBD)。詳細: `docs/superpowers/notes/2026-05-17-phase6-eval-v2-results.md`。残: Phase 6+ A (auth) / B (Replay UI + boundary timing) / C (multi-reviewer) は別 spec |
| 低 | **G7 full-ep 再走** | G8 `--limit` 無しで全フレーム depth 生成 → HAMER 再走で `cam_t` metric anchoring 確認 | 初回 PARTIAL の follow-up。優先度低 |
| 低 | **`_vlm_dumps` schema 変化対応** | per-call dir 構造化されたので SFT loader ([[project_gemma_ft_pipeline]]) が読めるか確認 | G6 で判明 |
| 中 | **`run_26B_so101.sh` config gap** | `--boundary-config so101_zero_crossing.yaml` + `--smoother-config so101_zc_preserve.yaml` を追加 → 26B vs 4B annotation richness fair compare | G1 26B SO101 再走で boundaries=0 → segments=1 idle が判明 (planner 品質ではなく config gap)。詳細: `docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md` |
| 中 | **gem4 26B chain 結果検証** | pick_up_bottle / replace_the_cookie / open_the_jar (PID 82185, GPU 1) 完了後に 4B (`runs/gem4_*_4B/`) と比較 | 実行中。`scripts/batch_annotate.py` 側も boundary-config gap がないか要確認 |
| 低 | gem4 設定整理 | `mimicanno/configs/robot/gem4_*.yaml` × 3 の clean-up | docs/別 PR |

### 後始末

- `/misc/dl00/gayagaya/MimicAnno-phase5d/frontend/node_modules/` — git 認識外、`rm -rf` でいつでも除去可
- `mimicanno serve` (PID 1063745) — so101_phase4_v5 配信で稼働継続中、別件なので触らない

---

## 未マージ PR 待ち

| branch | 内容 | 状態 |
|---|---|---|
| `test/loadable-run-fixture` | `tests/fixtures/loadable_run/` 凍結 + conftest 切替 (5 commit、224 passed) | origin push 済、Opus レビュー APPROVED (ブラウザで作成: <https://github.com/takaki-maeda-99/MimicAnno/pull/new/test/loadable-run-fixture>)。Title `test(fixtures): freeze loadable_run for CI (no real-data dependency)`、body 雛形は `docs/superpowers/plans/2026-05-17-loadable-run-fixture-plan.md` の Summary/Exit criteria 抜粋で十分 |
| `docs/g-smoke-results` | G6/G7/G8 GPU smoke 結果 (3 commit + TODO 更新) | origin push 済、PR 本文準備済 (ブラウザで作成: <https://github.com/takaki-maeda-99/MimicAnno/pull/new/docs/g-smoke-results>) |
| `docs/g4-gem4-smoke` | G4 gem4 smoke 結果 (commit `5f8faa2`) | 別セッション、status 確認要 |

---

## 完了済み ✅

| ストリーム | 内容 | コミット / PR |
|---|---|---|
| S-RS | run-set switcher UI ドロップダウン | PR #9 |
| S-B2 | 境界ドラッグ PATCH + BoundaryDragLayer | `9c25b87` |
| S-UI | ダークテーマ + HandScrubBar + HandViewer サイドパネル | `68aafcf` |
| S-HG | HandSignalGraph (xyz cam_t 時系列) | `3ae28bb` |
| S-B3 | reviewed 単独トグル | `14eb192` |
| S-D | Phase 5 D EditEvent history + `mimicanno eval` CLI | `3d8bb34` |
| fix-boundary-route | `patch_boundary_route` Depends 修正 | PR #10 (`679fbf9`) |
| test-fixtures | `tests/fixtures/loadable_run/` 凍結 | `cf05727`/`59b1151`/`8292811` |
| **D r2 frontend timing** | **3 regression 修正 (Date.now → performance.now / cross-input Map ref / focusout discard) + 8 new tests** | **merge `b5050cc` (main)** |
| **D r2 backend hardening** (2026-05-17) | **B1 schema_version PATCH upgrade / B2 history order test / B3 `label_agreement`→`human_touched_fraction` rename+脚注 / B4 `client_edit_duration_ms` 600,000ms cap。15 new tests / 252 passing / mypy --strict clean** | **merge `a7d5283` (main)** |
| **G1** | batch_annotate 4B smoke (SAM3 runtime 共有 + `BATCH_RUNS_ROOT`) | `3b6899e` etc. (origin/main 済) |
| **G2** | Phase 5 D SO101 v5 UI smoke (17 events × 4 edit types) | autonomy exit 内 |
| **G3** | autonomy exit e2e sanity (SO101 3 ep) | `runs/g3_smoke_20260516_2252/` |
| **G3 再走** (2026-05-17) | 同条件再現性 PASS、wall 4.5 min (前回 5.5 min)、planner 出力 deterministic 一致 | `runs/g3_smoke_20260517_1353/` / note `2026-05-17-g3-rerun-results.md` |
| **G1 26B SO101** (2026-05-17) | A100 80GB で 26B mechanics PASS (VRAM 52 GiB)、2 ep × 7 min。planner 品質は 4B より良い兆候 (bottle→targets, gripper 具体化) | `/tmp/g1_smoke_26b/` / note `2026-05-17-g1-26b-so101-smoke-results.md` |
| **G6** | Gemma 4B planner regression (`docs/g-smoke-results`) | `6ca0a43` |
| **G7** 🟡 | Hand+HAMER pipeline mechanics PASS、cam_t anchoring 未検証 (`docs/g-smoke-results`) | `633ca13` |
| **G8** | UniDAC precompute_depth (`docs/g-smoke-results`) | `158b647` |

結果 note は `docs/superpowers/notes/2026-05-17-{g1,g6,g7,g8}-*-smoke-results.md` 等。各 G の詳細・surprise はそれぞれの note 参照。
**本セッション D r2 全完了サマリー**: `docs/superpowers/notes/2026-05-17-session-summary-d-r2-complete.md`

---

## 推奨次ステップ

1. `docs/g-smoke-results` を PR 作成 → main マージ (`test/loadable-run-fixture` も同様)
2. ~~D r2 backend~~ ✅ DONE (`a7d5283` merge)
3. `run_26B_so101.sh` の config gap 修正 (中優先、26B vs 4B fair compare に必要)
4. Phase 5 E は MimicRec 配置待ちで保留 (低優先、autonomy 不要範囲のみ MimicAnno 単独で進められる)
