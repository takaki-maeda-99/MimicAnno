# 残り作業 マスター実行計画 (2026-05-16)

**Status:** approved rev2 (Round 1 + Round 2 レビュー計 4 件反映済み)
**Author:** Claude (Sonnet 4.6) on main
**対象ブランチ:** main (司令塔), feat/run-set-switcher, feat/phase5-b-r2-boundary-drag, feat/phase5-d-eval-harness

---

## 0. 現状確認 (2026-05-16 時点)

### 完了済み (ここには手を入れない)

| 項目 | 根拠 |
|---|---|
| S-HV T1〜T5 + axes overlay | main にマージ済み (`a7d408a`, `5f2e8fb`) |
| **HV-regen** | 全 9 episode が `schema_version=2` (pinch_m / cam_t / euler_deg 付き) で揃っていることを直接確認済み — TODO の `[ ]` マークは **古い状態、実際は完了** |
| B2 spec / plan | `feat/phase5-b-r2-boundary-drag` worktree に push 済み (`3925d23`) |
| D spec / plan | `feat/phase5-d-eval-harness` worktree に push 済み (`69d4d27`) |
| S-RS plan (rev2) | main に push 済み (`d789348`) |
| A0-* 事前整理 | 完了 (TODO §事前整理 参照) |

### 残り作業の要約

| ストリーム | ブランチ | 残作業の種類 | ざっくり規模 |
|---|---|---|---|
| **Day 0 prereqs** | — | git ops のみ | 10 分 |
| **S-RS** | `feat/run-set-switcher` | 実装 (T0–T12) | 半日〜1日 |
| **S-B2** | `feat/phase5-b-r2-boundary-drag` | 実装 (T0–T18) | 2〜3日 |
| **S-D** | `feat/phase5-d-eval-harness` | 実装 (T1–T15) | 1.5〜2日 |

---

## 1. Day 0 prerequisites (S-MAIN が最初に実施)

各 worktree セッションを起動する前に、S-MAIN がこの順で実施する。

### P0: 現在の状態を確認してから作業開始

```bash
git status
git log --oneline origin/main..HEAD
```

local main が clean かつ `d789348` が HEAD であることを確認してから次へ進む。

### P1: origin/main を push

```bash
git push origin main
```

現在 local main は `d789348` で origin より 2 commit 進んでいる。これを揃えることで
各 worktree の `git fetch origin && git log origin/main..HEAD` が正確になる。
(P1 完了後 `origin/main` = `d789348` になるので、RS branch の rebase は no-op。)

### P1.5: HV-regen を完了マークに更新

