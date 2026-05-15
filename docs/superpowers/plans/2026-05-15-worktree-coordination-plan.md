# Worktree 並列開発 調整計画 (2026-05-15)

**司令塔セッション:** `/misc/dl00/gayagaya/MimicAnno` (main worktree)
**並列セッション:** 3 worktree (うち 2 は別ターミナルで独立 Claude セッション起動)

## -1. Day 0 prerequisites (各 worktree セッション起動前に S-MAIN が完了させる)

レビュー指摘事項を踏まえた必須前提:

- [ ] **origin/main を push して同期** — 現在 local main は `9145e33`、origin は `9f1dd06` 相当で 6 commit 遅れ。これがないと §5.1 の `origin/main..HEAD` 比較が嘘になる
- [ ] **`fix/phase5-b-r1-dev-followup` の処遇を確定** (merge / drop / S-B2 に取り込み のいずれか) — 未決のまま S-B2 を起動すると衝突
- [ ] **各 worktree branch を main に rebase** — `feat/hand-viewer`, `feat/phase5-b-r2-boundary-drag`, `feat/phase5-d-eval-harness` はいずれも `111befe` 起点で、現 main `9145e33` と 4 commit (cleanup docs + T3/T4) ずれている。submodule pointer 違いの伏線
- [ ] **各 worktree で submodule init + frontend setup**:
  ```bash
  cd <worktree> && git submodule update --init --recursive
  cd frontend && npm install  # node_modules は worktree ごとに独立に必要
  ```

## 0. 前提と現状

- main HEAD: `9145e33` (2026-05-15 時点)
  - Phase 4 v5 / Phase 5 A read-only + B r1 / Phase 5 C / Hand pipeline Phase A-B / Hand viewer T1-T4 = shipped
  - 既存 worktree: `MimicAnno-planner-fix` (`feat/planner-visual-prompts` @ `a5939b4`) は別件で稼働中
- ディスク掃除済 (24G 削減、`docs/cleanup-2026-05-15.md` 記録)
- 自動メモリ (`~/.claude/projects/-misc-dl00-gayagaya-MimicAnno/memory/`) で各セッション間の永続的な事実共有が可能 (ただし real-time ではない)

## 1. ストリーム定義と狙い

| ID | Worktree | ブランチ | 担当範囲 | 完了の出口基準 |
|---|---|---|---|---|
| **S-HV** | `MimicAnno-hand-viewer` | `feat/hand-viewer` | Hand viewer T5 (統合 smoke) + 全 episode signals.json v2 再生成 | smoke notes 1 本記録 + 全 9 episode の signals.json schema_version=2 |
| **S-B2** | `MimicAnno-phase5b-r2` | `feat/phase5-b-r2-boundary-drag` | Phase 5 B r2: 境界ドラッグ編集 (spec → plan → impl → smoke) | PATCH endpoint + UI ドラッグ + smoke green、PR レビュー通過 |
| **S-D** | `MimicAnno-phase5d` | `feat/phase5-d-eval-harness` | Phase 5 D: Evaluation harness (spec → plan → impl) | spec + plan 完了 + impl 着手 (eval harness は Phase 5 A の **read-only** endpoint をコンシューマとして使うため、S-B2 と並列で impl 可) |
| **S-MAIN** | `MimicAnno` | `main` | 司令塔: 進捗統合、衝突解消、メモリ更新、レビュー手配、最終マージ承認 | 全 S-* マージ + memory 更新 + handoff note |

## 2. 依存関係 (DAG)

```
S-HV  ─── 独立
S-B2  ─── 独立 (RunViewer.tsx で衝突可能性)
S-D   ─── 独立 (Phase 5 A の read-only endpoint をコンシューマ)
```

