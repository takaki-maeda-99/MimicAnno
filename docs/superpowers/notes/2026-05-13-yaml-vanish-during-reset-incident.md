# Incident: `git reset --hard` mid-batch made YAML files vanish, 16 ep failed

Date: 2026-05-13
Reporter: Claude (Piper セッション)
Severity: low (recoverable, no data corruption; lost ~50 min of GPU 3 batch progress)
Related:
- `docs/superpowers/notes/2026-05-13-server-on-piper-branch-incident.md` (上位インシデント、修復案 A を実行した直接の原因)

---

## TL;DR

上位インシデント (Phase 5 A server commit が Piper ブランチに誤配置) を
修復するため `git reset --hard 8bb2d4e` を実行。同時刻に GPU 3 で走らせていた
Piper v5 バッチが ep23 を起動した瞬間、**branch switch 中の working tree が
一瞬 piper YAML を持たない状態になり**、CLI argparse の
`--boundary-config <yaml>` が file-not-found で exit 2。残り 16 ep (ep23-38)
が連鎖的に同エラーで FAIL。

データ破壊なし。再走で完全回復可能。

---

## どうなったか (時系列)

```
00:39:31  GPU 1 batch start (ep0-19, v5: ZC + preserve_sources)
00:39:32  GPU 3 batch start (ep20-38, 同上)
00:43:15  GPU 3: ep20 OK
00:43:56  GPU 1: ep0 OK
00:46:23  GPU 3: ep21 OK
00:47:08  GPU 1: ep1 OK
00:49:36  GPU 3: ep22 OK ★ ここまで順調

(裏で私が上位インシデントの修復オペ:)
~00:49:40  git checkout feat/phase4-smoother-source-aware-merge
           ← working tree から piper_*.yaml が一瞬消える
           (smoother branch にこれらのファイルは存在しないため)
~00:49:40  git cherry-pick 5e9577d (T2-T8 server)
~00:49:45  git checkout feat/piper-portability
~00:49:45  git reset --hard 8bb2d4e
           ← piper_*.yaml が working tree に再出現

00:49:36  GPU 3 batch: ep23 が "starting" ログを吐いた直後に subprocess 起動
          → working tree から piper_zero_crossing.yaml が消えた瞬間と衝突
          → typer の Path(exists=True) チェックで弾かれる
          → exit 2

00:49:37〜00:49:47  ep24-38 も同様に連鎖 FAIL
                   (batch script は exit code を catch して次に進むので止まらない)
00:49:47  GPU 3 batch "done"
```

エラー本体:

```
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ Invalid value for '--boundary-config': File                                  │
│ '/misc/dl00/gayagaya/MimicAnno/mimicanno/configs/boundary/                   │
│  piper_zero_crossing.yaml' does not exist.                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

## なぜ GPU 1 batch は無事だったか

GPU 1 は ep2 を 00:47:08 に起動し 00:51:46 まで走行。git ops は
00:49:40〜00:49:45 の数秒間。GPU 1 の subprocess は ep2 の CLI argparse を
00:47 時点で済ませており、YAML 検証は通過済み (Path 解決後はモデルロード
等で YAML を再参照しない)。ep3 が起動するのは 00:51:46 で、その時点では
reset --hard 完了後 → YAML が再配置されているので問題なし。

GPU 3 だけ運悪く ep23 起動瞬間と git ops が **数秒のウィンドウで衝突**。

---

## 影響

### データ
- v5 完走 ep: 6/39 (ep0-2 from GPU 1, ep20-22 from GPU 3)
- v5 失敗 ep: 16 (ep23-38)
- GPU 1 は走行継続中、ep3-19 (17 ep) は未着手 → 残り順次完走予定

### 履歴 / リポジトリ
- 上位インシデントの修復自体は意図通り完了:
  - `feat/phase4-smoother-source-aware-merge`: T2-T8 server cherry-pick 完了 (`79c2796`)
  - `feat/piper-portability`: Piper-only に reset 完了 (`8bb2d4e`, origin と一致)
- データ破壊なし

### コスト
- GPU 3 の 12 分強 (00:39-00:49 のうち 3 ep 分は成果) + 立ち上げ 10 分 = 累計 ~25 分の GPU 時間
- 16 ep ぶんの再走必要 = +~60 分

---

## 修復 (実施済み)

GPU 0 (48 GB 空き) で ep23-38 の再走を起動 (00:54 頃):

```bash
RUNS_ROOT=runs/piper_phase4_v5 \
LOGS_DIR=logs/batch_piper_v5_retry \
BOUNDARY_CONFIG=mimicanno/configs/boundary/piper_zero_crossing.yaml \
SMOOTHER_CONFIG=mimicanno/configs/smoother/piper_zc_preserve.yaml \
GPU=0 START=23 END=38 bash scripts/batch_piper_phase4.sh
```

GPU 1 は引き続き ep3-19 を進めるので、両合わせて約 60 分後に v5 全 39 ep 揃う見込み。

---

## 教訓

1. **走行中のバッチがあるときに branch switch / reset --hard をしない**
   - working tree のファイル構成が一瞬でも変化する操作は、subprocess の
     CLI argparse / Path 検証と衝突する可能性
   - 安全な順序: バッチ完了 → branch ops、または branch ops → バッチ起動
2. **YAML のような小さい設定ファイルはバッチ起動時に temp copy しておく** という防衛案も
   ある (今回は対応していない、scope 外)
3. **batch_*.sh は exit code を catch して次 ep に進む設計**なので連鎖 FAIL が
   止まらない。良い面 (完走可能) もあるが、根本原因 (YAML 消失) を batch が
   検出できない悪い面もあった。CI 用途では「3 連続 FAIL で abort」 のような
   guard が欲しい
4. memory [[feedback_handoff_conflict_check]] / [[feedback_plan_before_implement]]
   とセットで読むと「並行作業の調整不足 → リカバリ操作で別の問題を引く」
   というパターンが明確になる

---

## 次のアクション

1. GPU 0 batch (ep23-38) と GPU 1 batch (ep3-19) の完了待ち (~60 分)
2. 全 39 ep 揃ったら task #6 (v4 vs v5 比較レポート追記) を実行
3. v5 で `merge_same_label` 発火率が 0 に近づき、mean segs/ep が 3+ に
   増えれば smoother spec の Piper 一般化が実証される
