# Phase 4 smoother source-aware merge — implementation plan

Date: 2026-05-12
Status: draft
Spec: [`../specs/2026-05-12-phase4-smoother-source-aware-merge-design.md`](../specs/2026-05-12-phase4-smoother-source-aware-merge-design.md)
Branch: `feat/phase4-smoother-source-aware-merge` (current)

---

## 0. ゴール

spec §6 の exit criteria を満たす:

1. 新規 7 単体テスト + 既存 smoother テスト 100% green
2. T9 (SO101 23 ep, ZC + preserve_sources=`gripper_zero_crossing`) で
   mean segs/ep ≥ 4.0、seg ≥ 3 が 18/23 以上
3. `merge_same_label_preserve_sources=()` の既定で T8 v4 の
   `config_hash` と segment 数が完全一致
4. 既存 Phase 1–3 / v3 run の `config_hash` も不変

「hamer / UniDAC を将来 source として追加する」は本 plan のスコープ外
(spec §2.5 参照)。今 plan で実装する preserve_sources は tuple 一般形なので、
将来の detector PR は YAML への source 名追加のみで完結する。

---

## 1. 原則

- **既定で byte-identical**: `merge_same_label_preserve_sources=()` のとき
  既存 v3/v4 run の `config_hash` と segment 数が完全一致すること。
- **TDD**: 各タスクは「失敗するテスト → 実装 → green」の順。
- **1 task = 1 commit** (PR-able 単位)。
- **検証は uv 経由** (`uv run pytest ...`, `uv run mimicanno ...`)。
- ZC source 文字列は `boundaries.py:130` で `"gripper_zero_crossing"` (確認済み)、
  YAML / spec の表記と一致。

---

## 2. タスク分解

| # | タスク | 出力 | 依存 |
|---|---|---|---|
| T1 | `SmootherConfig.merge_same_label_preserve_sources` field 追加 + `to_dict` の conditional emit (empty 時は emit しない) | `mimicanno/config.py`, unit test | - |
| T2 | YAML loader 拡張 (`load_smoother_config_yaml`) + `valid_top_keys` 更新 + 不正値テスト | `mimicanno/config.py`, `tests/test_config.py` | T1 |
| T3 | `_merge_same_label` / `_do_one_merge_round` シグネチャに `config` を追加し、`_boundary_is_preserved` ヘルパで preserve 判定 | `mimicanno/smoother.py` | T1 |
| T4 | `apply_smoothing` から Op 1 / Op 2 後 / Op 3 後の `_merge_same_label` 全呼び出しに config を伝搬 | `mimicanno/smoother.py` | T3 |
| T5 | 新規 smoother 単体テスト 7 ケース (spec §5.1) を追加 | `tests/test_smoother.py` | T3, T4 |
| T6 | `mimicanno/configs/smoother/so101_zc_preserve.yaml` を追加 (preserve = `gripper_zero_crossing`) | YAML 1 本 | T2 |
| T7 | 後方互換 spot check: 既存 v3/v4 run を再走し、`config_hash` と annotation.json が完全一致 | テスト結果 (CLI run + diff) | T1-T6 |
| T8a | `batch_so101_phase4.sh` に `SMOOTHER_CONFIG` env → `--smoother-config` 透過を追加 (現状 ZC は通るが smoother config 経路が無い) | scripts/ patch | T6 |
| T8 | T9 batch: SO101 23 ep を ZC + preserve YAML で再走 → `runs/so101_phase4_v5/` (新 `batch_so101_phase4_v5.sh` を v4 と同じパターンで作成) | スクリプト + run output | T8a |
| T9 | 結果集計と exit criteria 判定 → `notes/2026-05-12-so101-phase4-v5-results.md` 作成、memory 更新 | notes + memory | T8 |
| T10 | exit criteria 未達なら次手 (例: smoother min_segment_duration_sec 緩和の追加 spec) を提案 | follow-up spec の有無 | T9 |

---

## 3. 各タスクの詳細

### T1: SmootherConfig field 追加

**目的**: `merge_same_label_preserve_sources: tuple[str, ...] = ()` を
`SmootherConfig` に追加し、`to_dict()` で empty 時は emit しない。

**手順** (TDD):

1. `tests/test_config.py` に新規テスト:
   - **byte-equivalence**: `SmootherConfig().to_dict()` の dict が
     現状の v4 と key-by-key 完全一致 (新キーなし)
   - 非空 tuple を渡したとき key が含まれ tuple→list に変換される
   - **hash parity**: `compute_config_hash(legacy)` ==
     `compute_config_hash(default)` を直接 pin
2. `mimicanno/config.py::SmootherConfig` に field を追加 (frozen dataclass)
3. `to_dict` の該当箇所で `if self.merge_same_label_preserve_sources:` ガード