- **3 ストリームすべて独立** (レビュー指摘: S-D を S-B2 の writable API 依存と当初書いたが誤り。eval harness は Phase 5 A の既存 read-only endpoint を消費するため B2 を待たなくてよい)
- S-HV が smoke 段階で frontend 微修正を要する可能性は残る (T5 で UI バグが出るかも) → 「frontend 変更なし」とは断言しない
- 触る frontend ファイルの衝突マトリクス:
  | ファイル | HV | B2 | D |
  |---|---|---|---|
  | `RunViewer.tsx` | 触らない (smoke のみ) | **触る** (BoundaryDragLayer hook) | 触らない |
  | `RunList.tsx` | 触らない (T4 で main 済) | 触らない | 触る可能性 (eval 結果リンク) |
  | `App.tsx` | 触らない | 触らない | 触る可能性 |
  → 主衝突候補は **D が RunList/App を触る場合の B2 との競合**。S-D は frontend 触る前に S-B2 マージ待ち推奨

## 3. マージ順序とリリース戦略

1. **S-HV** を最初にマージ (smoke で確認した時点で `feat/hand-viewer` → main、Fast-Forward 可)
2. **S-B2** を 2 番目 (rebase on main → CI green → merge)
3. **S-D** spec/plan のみ commit (impl 未完なら branch だけ push、merge は impl 完了後)

理由: S-HV は **既に T1-T4 が main に取り込み済で残作業は smoke のみ** → 出口が確定的で最短マージ可能。S-B2 は spec 起こしからなのでサイクル時間が最大、main を最新に保つために短サイクル rebase を強制する。S-D は frontend を最後に触ることで B2 とのコンフリクトを最小化する。

## 4. 各ストリームの out-of-scope (重要)

ストリーム間の責任を明確化し、勝手に他ストリームの領域に踏み込まない。

- **S-HV (out)**: phase 編集、boundary 編集、eval、新規エンドポイント追加禁止 (smoke + regen のみ)
- **S-B2 (out)**: hand pipeline、eval、phase 5 C export 変更禁止
- **S-D (out)**: B2 が触る relabel/boundary endpoint の変更禁止 (read-only consumer に徹する)
- **S-MAIN (out)**: 各ストリームの内部実装に手を入れない (レビューと統合のみ)

## 5. セッション間コミュニケーション・プロトコル

各 worktree セッションは独立した context を持つので、以下のルールで間接共有する。

### 5.1 開始時の手順 (各セッションが実行)
1. `git fetch origin && git log --oneline origin/main..HEAD` で自分の branch の状態確認
2. `~/.claude/projects/-misc-dl00-gayagaya-MimicAnno/memory/MEMORY.md` を読む
3. `cat docs/superpowers/plans/2026-05-15-worktree-coordination-plan.md` (本計画) を読む
4. 自分のストリーム範囲外には触らないことを確認

### 5.2 重要な決定をしたとき
- spec 確定 / 重要な API contract 変更 / 設計判断 → memory にプロジェクト型エントリを追加 (`project_*.md`)
- ファイル名規約: `project_phase5_b_r2_spec.md` 等
- MEMORY.md index にも 1 行追加

### 5.3 他ストリームに影響しそうな変更を見つけたら
- 即マージせず、まず memory に project entry を書き、`docs/superpowers/notes/2026-05-15-cross-stream-<topic>.md` に詳細
- S-MAIN セッションが定期的に notes/ をチェック → 必要なら他セッションに対応依頼

### 5.4 完了報告
- 完了したらブランチを push + `docs/superpowers/notes/2026-05-15-<stream>-done.md` に handoff note
- S-MAIN がマージ判断

## 6. レビュー・品質ゲート

各ストリーム個別:
1. spec → spec-document-reviewer subagent でレビュー (B2, D)
2. plan → 自己レビュー + 主要なリスクを plan 末尾に列挙
3. impl → ローカル test green + smoke
4. 完了直前 → `code-reviewer` または `general-purpose` agent で diff レビュー
5. S-MAIN がマージ前に最終確認

S-HV のみは spec/plan 既存のため step 1-2 はスキップ可、step 3-5 のみ。

## 7. リスクと緩和策

