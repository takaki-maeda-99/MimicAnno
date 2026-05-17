# U-A4 commander response — 司令塔回答 (2026-05-17)

This file answers the question posed in TODO.md `#### U-A4 status 2026-05-17 確認 — 司令塔判断 3 択` while the TODO itself is in flux (multiple sessions editing). Authoritative.

## 質問のおさらい

TODO は U-A4 について以下を確認:
- branch `feat/ua-4-mask-overlay` local-only、tip `e909069` (docs only)、impl commit ゼロ
- impl が 2 段階 stash に分散 (`stash@{1}` full 14 ファイル / `stash@{2}` partial 6 ファイル、`vlm_dumps.py` / `routes.py` / `VideoPlayer.tsx` で重複 → pop 衝突確定)
- main の `vlm_dumps.py` (PR #14) が rev3 spec と field 名 drift
- 3 択を司令塔に求めた:
  - A: 司令塔自身で fix-up
  - B: 新規 sub-Claude rev3 dispatch
  - C: 本セッションに継承

## 司令塔決定: **Option B' (B のサブセット)**

**既存の rev3 dispatch agent `a96a4c8b` の完了を待つ。**

### 理由

1. **B (新規 rev3 dispatch) は既に実行済** — 私が `a96a4c8b` を rev3 spec (`eb389ba`) + rev3 dispatch prompt (`e909069`) で立ち上げ済。司令塔セッション内、background、shared worktree、dispatch 後 ~40 分経過 (時点 2026-05-17 17:30)
2. **A / C は commander 原則違反** — 司令塔は「コード作業しない、dispatch 管理だけ」が決まり
3. **stash@{2}/@{3} は破棄候補** — rev3 前の旧 impl 由来。`a96a4c8b` は rev3 prompt 完全準拠で立ち上げているので、出力が landed すれば最もクリーン
4. **shared worktree の教訓** — 今回 isolation を付けなかったので agent と司令塔ワークスペースが衝突。次回 U-A4 を再 dispatch するなら `isolation: "worktree"` 必須 (U-A2/U-A5 は今回そうした)

### Option B' 採用後の commander 監視チェックリスト

- [ ] `a96a4c8b` 完了通知を待つ (通知が来たら自動で notify)
- [ ] 完了したら output report を読み:
  - branch `feat/ua-4-mask-overlay` の origin push 状態
  - test 通過 (backend + frontend + mypy strict)
  - §2 contract changes flag (rev3 spec を変えてないか)
  - shared worktree のゴミ (RunViewer.tsx 等の uncommitted) を agent がクリーンアップしたか
- [ ] PR body 雛形を作って `docs/superpowers/dispatch/2026-05-17-ua-4-pr-body.md` に保存
- [ ] `stash@{2}` `stash@{3}` を `git stash drop` で削除 (agent 出力が source of truth と確認後)
- [ ] frontend overlay の camera-match 動作確認 ([[feedback_sam3_use_external_cam]])

### 並行 follow-up (Option B' でも別途必要)

#### U-A3 schema drift fix (中優先度)

PR #14 で merged された `mimicanno/server/vlm_dumps.py` は rev3 §2.4 と field 名 / 値が一致しない:

| field | main の code (PR #14) | rev3 spec (eb389ba) |
|---|---|---|
| `kind` | `"planner" / "segment"` | `"planner" / "labeler"` |
| `call_id` planner | `"_planner/call_NNN"` | `"call_NNN"` |
| `call_id` segment | `"s_NNN/attempt_M"` | `"s_NNN__attempt_M"` |
| `segment_ordinal` / `attempt` / `frame_url` / `keyframe_urls` / `request_json` | 無し | 必須 |
| `failed` 判定 (segment) | `response.txt` missing or non-JSON | "later `attempt_M+1` exists" |

frontend `VlmPanel.tsx` (PR #14) は old schema 期待で動作中。判断:
- **(a)** PR #14 を rev3 に揃え直す (vlm_dumps.py + VlmPanel.tsx 両方修正、follow-up PR)
- **(b)** rev3 spec §2.4 を PR #14 実態に合わせて書き戻す (rev4)
- **(c)** U-A4 agent `a96a4c8b` が rev3 を読んで両者の整合性を取った PR を出してくる可能性 — 出力レビュー時に確認

推奨: **(a)** が筋。autonomy 閉のためユーザー承認待ち。

### 次の commander session への引継ぎ

- 本ファイルは TODO のフラックスから独立、安定参照可
- agent 完了通知後の処理手順は上記チェックリスト
- TODO への反映は flux 落ち着いてから一括で
