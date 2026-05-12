# Incident: Phase 5 A server commit landed on `feat/piper-portability` by mistake

Date: 2026-05-13
Reporter: Claude (Phase 5 A 主セッション)
Severity: medium (recoverable, branch state confused, no data lost)
Status: **RESOLVED 2026-05-13** — 並行 Piper セッションが Plan A を実行
(cherry-pick `5e9577d` → `feat/phase4-smoother-source-aware-merge` として
`79c2796`、`feat/piper-portability` を `8bb2d4e` に reset)。副作用として
`2026-05-13-yaml-vanish-during-reset-incident.md` 参照。

---

## TL;DR

私の Phase 5 A T2-T8 の実装コミット `5e9577d feat(phase5-a):
read-only persistence server (T2-T8 complete)` が、本来乗るべき
`feat/phase4-smoother-source-aware-merge` ではなく **`feat/piper-portability`**
に乗ってしまっている。データ損失なし、reflog で全 commit 把握可能。
修復方針 (3 案) について判断を仰ぎたい。

---

## どうなっているか

### branch 図

```
main (9b062b8)
 │
 ├── feat/phase4-smoother-source-aware-merge (HEAD: 9a82423)
 │     ├── e4f658e  feat(phase4): smoother source-aware merge  ← 私
 │     ├── 525e041  docs(phase5-a): spec + plan                ← 私
 │     ├── 0ec9c90  build(phase5-a): [server] extra            ← 私 (T1)
 │     └── 9a82423  docs(phase5-a): WIP handoff note           ← Piper セッションが立てた占有保護
 │                                                                (これは私の保護用に正しく置かれた)
 │
 └── feat/piper-portability (HEAD: 5e9577d) ← 今ここ
       ├── 8bb2d4e  feat(piper): port MimicAnno to Piper       ← Piper セッションの正規 commit
       │            (39 ep validation note + scripts + configs)
       │
       └── 5e9577d  feat(phase5-a): read-only persistence      ← ★ 私が間違えて
                    server (T2-T8 complete)                       Piper ブランチに置いた
```

### あるべき姿

```
feat/phase4-smoother-source-aware-merge
       ├── e4f658e  (smoother)
       ├── 525e041  (spec+plan)
       ├── 0ec9c90  (T1 extra)
       ├── 9a82423  (handoff note)
       └── ★ ここに 5e9577d 相当 (T2-T8 server) が cherry-pick されるべき

feat/piper-portability
       └── 8bb2d4e  (Piper のみ、シンプル)
```

---

## なぜそうなったか (reflog 由来の時系列)

```
HEAD@{14} … HEAD@{6}    Phase 4 smoother sub-project の作業 (T1-T10 完了、commit e4f658e)
HEAD@{5}                9a82423 を作成 (Piper セッションが私の WIP 保護のため)
HEAD@{4}                main へ checkout (← 私かツールが misroute、ここから事故開始)
HEAD@{3}                feat/phase4-smoother-source-aware-merge へ戻った
HEAD@{2}                checkout: feat/phase4-smoother-source-aware-merge → feat/piper-portability
                       ★ ここで Piper セッション (別 Claude / autonomy loop?) が
                         feat/piper-portability にスイッチした。
                         私のセッションは認識せず、untracked WIP
                         (mimicanno/server/*, tests/server/*) は untracked のまま
                         Piper ブランチに連れていかれた (untracked は switch で保持)
HEAD@{1}                8bb2d4e feat(piper) ← Piper セッションが Piper ブランチ上で正規 commit
HEAD@{0}                5e9577d feat(phase5-a) ← 私が「smoother branch だ」と思い込んで
                                                 untracked WIP を commit、Piper branch に着地
```

**根本原因**: 並行 Piper セッションが私と同じ作業ディレクトリの git HEAD を
動かしている事を私のセッションは検知していなかった。`untracked` ファイルは
checkout で持ち越されるため、`git status` の見た目だけでは
「自分のブランチに居る」感覚が変わらない。

教訓は memory [[feedback_handoff_conflict_check]] で記録済み (本セッションで追加)。

---

## 影響範囲

### 良い面

- `e4f658e` (smoother)、`525e041` (spec+plan)、`0ec9c90` (T1)、`9a82423` (handoff)
  は **`feat/phase4-smoother-source-aware-merge` ブランチで完全に保持**。失っていない。
- `5e9577d` のテストは全 green (1070 passed, mypy clean)。コード自体に問題なし。
- Piper の `8bb2d4e` も無傷で `feat/piper-portability` の親 commit に乗っている。

### 悪い面

- `feat/piper-portability` に server コードが混入している。
  もし Piper 作業者がこのブランチを参照していたら混乱の元。
- `feat/phase4-smoother-source-aware-merge` から見れば T2-T8 が抜けている状態。
- ローカル commit のみで origin には push されていない (`git branch -v`
  で `[ahead 1]` 表記、上流追跡なし)。**外部に出ていないため修復は purely local**。

---

## 修復案 (3 つ)

### 案 A: cherry-pick + reset --hard (Recommended)

```bash
git checkout feat/phase4-smoother-source-aware-merge
git cherry-pick 5e9577d                       # T2-T8 を smoother ブランチへ
git checkout feat/piper-portability
git reset --hard 8bb2d4e                      # Piper ブランチを Piper-only に戻す
```

- **pros**: 履歴が「あるべき姿」と一致、Piper ブランチがクリーン
- **cons**: `feat/piper-portability` に対する `reset --hard` は destructive。
  Piper 作業者が `5e9577d` を既に reference / push していると問題
- **リスク評価**: branch は `[ahead 1]` で origin に存在せず、Piper 作業者の
  最新 commit は `8bb2d4e` で本コミットの前。**おそらく安全**

### 案 B: cherry-pick だけ、reset しない

```bash
git checkout feat/phase4-smoother-source-aware-merge
git cherry-pick 5e9577d
# feat/piper-portability はそのまま、Piper 作業者が見たら適宜整理してもらう
```

- **pros**: destructive op ゼロ、Piper 作業者の判断を尊重
- **cons**: Piper ブランチに余分な commit (server コード) が乗ったまま。
  Piper 作業者が PR 出すときに `5e9577d` を除外する必要がある (interactive rebase 等)
- **おすすめ度**: 中

### 案 C: 何もしない (commit はそのまま、smoother work は untracked のまま)

- 現状を温存し、ユーザーが手動で整理する
- **おすすめ度**: 低 (server 実装が `feat/piper-portability` に乗っているので
  smoother branch から見ると T2-T8 が再度消失している状態)

---

## 確認したいこと

1. **Piper セッション** (`8bb2d4e` を作った別 Claude / 別作業者) はまだ
   active か? (active なら案 A の reset --hard は事前通知必要)
2. `feat/piper-portability` ブランチは origin に push 済みか? (今は local only)
3. 案 A の destructive op を進めて良いか、それとも案 B (cherry-pick のみ)
   で済ませるか

---

## 次のアクション (どの案でも共通)

修復後:
- `feat/phase4-smoother-source-aware-merge` で T9 (README) → T10 (smoke) →
  T11 (memory) の続きを進める
- Phase 5 A sub-project の完成 = autonomy window 内の次のマイルストーン
