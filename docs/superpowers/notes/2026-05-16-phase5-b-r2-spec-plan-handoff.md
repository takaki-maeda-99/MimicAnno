# Phase 5 B r2 (境界ドラッグ編集) — spec / plan 起こしハンドオフ

Date: 2026-05-16
Branch: `feat/phase5-b-r2-boundary-drag` (worktree `/misc/dl00/gayagaya/MimicAnno-phase5b-r2`)
Author: Claude (Opus 4.7)

## 成果物

- **spec**: `docs/superpowers/specs/2026-05-15-phase5-b-r2-boundary-drag-design.md`
- **plan**: `docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md`
- 本ノート (作業ログ)

## 進めた手順

1. **前提整理** — r1 (`2026-05-13-phase5-B-edit-relabel-design.md`) と memory
   (`project_phase5_b_r1_shipped`, `phase-5-sub-project-status-2026-05-14`)
   を読み、A の write 担当が B に契約変更済みなことを確認。worktree TODO
   `TODO.md:91/103` の **B2-spec / B2-plan** を起点に置く。
2. **spec 初稿** — r1 spec の構造 (§1〜§8) をテンプレに、r2 のスコープ
   「隣接 2 segment の共有境界 1 本を frame snap で動かす」を 1 操作 1
   PATCH に閉じ込めた形で起草。endpoint は新規
   `PATCH /api/runs/<name>/boundaries/<boundary_id>` (boundary_id = 右側
   segment_id) で r1 PATCH と path 形を分離。
3. **独立 spec レビュー** — `brainstorming-skill` プラグインが未インストール
   だったため、general-purpose Agent に「proxy 役」を投げて指摘を収集
   (12 件、MUST/SHOULD/NICE 分類)。
4. **spec 修正反映** — 以下を取り込み:
   - **MUST**: §3.4 のサンプルコードが `SubtaskSegment(**to_dict())` で
     TypeError 確実だった → `dataclasses.replace` + 既存
     `smoother._recompute_confidence` 再利用に書き換え。新規 helper 案
     (§8 step 1) は削除。
   - **MUST**: §3.5 の disjoint 議論を「preimage byte index による
     disjoint (r1=`'s'`, r2=`'b'`)」に書き直し、segment_id 命名規約に
     依存しない論証へ。
   - **SHOULD**: §5.1 #1 に `boundary_confidence` / `overall_confidence`
     再計算の explicit assert を追加。
   - **SHOULD**: §3.7 に `AbortController` + 10s timeout (UI stuck-disabled
     防止) と TimelineRuler のサイズ規約 (32 px / 4 px-per-frame / ←→
     keyboard nudge / `role="slider"`) を pin。
   - **SHOULD**: §5.1 #16 に `ThreadPoolExecutor(max_workers=2)` での
     並列発火を明記。
   - **NICE**: §4 に「parquet sidecar の `boundary_source_*` 列に
     `"human_edit"` が現れる」consumer 通知を追記。
   - **NICE**: §3.3 の no-op 扱いを「クライアントで送らない、サーバは
     最終防衛で 400」に明確化。
5. **plan 初稿** — r1 plan (`2026-05-13-phase5-B-edit-relabel-plan.md`)
   の §0〜§5 構造を踏襲し、T1〜T18 を分解。
6. **独立 plan レビュー** — Agent に同様に依頼、8 件 (MUST/SHOULD/NICE)。
7. **plan 修正反映** — 以下を取り込み:
   - **MUST**: T9 の preimage 例が r1 実装 (`edit:` + 完全な
     `"sha256:..."` を含む `old_run_hash`) と乖離 → 手計算 hex を捨て、
     T4a で `derive_boundary_run_hash` helper を先行実装し、T9 はその
     helper の出力を直接 pin する形に。
   - **MUST**: T1 の `write_run_atomically` 署名に `index_row` を明示
     (r1 既存の 3-file write 契約を保持)。
   - **MUST**: T0 audit task を新設 (fixture `real_so101_run` 存否確認 +
     r1 fetch mock 流儀 `vi.fn` vs `msw` 確認)。
   - **SHOULD**: T6 (405 wiring) を T5 に統合、T5 自体で `Allow: PATCH`
     も検証。
   - **SHOULD**: T4 を T4a (pure hash helper) と T4b (write txn 本体) に
     分割し「1 task = 1 commit」を守る。
   - **SHOULD**: T13 を T13a (state-lift refactor) と T13b (TimelineRuler
     組み込み) に分割、frontend single-in-flight gate の hidden refactor
     を顕在化。
   - **SHOULD**: T1 acceptance に `mypy --strict` を明記 (T15 まで遅延
     しない)。

## スコープ要点 (実装前の最終確認)

- **mutate 対象**: 隣接 2 segment の (start|end)_(frame|time|boundary) +
  `smoothing_ops += ["edited"]` (dedup) + `reviewed=True` + `reviewer_id`
  + `boundary_confidence` / `overall_confidence` 再計算
- **触らない**: `phase`, `verb`, `object`, `target`, `failure_flags`,
  `object_track_ids`, `evidence`, `label_source`、非対象 segment 一切
- **新エンドポイント**: `PATCH /api/runs/<name>/boundaries/<boundary_id>`
  (body `{"frame": int}`)。`boundary_id` は右側 segment の `segment_id`
- **disjoint hash 空間**: r1 (`edit:` + `sha256:`...) / r2 (`edit:boundary:`...)
  / auto-pipeline (32-byte 連結) の 3 つを byte index 0..5 で完全分離
- **frontend**: TimelineRuler 新規コンポーネント (32 px 段)、内側境界
  のみハンドル、frame snap、AbortController 10s timeout、single-in-flight
  state を `RunViewer` にリフトして既存 `<select>` と共有

## 残課題 / 未着手

- T0 audit (fixture + mock 流儀確認) — 実装着手時の最初の task
- 実装 T1〜T18 — 本 plan の通り順に
- CHANGELOG 更新の慣行が r1 plan で明示されていないため r2 でも今は
  入れていない。r1 PR で実態を確認のうえ、必要なら T17 に足す
- CORS 設定変更は **不要** の見込み (r1 で既に PATCH を `allow_methods`
  に含めている)。T0 で確認

## 関連メモリ

- `[[project_phase5_b_r1_shipped]]` — r1 が `9f1dd06` で取り込み済、
  本 branch はそこから分岐
- `[[phase-5-sub-project-status-2026-05-14]]` — B 行を r2 SHIPPED 時に
  更新予定 (T18)
- `[[feedback_plan_before_implement]]` — 本ハンドオフはこのフィードバック
  通り、独立レビュー 2 周 (spec 1 周 + plan 1 周) を経て確定
- `[[feedback_handoff_conflict_check]]` — 実装着手時に `git branch -v` +
  `git log --oneline -10` を実行する規約