**Verify**: `uv run pytest tests/test_config.py -q` green。

### T2: YAML loader 拡張

**目的**: smoother YAML の `merge_same_label_preserve_sources:` キーを読む。

**手順**:

1. テスト追加:
   - YAML round-trip (loader → to_dict → loader で同値)
   - list of non-str → `SmootherConfigInvalid` raise
   - **未指定 (旧 YAML) → `()` のまま** (旧 run の互換)
2. `load_smoother_config_yaml` の `valid_top_keys` に `merge_same_label_preserve_sources`
   を追加し、raw 側の型検証を実装

**Verify**: `uv run pytest tests/test_config.py -q`、不正値テスト含めて green。

### T3: `_merge_same_label` の source-aware 化

**目的**: spec §3.2 の `_boundary_is_preserved` を実装。

**手順**:

1. `tests/test_smoother.py` で **先に** 失敗するテストを 2 ケース書く
   (新規 10 ケースの 2, 4 をここで先行 — preserve あり/なし)
2. `smoother.py` の `_merge_same_label` / `_do_one_merge_round` シグネチャに
   `preserve: frozenset[str] = frozenset()` を追加
   (full `SmootherConfig` ではなく抽出済み frozenset のみを渡す方針 — spec §3.4)
3. helper (新規; smoother.py に追加):
   ```python
   def _boundary_is_preserved(
       left: SubtaskSegment,
       right: SubtaskSegment,
       preserve: frozenset[str],
   ) -> bool:
       if not preserve:
           return False
       shared = set(left.end_boundary.sources) | set(right.start_boundary.sources)
       return bool(shared & preserve)
   ```
   schema.py:80-100 で `BoundaryRef.sources: list[str]` を保持していることを
   spot check 済 (2026-05-12 確認)。
4. merge 判定で `_boundary_is_preserved` が True なら skip

**Verify**: 先行 2 ケースが green。

### T4: `apply_smoothing` から伝搬

**目的**: spec §3.4 — **三箇所すべて** (初回 Op 1 含む) の
`_merge_same_label` 呼び出しに `preserve` を渡す。

**手順**:

1. `apply_smoothing` 入口で
   `preserve = frozenset(config.merge_same_label_preserve_sources)` を構築
2. `smoother.py:582` (初回 Op 1)、`:591` (Op 2 後)、`:604` (Op 3 後) の
   全呼び出しに `preserve=preserve` を渡す
3. `grep -n "_merge_same_label(" mimicanno/smoother.py` で漏れ無確認
4. `_merge_short` / `_viterbi_relabel` は本 plan では変えない
5. 末尾で「typo 警告」 (spec §3.5): 一度も観測されなかった preserve 文字列を
   `logging.getLogger(__name__).warning(...)` で通知

**Verify**: 既存 smoother テスト全部 green (`uv run pytest tests/test_smoother.py -q`)。

### T5: 単体テスト 10 ケース

**目的**: spec §5.1 の 10 ケースを完全実装。

ケース (spec §5.1 番号と対応):

1. default = legacy 挙動 (preserve = ())
2. single source preserve (= ZC) — T3 で先行済みなら拡充
3. multi source preserve (intersection 判定)
4. non-matching source (`hand_motion`) は merge される — T3 先行
5. Op 2 後 re-merge: `_merge_short` 由来の新 pair は preserve 対象でない限り merge
   (fixture 作成は手間 — `min_segment_duration_sec` を意図的に下げて
   sub-threshold な segment を構築)
6. 3 連続同一 phase + 中央 boundary 1 個だけ preserve (current-impl property、
   pass order 依存をコメントで明記)
7. chained preserve: 全 boundary preserve → どれも merge されない
8. **multi-round 収束**: preserve skip された pair が後続 round でも
   一貫して skip され、`rounds` カウンタが正しい値で停止
9. **invariant 保持**: 結果が `_assert_segment_invariants` を pass
10. **Op 3 後 preserve**: Viterbi が phase を揃えた直後の `_merge_same_label`
    でも preserve_sources が効く

**Verify**: `uv run pytest tests/test_smoother.py -k preserve -v` で 10 件 green。

### T6: SO101 用 YAML

**ファイル**: `mimicanno/configs/smoother/so101_zc_preserve.yaml`

```yaml
# Phase 4 smoother: SO101 finer-segmentation profile.
# Pairs with mimicanno/configs/boundary/so101_zero_crossing.yaml.
# spec: docs/superpowers/specs/2026-05-12-phase4-smoother-source-aware-merge-design.md
min_segment_duration_sec: 0.30
viterbi_enabled: true
lambda_forbidden: 0.5
merge_same_label_preserve_sources:
  - gripper_zero_crossing
```