`TODO.md` の `[ ] HV-regen` を `[x]` に変更する。
根拠: 全 9 episode が既に `schema_version=2` かつ `cam_t / euler_deg / pinch_m` を持つ。
ただし **axes overlay の動作確認 (open question §5 #3) は P3.5 後のブラウザ smoke で行う**。

### P2: 各 branch を main に rebase

```bash
# feat/run-set-switcher
git -C /misc/dl00/gayagaya/MimicAnno-run-set-switcher fetch origin
git -C /misc/dl00/gayagaya/MimicAnno-run-set-switcher rebase origin/main

# feat/phase5-b-r2-boundary-drag
git -C /misc/dl00/gayagaya/MimicAnno-phase5b-r2 fetch origin
git -C /misc/dl00/gayagaya/MimicAnno-phase5b-r2 rebase origin/main

# feat/phase5-d-eval-harness
git -C /misc/dl00/gayagaya/MimicAnno-phase5d fetch origin
git -C /misc/dl00/gayagaya/MimicAnno-phase5d rebase origin/main
```

注意: B2 branch は `3925d23` (spec+plan commit 1 本のみ)。D branch は `69d4d27` (同)。
RS branch は `d789348` — これは main と同じ HEAD なので rebase は no-op。

### P3: 各 worktree で submodule init + frontend setup 確認

frontend は **pnpm** を使用 (`pnpm-lock.yaml` が存在する)。`npm install` ではなく
`pnpm install --frozen-lockfile` を使うこと。`npm install` を走らせると lockfile と
無関係な `node_modules` が生成され後段の `pnpm vitest` で依存解決ずれが起きる。

```bash
for wt in MimicAnno-run-set-switcher MimicAnno-phase5b-r2 MimicAnno-phase5d; do
  echo "=== $wt ==="
  git -C /misc/dl00/gayagaya/$wt submodule update --init --recursive
  cd /misc/dl00/gayagaya/$wt/frontend && pnpm install --frozen-lockfile && cd -
done
```

### P3.5: HV axes overlay を 1 episode ブラウザ確認 (任意だが推奨)

`schema_version=2` は必要条件。axes overlay が実際に canvas に描画されるかを
GX010085 で目視確認してから HV-regen を正式に完了とする。

### P4: TODO.md を更新してコミット

- `[x] HV-regen` に変更 (P3.5 確認後)
- Day 0 prereqs チェックボックスを `[x]` に

```bash
git -C /misc/dl00/gayagaya/MimicAnno add TODO.md
git -C /misc/dl00/gayagaya/MimicAnno commit -m "docs(TODO): mark HV-regen done + Day 0 prereqs complete"
git -C /misc/dl00/gayagaya/MimicAnno push origin main
```

---

## 2. ストリーム実行計画

3 ストリームはすべて独立して並列実行可能 (worktree 間の DAG レビュー済み)。
ただしマージ順は §3 の通り固定する。

### 2.1 S-RS (run-set switcher) — 最初にマージ

**ブランチ:** `feat/run-set-switcher` (worktree: `MimicAnno-run-set-switcher`)
**詳細計画:** `docs/superpowers/plans/2026-05-16-run-set-switcher-plan.md` (rev2 レビュー済み)

**タスク一覧 (plan §3 参照):**

| Task | 概要 | 性質 |
|---|---|---|
| T0 | audit: conftest.py fixture 確認、frontend mock 手法確認 | audit |
| T1 | `list_run_sets(parent)` + unit test | server |
| T6 | `tmp_parent_runs_root` fixture を conftest.py に追加 | test infra |
| T2 | `make_router` を `parent_root` ベースに変更 + `/api/run-sets` endpoint + traversal 対策 | server |
| T3 | `GET /api/runs/index.json?run_set=` 対応 + test | server |
| T4 | `GET /api/runs/{name}/{artifact}?run_set=` 対応 + test | server |
| T5 | `PATCH /api/runs/{name}/segments/{id}?run_set=` 対応 + test | server |
| T7 | `frontend/src/lib/runsClient.ts` 新規 + unit test | frontend |
| T8 | `RunList.tsx` にドロップダウン追加 + test | frontend |
| T9 | `App.tsx` で `?run_set=` を prop に流す | frontend |
| T10 | `RunViewer.tsx` + `editClient.ts` に `?run_set=` pass-through + test | frontend |
| T11 | mypy --strict + 既存 tests (1170+) all green | gate |
| T12 | 手動 smoke (§4 参照): runs/ 親渡し + ブラウザ切り替え + legacy 確認 | gate |

**出口基準 (plan §0 参照):**
1. `GET /api/run-sets` → サブディレクトリ一覧
2. `GET /api/runs/index.json?run_set=<name>` → 正しい index
3. `PATCH /api/runs/{name}/segments/{id}?run_set=<name>` → 正しく書き込む
4. ブラウザ ドロップダウンで切り替えると episode 一覧が変わる
5. 既存 1170+ tests green、mypy --strict clean
6. legacy mode (単一 run-set ディレクトリ渡し) でドロップダウン非表示

### 2.2 S-B2 (境界ドラッグ) — S-RS マージ後にマージ

**ブランチ:** `feat/phase5-b-r2-boundary-drag` (worktree: `MimicAnno-phase5b-r2`)
**詳細計画:** `docs/superpowers/plans/2026-05-16-phase5-b-r2-boundary-drag-plan.md` (独立レビュー済み)

**タスク一覧 (plan §2 参照):**

| Task | 概要 | 性質 |
|---|---|---|
| T0 | audit: r1 fixture 確認、frontend mock 手法確認 | audit |
| T1 | `write_txn.py` 抽出 (edit_repo.py からリファクタ) + r1 全 test green | refactor |
| T2 | `boundary_lookup.py`: `resolve_boundary` + 例外 2 種 + unit test | server |
| T3 | `boundary_lookup.py`: `validate_new_frame` + `InvalidFrame` + unit test | server |
| T4a | `boundary_repo.py`: `derive_boundary_run_hash` (pure helper) | server |
| T4b | `boundary_repo.py`: `patch_boundary` 本体 + unit test 4 ケース | server |
| T5 | PATCH route `/api/runs/{name}/boundaries/{id}` + 17 unit test (TDD) | server |
| T7 | server integration: 実データ drag → re-GET → 古 ETag 412 | integration |
| T8 | race test: `concurrent.futures` 2 並列 PATCH → `{200, 412}` | integration |
| T9 | hash disjoint pin: r1/r2/auto-pipeline 3 空間が disjoint であることを assert | integration |
| T10 | frontend deps 確認 (pointer-events-polyfill の要否) | frontend |
| T11 | `boundaryClient.ts` 新規 + unit test | frontend |
| T12 | `TimelineRuler.tsx` 新規 (32px 高、keyboard nudge、pointer events) | frontend |
| T13a | `RunViewer.tsx`: in-flight state を上に巻き上げ (state-lift refactor) | frontend |
| T13b | `<TimelineRuler>` を SegmentTable 上に挿入、pendingPatch 共有 | frontend |
| T14 | frontend vitest 3 ケース (drag/412/edge) | frontend |
| T15 | gate: mypy --strict + `~1190 tests` + `~63 frontend tests` | gate |
| T16 | 手動 smoke: SO101 v5 + Piper v5 で境界 3 本を drag → reload → persist | gate |
| T17 | docs: server README + trunk README | docs |
| T18 | memory 更新 | docs |

**出口基準 (plan §0 参照):**
1. PATCH `/api/runs/<name>/boundaries/<id>` happy path round-trip
2. +22 新規テスト全 green
3. status-code matrix 完備 (200/400×4/404/405/412/415/428)
4. race test: 正確に `{200, 412}`
5. r1/r2/auto-pipeline hash 3 空間 disjoint
6. 既存 1170+ tests green、mypy --strict clean
7. frontend smoke: 境界 3 本 drag → reload で persist
8. JSON schema 変更なし

**S-RS との衝突リスク:**
- **S-RS の T10 も `RunViewer.tsx` を変更する** (`?run_set=` の artifact fetch / PATCH への pass-through)。
  B2 の T13a/b も `RunViewer.tsx` で state-lift refactor を行う。
  → **B2-T10 (frontend 着手) 前に S-RS が main にマージ済みであること**を必須とする。
  マージ後 B2 は `feat/phase5-b-r2-boundary-drag` を main に rebase する際、
  `RunViewer.tsx` の衝突を解消する (S-RS の `?run_set=` pass-through を保持しつつ
  state-lift を上に積む)。S-RS マージ前に B2 backend (T0–T9) を進めることは可。

### 2.3 S-D (eval harness) — B2 マージ後に frontend 統合

**ブランチ:** `feat/phase5-d-eval-harness` (worktree: `MimicAnno-phase5d`)
**詳細計画:** `docs/superpowers/plans/2026-05-16-phase5-d-eval-harness-plan.md` (rev1 レビュー済み)

S-D は Phase 5 A の **read-only** endpoint のみを消費するため、B2 と並列実装可。
ただし D-T11 は `RunViewer.tsx` の `PhaseSelect` 周辺に `focusin`/`change` 計測 hook を追加する。
B2-T13a/b も同じ `RunViewer.tsx` の state-lift を行うため、
**D-T11 は S-RS + B2 の両マージ後**に着手する。
また **D-T5 (`apply_edit` 拡張) は B2-T1 (`write_txn.py` 抽出) が完了した後**に着手する
(`edit_repo.py` の write block 構造が T1 で大きく変わるため)。

**タスク一覧 (plan §2 参照):**

| Task | 概要 | 性質 | 依存 |
|---|---|---|---|
| T1 | `EditEvent` dataclass + JSON serializer + unit test | schema | なし |
| T2 | `AnnotationResult.history` field + conditional emit + regression test | schema | なし |
| T3 | `annotation.schema.json` bump v2.0 + loader 拡張 | schema | なし |
| T4 | `_build_event` helper + unit test (time mock, clipping, first/subsequent) | server | なし |
| T5 | `apply_edit` 拡張: history append + B r1 38 ケース無修正確認 | server | **B2-T1 完了後** |
| T6 | PATCH route: `client_edit_duration_ms` validator + spec §5.1 #1-#10 | server | なし |
| T6.5 | B3 fix: `HISTORY_AHEAD_OF_MANIFEST` + 412 で history 不変 | server | なし |
| T7 | server integration 3 ケース (real disk PATCH → CLI / annotate overwrite / hash chain) | integration | なし |
| T8 | `mimicanno/eval/` package: `metrics.py` pure 関数群 + 12 unit test | eval | なし |
| T9 | `render.py` (Markdown renderer) + snapshot fixture | eval | なし |
| T10 | `eval/cli.py` + `cli.py` への `eval` subcommand 追加 | cli | なし |
| T11 | frontend: `RunViewer.tsx` の `PhaseSelect` に `focusin`/`change` 計測 hook + vitest | frontend | **T10 後 + S-RS + B2 両マージ後** |
| T12 | gate: mypy --strict + 全 regression (1100+) | gate | T11 後 |
| T13 | 手動 smoke: SO101 v5 で 5 edits → `mimicanno eval` → client_coverage ≥ 0.8 | gate | T12 後 |
| T14 | docs | docs | T13 後 |
| T15 | memory 更新 | docs | T14 後 |

**出口基準 (plan §0 参照):**
1. `EditEvent` schema + `annotation.schema.json` v2.0 bump
2. `apply_edit` が PATCH ごとに 1 event 追加 (atomicity 保持)
3. `client_edit_duration_ms` round-trip (UI → PATCH → history)
4. `mimicanno eval` CLI (JSON + Markdown)
5. `human_edit_time` + `label_agreement` 計算
6. 全 27 新規テスト green + B r1 既存 38 ケース無変更 green
7. mypy --strict clean (eval/ + edit_repo.py touch 行)
8. frontend client_coverage 計測 + vitest 1 ケース追加
9. SO101 v5 smoke で client_coverage ≥ 0.8

---

## 3. マージ順と司令塔の責務

```
Day 0 prereqs
    │
    ├─ S-RS (feat/run-set-switcher) → マージ ①
    │
    ├─ S-B2 backend (T0-T9: B2-T1 完了を D に通知)
    │       │
    │       └─ S-RS マージ後: rebase → S-B2 frontend (T10-T18) → マージ ②
    │
    └─ S-D backend T1-T4, T6-T10 (B2-T1 完了後に T5 を追加)
            │
            └─ S-RS + B2 両マージ後: rebase → S-D-T11 → gate → マージ ③
```

**重要な hard gate:**
- **B2-T10 (frontend 着手)**: S-RS マージ済みが必須 (RunViewer.tsx 衝突)
- **D-T5 (apply_edit 拡張)**: B2-T1 (write_txn.py 抽出) 完了済みが必須 (edit_repo.py 大規模 refactor 後)
- **D-T11 (frontend hook)**: S-RS + B2 の両マージ済みが必須 (RunViewer.tsx 三重衝突回避)

### 司令塔 (S-MAIN) のチェックポイント

| タイミング | やること | マージ承認基準 |
|---|---|---|
| Day 0 完了時 | P0–P4 実施 + origin/main push 確認 | — |
| B2-T1 完了報告受信時 | D ストリームに「T5 着手 OK」を通知 | — |
| S-RS 完了報告受信時 | handoff note + exit criteria checklist 全 `[x]` 確認 | plan §0 出口基準 6 項目 + mypy clean + 1170+ tests green |
| S-RS マージ後 | B2 ストリームに「rebase + frontend (T10) 着手 OK」を通知 | — |
| S-B2 完了報告受信時 | smoke notes + exit criteria checklist 全 `[x]` 確認 | plan §0 出口基準 8 項目 + mypy clean + 1190+ tests green |
| S-B2 マージ後 | D ストリームに「rebase + T11 着手 OK」を通知 | — |
| S-D T10 完了時 | S-RS + B2 両マージ済みを確認してから T11 着手を指示 | — |
| S-D 完了報告受信時 | smoke notes + client_coverage 確認。S-D が rebase 後に B r1 38 ケースを再走して green であることを確認してから S-MAIN がマージ承認する | plan §0 出口基準 9 項目 + mypy clean + 1100+ tests green (B r1 38 ケース含む) |
| 全ストリーム完了時 | wrapup note + real-data sanity check → ユーザー handoff | §6 完了条件全 `[x]` |

### ロールバック方針

各マージは `feat/*` ブランチを削除しない。問題発生時:
1. `git revert -m 1 <merge-commit>` で main から切り戻す
2. `feat/*` ブランチで修正 → 再 PR

main への force-push は不可 (shared branch)。

### MEMORY.md 編集ルール (再掲)

- **MEMORY.md は S-MAIN のみが編集**
- 各ストリームは `project_*.md` 新規ファイルを作成し、index 追加要求を notes/ 経由で S-MAIN に通知
- HV-regen 完了を `project_hand_viewer_shipped.md` に追記 (S-MAIN が実施)

---

## 4. リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| **S-RS (T10) と B2 (T13a/b) が `RunViewer.tsx` を同時に変更** | B2 rebase 時に衝突 (高確率) | §3 の hard gate 通り: B2-T10 着手前に S-RS マージ必須。rebase 後に `?run_set=` pass-through を保持しつつ state-lift を積む作業が必要 (30 分程度の手作業) |
| **S-RS と S-D-T11 が `App.tsx` を変更する可能性** | D-T11 rebase 時に衝突 | §3 の hard gate 通り: D-T11 着手前に S-RS + B2 両マージ必須。App.tsx の変更面積は軽微と予想されるが衝突は実在しうる |
| **D-T5 (`apply_edit` 拡張) と B2-T1 (`write_txn.py` 抽出) が `edit_repo.py` を競合変更** | 致命的 conflict | §3 の hard gate 通り: D-T5 は B2-T1 完了後のみ着手。B2-T1 が `edit_repo.py` を wrapper 化した後に D-T5 が history append を追記する (行が物理的にずれる) |
| **D-T3 の `schema_version` bump (v2.0) が B2 の fixture を壊す** | B2 が D マージ後の rebase で fixture 不一致 | B2 は D より先にマージ (§3 順序)。D マージ後に B2 の追加作業が生じた場合は fixture を再生成する必要がある旨を B2 完了 notes に残す |
| **B r1 38 ケースの green 維持の責務分担** | D が apply_edit 拡張後に 38 ケースの一部が壊れる | D-T5 で確認 + S-MAIN が D マージ前に「D rebase 後の 38 ケース再走」を gate に追加 (§3 チェックポイント参照) |
| `MimicAnno-run-set-switcher` の branch が main と同 HEAD | push 時に "nothing to push" | 実装コミットを積んでから push。P2 の rebase は no-op で問題ない |
| HV-regen が一部 episode で axes overlay 未動作 | Hand viewer の軸表示が出ない | `schema_version=2` は確認済み。P3.5 で GX010085 の axes overlay をブラウザで目視確認してから完了マーク |
| `git submodule update --init` がネットワークタイムアウト | worktree セットアップ失敗 | worktree は `.git/modules/` を main と共有するので通常 network 不要 (checkout のみ)。sam3 等の new remote は P2 の rebase 前に `git submodule status` で pointer 確認 |

---

## 5. 開口問題 (open questions)

1. **S-D-T11 が `App.tsx` も変更するか**: D plan T11 は `RunViewer.tsx` の `PhaseSelect` 周辺のみを変更し、`App.tsx` への変更は現時点で明示されていない。ただし S-RS が `App.tsx` に `?run_set=` param を追加するため、D-T11 着手時には既に変更済みの `App.tsx` の上に乗る形になる。実際の変更量は T11 着手時に確認。
2. ~~pnpm vs npm~~: **解決済み** — `pnpm-lock.yaml` が存在することを確認。P3 で `pnpm install --frozen-lockfile` を使う。
3. **`data/hands/` の axes overlay 動作確認**: P3.5 でブラウザ確認を推奨 (§4 リスク表参照)。確認できなかった場合でも実装作業は進められる (axes overlay は別ブランチ `feat/hand-viewer-axes` で既に実装済み)。

---

## 6. 完了条件 (このマスター計画としての)

- [ ] Day 0 prereqs 完了 (P0–P4)
- [ ] S-RS merged (feat/run-set-switcher → main)
- [ ] S-B2 merged (feat/phase5-b-r2-boundary-drag → main)
- [ ] S-D merged (feat/phase5-d-eval-harness → main)
- [ ] TODO.md の S-RS / B2 / D チェックボックスすべて `[x]`
- [ ] **Real-data labeling qualitative sanity check**: SO101 v5 + Piper v5 の phase ラベリング結果を人間目視で確認し、phase が期待通りに並んでいることを notes に記録する (autonomy window exit 条件 #2)
- [ ] **eval harness による client_coverage ≥ 0.8 を実データで確認** (S-D-T13 の再走または同等)
- [ ] `docs/superpowers/notes/2026-05-16-multi-stream-wrapup.md` 作成 (shipped / what looked off / open questions の 3 セクション構成。B2 境界 drag smoke 結果 + D eval harness smoke 結果を必ず含む)
- [ ] memory 更新 (project_phase5_status.md, 各 shipped エントリ)
- [ ] main で `uv run pytest tests/ -q` all green + `cd frontend && pnpm test` all green (統合 regression)
- [ ] ユーザーへの handoff 完了 (autonomy window exit 条件 #3)
