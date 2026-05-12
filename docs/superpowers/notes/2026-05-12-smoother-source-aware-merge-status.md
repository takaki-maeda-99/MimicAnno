# Phase 4 smoother source-aware merge — 現状サマリ

Date: 2026-05-12
Branch: `feat/phase4-smoother-source-aware-merge`
Status: spec/plan 完了 → 実装着手前

---

## 1. 経緯

- Phase 4 finer-segmentation (#5 マージ済み, 2026-05-11)
  - `detect_gripper_zero_crossing` (ZC boundary detector) を opt-in で追加
  - SO101 23 ep の T8 検証で **mean 3.57 ZC candidates/ep** を出した
- しかし最終 annotation の segment 数は **mean 2.78/ep**、spec exit criteria
  (`seg ≥ 3 を 22/23 ep`、`seg ≥ 5 を 20/23 ep`) を未達
- 原因切り分け (`notes/2026-05-11-so101-phase4-v4-results.md`):
  - ZC は出ているが、Phase 4 smoother の Op 1 `_merge_same_label` が VLM の
    同一 phase 隣接 segment (例: 連続 `approach_object`) を collapse して
    境界を消していた
  - 23 ep 中 **17 ep で merge_same_label op が発火**
- ボトルネックは ZC detector ではなく **smoother** にあると確定
  (memory: `project_smoother_bottleneck.md`)

---

## 2. 方針

- **短期 (本 sub-project)**: smoother に "特定 boundary source を含む境界は
  merge しない" hint を入れる (source-aware `_merge_same_label`)
  - 既定値 `()` で完全な後方互換
  - SO101 では `gripper_zero_crossing` を preserve に設定して T9 再走
- **中期 (別 spec)**: VLM phase enum の細分化
  (`approach_object` → `pre_grasp_approach` / `post_grasp_approach` 等)
- **将来 (別 spec)**: hamer (手 pose) / UniDAC (depth/contact) を新 boundary
  source として統合 — 本 sub-project の preserve_sources は tuple 一般形に
  しておくので、統合 PR は YAML 追加のみで完結

---

## 3. ドキュメント

| 種類 | パス | 状態 |
|---|---|---|
| 仕様 | `docs/superpowers/specs/2026-05-12-phase4-smoother-source-aware-merge-design.md` | draft 完成 (§2.5 future sources 追加済) |
| 計画 | `docs/superpowers/plans/2026-05-12-phase4-smoother-source-aware-merge-plan.md` | draft 完成 (T8a 補強済) |
| 既存知見 (T8) | `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` | 完了済 |

---

## 4. 実装する機能 (全列挙)

### 4.1 Config レイヤ (`mimicanno/config.py`)

- `SmootherConfig` に新フィールド追加:
  ```python
  merge_same_label_preserve_sources: tuple[str, ...] = ()
  ```
- `SmootherConfig.to_dict()` の **conditional emit**: フィールドが empty の
  ときはキーを出さない (既存 v3/v4 run の `config_hash` を破壊しないため)
- `load_smoother_config_yaml` 拡張:
  - `valid_top_keys` に `merge_same_label_preserve_sources` を追加
  - YAML 値の型検証 (list of str)、不正値は `SmootherConfigInvalid`
- YAML round-trip 保証 (loader → to_dict → loader で同値)

### 4.2 Smoother ロジック (`mimicanno/smoother.py`)

- `_merge_same_label` / `_do_one_merge_round` のシグネチャに
  `config: SmootherConfig` を追加 (`_merge_short` / `_viterbi_relabel` と
  同じ形式)
- 新ヘルパ `_boundary_is_preserved(left, right, preserve)`:
  - `preserve` が空なら常に False (既定パスで分岐ゼロ)
  - `left.end_boundary.sources` と `right.start_boundary.sources` の和集合と
    `preserve` の交差を判定
- merge 判定で True なら当該ペアを **skip**
- `apply_smoothing` から Op 1 / Op 2 後 / Op 3 後 (smoother.py:582, :591,
  :604) の全 `_merge_same_label` 呼び出しに config を伝搬
- ループ収束は変わらず保証される (preserve は単に merge を抑制するだけ)
- DEBUG ログ: preserved skip 回数 (info ではなく debug)
- `_merge_short` / `_viterbi_relabel` は **本 sub-project では変更しない**
  (spec out of scope)

### 4.3 設定ファイル

- 新規 YAML: `mimicanno/configs/smoother/so101_zc_preserve.yaml`
  ```yaml
  min_segment_duration_sec: 0.30
  viterbi_enabled: true
  lambda_forbidden: 0.5
  merge_same_label_preserve_sources:
    - gripper_zero_crossing
  ```

### 4.4 バッチ実行基盤

- `scripts/batch_so101_phase4.sh` に `SMOOTHER_CONFIG` env を読み取って
  `--smoother-config "$SMOOTHER_CONFIG"` を CLI へ透過するパッチ
  (env 未指定なら従来挙動と byte-identical)
- 新規 `scripts/batch_so101_phase4_v5.sh` (v4 と同パターン、output が
  `runs/so101_phase4_v5/`、SMOOTHER_CONFIG をセット)

### 4.5 テスト

#### 単体: `tests/test_config.py`
- `SmootherConfig()` の `to_dict()` が現状 v4 と完全一致 (キー emit なし)
- 非空 tuple を渡したとき key 出力 + list 変換確認
- YAML round-trip
- 不正値 (list-of-non-str 等) で `SmootherConfigInvalid`

#### 単体: `tests/test_smoother.py` (新規 7 ケース)
1. default = legacy (preserve = ()) で既存挙動
2. single source preserve (= ZC) で merge 抑制
3. multi source preserve (intersection 判定)
4. non-matching source (`hand_motion`) は merge される
5. Op 2 後 re-merge: `_merge_short` 由来の新 pair も preserve でなければ merge
6. 3 連続同一 phase + 中央 boundary 1 個だけ preserve → `[A, A·A merged]`
7. chained preserve: 全 boundary preserve → どれも merge されない

#### 統合
- 後方互換 spot check: v3 / v4 既存 run を 1 ep だけ再走し、annotation.json と
  `config_hash` が完全一致 (diff 0)
- T9 batch: SO101 23 ep フル再走 → `runs/so101_phase4_v5/`

### 4.6 検証 (T9, exit criteria)

| 指標 | T8 v4 (現状) | T9 v5 目標 |
|---|---|---|
| mean ZC cands/ep | 3.57 | 3.57 (不変) |
| mean segs/ep | 2.78 | **≥ 4.0** |
| seg ≥ 3 | 11/23 | **≥ 18/23** |
| `merge_same_label` 発火 ep | 17/23 | **≤ 5/23** |
| ep10 が 1 segment | ✓ | ✓ |
| ep31 (5 seg) 維持 | ✓ | ✓ |

### 4.7 メモ / notes 更新
- `docs/superpowers/notes/2026-05-12-so101-phase4-v5-results.md` に T9 集計
- memory:
  - `project_smoother_bottleneck.md` を outcome に応じて閉じる/書換
  - 結果次第で `project_phase4_v5_shipped.md` を追加

---

## 5. 本 sub-project の **out of scope**

明示的に切り離した項目 (別 spec 行き):

- VLM phase enum の細分化 (`approach_object` 等の粒度向上)
- `_merge_short` / `_viterbi_relabel` の source-aware 化
- ZC detector / boundary fusion 側の変更
- **hamer / UniDAC 統合** — 別リポで動作確認済みだが MimicAnno への統合は
  未着手。本 sub-project の preserve_sources を tuple 一般形にしておく
  ことで将来の統合 PR は (a) BoundaryCandidate emit、(b) YAML に source 名
  追加、の 2 点で完結する設計にしている (spec §2.5)
- source 文字列の constants 化 (`mimicanno/constants.py` へ集約)

---

## 6. タスク順序 (plan §2 抜粋)

T1 → T2 → T3 → T4 → T5 → T6 → T7 (後方互換 spot check) → **T8a (batch
script パッチ)** → T8 (T9 batch) → T9 (集計・memory) → T10 (follow-up 判定)

各 task は TDD (failing test → 実装 → green) で 1 task = 1 commit。

---

## 7. リスク

- **Viterbi 段で再 collapse**: Op 3 が phase を同一に揃え直す → 直後の
  `_merge_same_label` で再 merge を試みる。boundary source は変わらないので
  preserve は機能するはず。T9 results で Op 3 後の merge 回数を計測予定
- **VLM 粒度問題は未解決**: 表層対処であり中期で別 spec
- **source 名のハードコード**: YAML と spec の 2 箇所のみ。constants 化は将来 task

---

## 8. 直近のネクストアクション

T1 (`SmootherConfig` field 追加) から TDD で着手。autonomy window 内
(Phase 5 directive 2026-04-30 →) のため、user 介入なしで T1-T10 を自走可能。