| リスク | 影響 | 緩和策 |
|---|---|---|
| 同じ frontend ファイル (`RunViewer.tsx`) を S-B2 が触る間に main が動く | merge conflict | S-B2 は短いサイクルで rebase。S-MAIN は main への直接 push を避け、必ず branch 経由 |
| submodule (UniDAC/hamer/sam3) の pointer が複数 worktree で食い違う | ビルド壊れ | worktree 作成直後に `git submodule update --init` を各 worktree で実行。pointer 変更時は S-MAIN が main に bump を 1 本化 |
| `_vlm_dumps_archive/` の jsonl を S-D が eval で使う可能性 | データ消失で再現性壊れる | archive は不削除。S-D spec に「historical FT data は `_vlm_dumps_archive/2026-05-15/` を参照」を明記 |
| `data/hands/` regen 中に S-HV が smoke 実行 | データ不整合 | regen は smoke 完了後に行う (S-HV 内のタスク順を `T5 smoke → regen` で固定) |
| 各セッションが古い memory を信じて作業 | 食い違い | 開始時 (5.1) で MEMORY.md を必ず読む + memory 参照前に該当ファイルが今日の date stamp を持つか確認 |
| autonomy window が exit 済? (2026-05-13 ユーザー指示で exit と memory に記載、ただし Phase 5 全体の exit 条件は未達) | 大きな判断を勝手に進める | 各セッションが破壊的/コスト大の決定前に user に問う。曖昧時は `[[project_phase5_status]]` を再読 |
| **frontend node_modules 不整合** (worktree ごとに独立 install 必須) | dev server 起動失敗 | Day 0 prereqs に `npm install` 明記 (上記) |
| **共有 `data/` への並列書き込み** (3 セッションが test や smoke で同じ JSON store を更新) | データ破損 | テストは `data/_test_<stream>/` を使う。smoke は順次実行 (S-MAIN がスケジュール調整) |
| **tests/ fixture 名衝突** (B2 と D が同名 fixture を新規追加) | rebase 時の merge conflict | 各ストリームの fixture は `tests/<stream>_fixtures/` プレフィクス必須 |
| **git stash がリポジトリ単位**で全 worktree から見える | 別ストリームの stash を誤って pop | 各セッションは作業開始時 `git stash list` を確認、自分以外の stash には触らない |
| **MEMORY.md 同時編集**で 3 セッションが同じ index 行を取り合う | conflict 発生 | **MEMORY.md は S-MAIN のみが編集**。他ストリームは `project_*.md` の新規ファイルのみ書き、MEMORY.md への 1 行追加要求を notes/ に書いて S-MAIN が反映 |
| **regen の実時間が読めない** (9 episode × hamer GPU 推論) | Day 1-2 タイムライン崩れ | 1 episode 実行して実測 → 残り 8 episode の ETA を計算してから schedule 確定 |

## 8. タイムライン目安 (順次マージ前提)

| Phase | 内容 | 期限 |
|---|---|---|
| Day 0 (today) | 計画レビュー → 全 worktree 起動 + 開始指示 | 2026-05-15 |
| Day 1 | S-HV smoke → main マージ。regen 1 episode 実測 → ETA 確定。S-B2 spec 着手 | 2026-05-16 |
| Day 2-3 | regen 残り 8 episode (実測 ETA 依存)。S-B2 plan 完了。S-D spec 着手 | 2026-05-17 〜 18 |
| Day 3-5 | S-B2 impl → smoke → main マージ。S-D plan → impl (backend/CLI 中心、frontend 部分は B2 マージ後) | 2026-05-18 〜 20 |
| Day 6+ | S-D frontend 統合 + smoke | 2026-05-21 〜 |

## 9. 完了条件 (master plan としての)

- [ ] S-HV merged + signals.json v2 全 episode 確認
- [ ] S-B2 merged + smoke notes 記録
- [ ] S-D spec + plan 完成 (impl はオプション)
- [ ] memory に各 stream の `project_*` エントリ追加 + MEMORY.md 更新
- [ ] handoff summary を `docs/superpowers/notes/2026-05-15-multi-worktree-summary.md` に書いてユーザーに引き渡し

## 10. 開かれた疑問

- `fix/phase5-b-r1-dev-followup` (1 unmerged commit "← runs" back link) の扱い — S-B2 着手前に判断必要 (本 commit を B2 ブランチに含めるか、独立 PR にするか、破棄か)
- S-D の eval harness が外部依存 (例: ground truth dataset) を必要とするなら、その入手手段
- regen 完了後の signals.json v1 バックアップ保持期間