**Verify**: `uv run python -c "from mimicanno.config import load_smoother_config_yaml; ..."` で
ロード成功。

### T7: 後方互換 spot check

**目的**: spec §6 exit criteria 3, 4 — 既定値で既存 run が byte-identical。

**手順**:

1. 既存 v3 run の YAML で `mimicanno annotate` を 1 ep だけ再走
2. annotation.json の `config_hash` と segment 列が pre-PR と完全一致を diff で確認
3. v4 (ZC 有効) も同様

**Verify**: diff 0 件。

### T8a: batch script に smoother-config を通す

**目的**: 現 `batch_so101_phase4.sh` は `BOUNDARY_CONFIG` env のみ
`--boundary-config` に渡している (grep 確認済)。smoother config 経路が
無いので、`SMOOTHER_CONFIG` env を見て `--smoother-config "$SMOOTHER_CONFIG"` を
オプションで付与するパッチを当てる (空のとき従来挙動)。

そのうえで `scripts/batch_so101_phase4_v5.sh` を **`batch_so101_phase4_v4.sh`
と同じパターン** (env を export して `batch_so101_phase4.sh` を exec する
ラッパー) で作成 — diff が最小で review しやすい:

```bash
export RUNS_ROOT="$REPO/runs/so101_phase4_v5"
export BOUNDARY_CONFIG="$REPO/mimicanno/configs/boundary/so101_zero_crossing.yaml"
export SMOOTHER_CONFIG="$REPO/mimicanno/configs/smoother/so101_zc_preserve.yaml"
exec bash "$REPO/scripts/batch_so101_phase4.sh"
```

**Verify**: `SMOOTHER_CONFIG=""` で v4 と byte-identical な CLI コマンドが
組まれることをドライラン (`bash -x`) で確認。

### T8: T9 batch (SO101 23 ep)

**コマンド**:

```bash
mimicanno annotate \
  --boundary-config mimicanno/configs/boundary/so101_zero_crossing.yaml \
  --smoother-config mimicanno/configs/smoother/so101_zc_preserve.yaml \
  --output runs/so101_phase4_v5/ \
  ... (T8 v4 と同じ episode list)
```

**注**: T8 v4 のバッチスクリプトを再利用、output dir のみ差し替え。
3 GPU 並列、ep0-ep32。

### T9: 結果集計

**ファイル**: `docs/superpowers/notes/2026-05-12-so101-phase4-v5-results.md`

集計項目 (spec §5.3 の表):

| 指標 | T8 v4 | T9 v5 |
|---|---|---|
| mean ZC cands/ep | 3.57 | (期待 3.57) |
| mean segs/ep | 2.78 | (期待 ≥ 4.0) |
| seg ≥ 3 | 11/23 | (期待 ≥ 18/23) |
| `merge_same_label` 発火 ep | 17/23 | (期待 ≤ 5/23) |
| ep10 が 1 segment | ✓ | ✓ (cands=0 のはず) |
| ep31 (5 seg) 維持 | ✓ | ✓ |

memory 更新:
- `project_smoother_bottleneck.md` を outcome に応じて閉じる/follow-up へ書き換え
- 新規 `project_phase4_v5_shipped.md` を必要に応じて追加

### T10: follow-up 判定

- exit criteria 達成 → autonomy window 内なら次サブプロジェクト (VLM phase 細分化など) の spec へ
- 未達 → 原因切り分け (Viterbi 再 collapse 等) → 追加 spec ドラフト

---

## 4. 検証コマンド一覧

```bash
# 各タスク後
uv run pytest tests/test_config.py tests/test_smoother.py -q

# T7 後方互換
uv run pytest tests/integration -k "smoother or boundary" -q

# T8 batch
bash scripts/run_phase4_v5_batch.sh  # (T8 v4 スクリプト改変)

# T9 集計 (notes 中で結果生成)
uv run python scripts/summarize_phase4_run.py runs/so101_phase4_v5/
```

---

## 5. リスクと留意

- **Viterbi 再 collapse** (spec §7): Op 3 が phase を同一に揃え直し、
  その後の `_merge_same_label` で再度 merge を試みる。preserve 判定は
  boundary source ベースなので機能するはずだが T9 で要確認 (results note に
  Viterbi 後の per-ep merge 回数も出す)。
- **source 文字列のハードコード**: 当面 YAML + spec の 2 箇所のみ。
  constants 化は本 plan のスコープ外。
- **hamer / UniDAC 統合 PR が来たとき**: 本 plan の preserve_sources は
  tuple 一般形なので、その PR は (a) BoundaryCandidate emit、(b) YAML への
  source 名追加、の 2 点だけで完結。smoother 側コード変更ゼロを確認すること。
