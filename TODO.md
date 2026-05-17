# TODO (2026-05-17 現在)

**Autonomy window: CLOSED 2026-05-16** — Phase 5 D shipped + SO101 v5 real-data smoke (17 events × 4 edit types) green。次窓を開ける場合はユーザー判断。

---

## 残タスク

| 優先 | ID | 内容 | 状態・備考 |
|---|---|---|---|
| 高 | **D r2 backend** | `label_agreement` リネーム / PATCH-route `schema_version` upgrade 漏れ / PATCH-twice history order test / `client_edit_duration_ms` server-side cap | spec 未着手。詳細: `docs/superpowers/notes/2026-05-16-phase5-autonomy-exit-summary.md` |
| 低 | **Phase 5 E (そのうち)** | (A) `mimicanno export-undo` CLI、(B) integration contract 凍結 docs、(C) read-only Python client `mimicanno.client` | MimicRec 配置待ち。本リポ完結部分のみ着手可 |
| 中 | **G3 再走** | autonomy exit e2e sanity (`.venv` torch vs driver mismatch で前回停止) | env 整合待ち。1 回回ったので緊急性は低 |
| 低 | **G7 full-ep 再走** | G8 `--limit` 無しで全フレーム depth 生成 → HAMER 再走で `cam_t` metric anchoring 確認 | 初回 PARTIAL の follow-up。優先度低 |
| 低 | **`_vlm_dumps` schema 変化対応** | per-call dir 構造化されたので SFT loader ([[project_gemma_ft_pipeline]]) が読めるか確認 | G6 で判明 |
| 低 | **26B variant 別ホスト** | RTX A6000 48GB では VRAM 不足。VRAM 余裕ホスト確保後 | G1 残課題 |
| 低 | gem4 設定整理 | `mimicanno/configs/robot/gem4_*.yaml` × 3 の clean-up | docs/別 PR |

### 後始末

- `/misc/dl00/gayagaya/MimicAnno-phase5d/frontend/node_modules/` — git 認識外、`rm -rf` でいつでも除去可
- `mimicanno serve` (PID 1063745) — so101_phase4_v5 配信で稼働継続中、別件なので触らない

---

## 未マージ PR 待ち

| branch | 内容 | 状態 |
|---|---|---|
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
| **G1** | batch_annotate 4B smoke (SAM3 runtime 共有 + `BATCH_RUNS_ROOT`) | `3b6899e` etc. (origin/main 済) |
| **G2** | Phase 5 D SO101 v5 UI smoke (17 events × 4 edit types) | autonomy exit 内 |
| **G3** | autonomy exit e2e sanity (SO101 3 ep) | `runs/g3_smoke_20260516_2252/` |
| **G6** | Gemma 4B planner regression (`docs/g-smoke-results`) | `6ca0a43` |
| **G7** 🟡 | Hand+HAMER pipeline mechanics PASS、cam_t anchoring 未検証 (`docs/g-smoke-results`) | `633ca13` |
| **G8** | UniDAC precompute_depth (`docs/g-smoke-results`) | `158b647` |

結果 note は `docs/superpowers/notes/2026-05-17-{g1,g6,g7,g8}-*-smoke-results.md` 等。各 G の詳細・surprise はそれぞれの note 参照。

---

## 推奨次ステップ

1. `docs/g-smoke-results` を PR 作成 → main マージ
2. D r2 backend spec 起こし (高優先度の唯一の実装作業)
3. Phase 5 E は MimicRec 配置待ちで保留
