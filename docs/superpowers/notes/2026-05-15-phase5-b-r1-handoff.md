# Phase 5 B r1 — smoke session handoff note

**Date:** 2026-05-15
**Session:** UI smoke verification + BLOCKER fix landing

---

## Code state

All Phase 5 B r1 code including 3 BLOCKER fixes is in `origin/main` at `9f1dd06`.

```
9f1dd06  Merge remote-tracking branch 'origin/main'
4c51468  Merge branch 'feat/hand-pipeline'
5c0b6cb  Merge branch 'feat/phase5-b-r1-relabel'
2d63e0a  docs(phase5-b/r1): UI smoke verification plan + findings summary
8ab858d  fix(phase5-b/r1): toast prefix uses server error code on generic 5xx
9944b44  fix(phase5-b/r1): reload button drops ?hash so 412 recovery succeeds
2b71741  fix(phase5-b/r1): replaceState URL ?hash after successful PATCH
```

No open PRs related to r1. No local smoke/* branches.

---

## BLOCKER fixes (commit details)

| SHA | Fix | Why it matters |
|-----|-----|----------------|
| `2b71741` | PATCH 成功後に `history.replaceState` で URL `?hash` を新ハッシュへ更新 | 編集後リロードすると "no run for episode_id=X hash=<old>" エラーになっていた (D4) |
| `9944b44` | 412 conflict 後の reload ボタンが `?hash` を剥がしてから navigate | hash 付きでリロードすると同じ "no run" になっていた (E4) |
| `8ab858d` | 5xx toast が `HTTP 500: …` でなくサーバーの `error` フィールドを表示 | spec §3.5: `internal: unexpected error` のような正確なコードを出す必要がある |

---

## Disk state (ep0/ep32 in `runs/so101_phase4_v5/`)

Smoke セッション中に ep0/ep32 の annotation + manifest を smoke 用の edit-derived run_hash で上書きした。セッション内で auto-pipeline 値に復元済み。

| Episode | 復元後 run_hash |
|---------|----------------|
| ep0 (`episode_000000__*`) | `sha256:e350611063945b4e1bce196aec7cd05162af51ff7ad6a82f854af9d081f0fb7d` |
| ep32 (`episode_000032__*`) | `sha256:834aa84279bd717f49a0a127e66b7be5001c9052c3b0fef3e35fd0ceadef89a1` |

確認方法: `cat runs/so101_phase4_v5/episode_000000__*/manifest.json | python3 -c "import json,sys; m=json.load(sys.stdin); print(m['run_hash'])"` が上記 SHA を返すこと。

サーバーテスト 112/112 green (復元後確認済)。

---

## Parking lot

### "Human hand video viewer" (新 sub-project)

ユーザーリクエスト (2026-05-15): 手の動きを動画で確認できる専用ページが欲しい。現行の RunViewer は annotation/boundary の静的表示に特化しており、hand pose overlay や depth warp overlay は未対応。

- 要件: まだ未定義。新セッションで spec から始める。
- 参考: `feat/hand-pipeline` (commit `4c51468`) に hand pose + depth pipeline が入っている。

### TEST-GAP: frozen `tests/fixtures/` snapshot

現在 `tests/server/test_edit_repo.py` と `test_edit_short_circuit.py` は `tmp_runs_root_loadable` fixture が `runs/so101_phase4_v5/` の実 ep0/ep32 ディレクトリをコピーして使う。

問題: ep0/ep32 が smoke 編集で汚れると fixture コピーも汚れてテストが落ちる (今回の事象)。

長期改善案: `tests/fixtures/` にミニマル run dir スナップショット (JSON ファイル数個) をコミットし、`tmp_runs_root_loadable` はそこからコピーするよう変更。実データへの依存を断ち切れる。ただしスナップショットのスキーマ追従が必要。

---

## Smoke plan / findings summary

詳細: `docs/superpowers/plans/2026-05-14-phase5-b-r1-ui-smoke-plan.md` §7 (Findings Summary)

---

## 次のセッションへ

- r2 以降 (boundary drag, reviewed toggle, object relabel) は未着手
- "Human hand video viewer" を spec 化するなら新セッションで
- TEST-GAP の frozen fixture 対応は任意のタイミングで
