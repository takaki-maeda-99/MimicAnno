# Phase 4 smoother: source-aware `_merge_same_label`

Date: 2026-05-12
Status: draft
Author: Claude (Opus 4.7) under Phase 5 autonomy directive (2026-04-30 →)

Related:
- `docs/superpowers/specs/2026-04-29-mimicanno-phase4-smoothing-design.md` (Phase 4 base spec)
- `docs/superpowers/specs/2026-05-10-phase4-finer-segmentation-design.md` §6.5 (ZC detector exit-criteria post-mortem)
- `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` (T8 root-cause analysis)
- `mimicanno/smoother.py::_merge_same_label`
- `mimicanno/config.py::SmootherConfig`

---

## 1. Motivation

T8 (SO101 23 ep, 2026-05-12) で Phase 4 finer-segmentation の ZC detector は
仕様通りに mean **3.57 candidates/ep** を生成したが、最終 annotation の
segment 数は mean **2.78/ep** に留まり、spec §6.5 の exit criteria
(`seg ≥ 3 を 22/23 ep`, `seg ≥ 5 を 20/23 ep`) を満たさなかった。

決定的証拠 (notes 2026-05-11-so101-phase4-v4-results §決定的証拠):

```
ep0  cands t=[1.36, 3.37, 5.82, 6.62] → final [0–6.62][6.62–10.07]
ep0  seg0 smoothing_ops=['merge_same_label'] phase=approach_object
```

つまり ZC が出した中間 3 boundary は smoother op 1 (`_merge_same_label`) が
VLM の同一 phase 隣接 segment を collapse することで消されている。23 ep 中
**17 ep で `merge_same_label` op が発火**しており、ZC detector の出力を
下流が"飲み込んで"いる。

VLM の phase 粒度 (`approach_object` 一括) を細分化する案 (notes 選択肢 1)
は phase enum を破壊する大改修になるため、**短期対処として smoother に
"特定 boundary source は merge してはいけない" hint を持たせる** (notes 選択肢
2) のが本 spec のスコープ。

## 2. Scope

In scope:
- `_merge_same_label` を boundary source-aware にする
- `SmootherConfig` に新フィールド `merge_same_label_preserve_sources: tuple[str, ...]` を追加
- YAML loader と `config_hash` への組み込み (後方互換を保つこと)
- 単体テスト + SO101 re-run (T9 と呼ぶ) による定量検証

Out of scope:
- VLM phase enum の finer 化 (中期 follow-up、別 spec)
- `_merge_short` / `_viterbi_relabel` の source-aware 化
- ZC detector / boundary fusion 側の変更

## 2.5. Future sources (hamer / UniDAC)

`merge_same_label_preserve_sources` は tuple of source strings として
一般化されており、ZC 以外の boundary detector が将来追加されたときも
YAML を増やすだけで preserve 対象にできる。現時点 (2026-05-12) で
統合候補となっている外部 detector は以下:

- **HaMeR (手 pose)**: 別リポ / 別環境で動作確認済み。MimicAnno への統合は
  これから。手 keypoint の速度/接近イベントを boundary candidate として
  emit する想定。仮の source 名: `hand_pose_keypoint` (確定は統合 PR で)
- **UniDAC (depth / contact)**: 同上、別リポで検証済み。depth/接触の
  立ち上がりを boundary に出す想定。仮の source 名: `depth_contact`

これらは本 spec のスコープ外 (boundary detector PR が別途立つ) だが、
preserve_sources 設計は最初から複数 source の tuple を受ける形に
しておくことで、統合時の smoother 側変更がゼロになる。各 detector の
統合 PR は (a) 新 BoundaryCandidate を emit、(b) SO101 ロボット profile の
YAML (`so101_full_preserve.yaml` 等) に当該 source 名を追加、の 2 点で
完結できる。

注: source 文字列の命名規約と constants 化は本 spec のスコープ外
(`mimicanno/constants.py` への集約は将来 task、§7 参照)。

## 3. Design

### 3.1 Config 追加

`mimicanno/config.py::SmootherConfig` に以下を追加:

```python
@dataclass(slots=True, frozen=True)
class SmootherConfig:
    min_segment_duration_sec: float = 0.30
    forbidden_transitions: tuple[tuple[str, str], ...] = (...)
    viterbi_enabled: bool = True
    lambda_forbidden: float = 0.5
    # NEW: boundaries whose ``sources`` intersect this set are preserved
    # by ``_merge_same_label`` (Op 1) even if the two adjacent segments
    # share the same phase. Default empty → fully backward-compatible.
    merge_same_label_preserve_sources: tuple[str, ...] = ()
```

- 既定値 `()` のとき従来挙動と完全一致 (config_hash も既存 run と同値)
- `to_dict()` には **non-empty のときだけ** キーを emit
  (空のときに emit すると既存 v3/v4 run の config_hash が変わる)
- YAML 側 key は `merge_same_label_preserve_sources` (snake_case でそのまま)
- `load_smoother_config_yaml` の `valid_top_keys` と raw 検証を更新

### 3.2 `_merge_same_label` の挙動変更

判定ロジック (`_do_one_merge_round` 内):

```python
# 既存
if i + 1 < len(segments) and segments[i].phase == segments[i + 1].phase:
    out.append(_merge_pair_same_label(segments[i], segments[i + 1]))
```

を、左 segment の `end_boundary.sources` と右 segment の
`start_boundary.sources` が `preserve_sources` と交差していたら merge を
スキップするように拡張:

```python
def _boundary_is_preserved(
    left_seg: SubtaskSegment,
    right_seg: SubtaskSegment,
    preserve: frozenset[str],
) -> bool:
    if not preserve:
        return False
    shared = set(left_seg.end_boundary.sources) | set(right_seg.start_boundary.sources)
    return bool(shared & preserve)
```

注: smoother.py:519-540 の `_assert_segment_invariants` は
`left.end_boundary.candidate_id == right.start_boundary.candidate_id` と
`time` の一致のみを保証し **`sources` の equality は保証しない** (boundary が
synthesize された場合に source set が片側だけ拡張されうる)。よって
preserve 判定では **必ず union** を取る。これは「どちらかの側で preserve
対象 source が観測されたなら境界を保持する」という保守的な意味付け
(false positive 寄りで安全側)。

`_merge_same_label` シグネチャは変えず、`SmootherConfig` を引数に追加する。
これは `_merge_short` / `_viterbi_relabel` が既に `config` を受け取って
いる形式に合わせる。

### 3.3 ループ収束

既存の `_merge_same_label` は「productive round が 0 になるまで」反復する。
boundary preserve により永久に merge できない pair が残るだけなので、
収束保証は変わらない (各 round は必ず len を減らすか 0 で終わる)。

### 3.4 全 `_merge_same_label` 呼び出しサイトへの伝搬

`apply_smoothing` は `_merge_same_label` を **三箇所** で呼ぶ:

1. 初回 Op 1 (`smoother.py:582`) — ここが本 spec の主対象 (T8 で発火)
2. Op 2 後 (`smoother.py:591`)
3. Op 3 (Viterbi) 後 (`smoother.py:604`)

これら 3 箇所すべてに同じ `config` (もしくはそこから抽出した
`preserve: frozenset[str]`) を渡す。

実装上は `apply_smoothing` の入口で
`preserve = frozenset(config.merge_same_label_preserve_sources)` を一度だけ
構築し、`_merge_same_label` / `_do_one_merge_round` には full config では
なく **`preserve` だけを渡す** (frozen dataclass の重さを避け、helper の
責務を最小化)。

`_merge_short` (Op 2) が短 segment を吸収して新たに同一 phase 隣接 pair を
作る場合は **新しい end/start boundary の sources が preserve に該当しなければ
merge する** という形になり、これは仕様上意図通り。

### 3.5 ログ / 監査

- `SmoothingSummary` への新指標は追加しない (config_hash 変化を最小化)
- ただし debug 用に `_merge_same_label` 内で "preserved skip" 回数を
  数えてログ出力 (INFO レベルではなく DEBUG) する
- annotation.json の segment レベルでは何も変わらない (merge されなければ
  そもそも `merge_same_label` op は付かない)
- **Source-name typo 防御**: `apply_smoothing` 終了時に、run 中で
  一度も観測されなかった `preserve_sources` 文字列があれば WARNING を
  出す ("preserve_sources contains 'xyz' but no boundary in this episode
  carried that source — possible YAML typo")。silent no-op を防ぐ
  (constants 化までの繋ぎ、§7 参照)

### 3.6 SO101 用 YAML

`mimicanno/configs/smoother/so101_zc_preserve.yaml` を新設:

```yaml
min_segment_duration_sec: 0.30
viterbi_enabled: true
lambda_forbidden: 0.5
merge_same_label_preserve_sources:
  - gripper_zero_crossing
```

source 名は `mimicanno/configs/boundary/so101_zero_crossing.yaml` が
emit する `BoundaryCandidate.sources` の値と一致させる必要がある。
T9 実行前に grep で確認すること。

### 3.7 Viterbi (Op 3) 後の振る舞い契約

preserve_sources は **boundary identity (source set) に対するルール**
であり、phase identity には関与しない。よって:

- Op 3 が隣接 segment の phase を同一に揃え直し、その後の Op 1 で再 merge
  が試みられても、その境界の `sources` が preserve に該当すれば skip される
- 逆に Viterbi が phase を変えて隣接 segment が非同一 phase になれば、
  そもそも Op 1 は当該ペアを merge 対象としない (preserve 判定に到達しない)

つまり Viterbi の挙動と preserve_sources は直交。T9 results note で
Op 3 後の merge 試行回数を計測して仮説検証する。

## 4. Backward compatibility

- `merge_same_label_preserve_sources` の既定値は `()`
- `SmootherConfig.to_dict()` で empty のときは emit しない →
  既存 v3/v4 run の `config_hash` と同値
- YAML loader: 未指定キーの動作は変わらない
- `_merge_same_label` のシグネチャ変更は internal helper のみ。
  unit test が直接呼んでいる箇所のみ更新

## 5. Test plan

### 5.1 単体テスト (`tests/test_smoother.py`)

新規ケース:

1. **default = legacy 挙動**: `merge_same_label_preserve_sources=()` で
   既存テストが全部通る
2. **single source preserve**: 2 segment が同一 phase だが間の boundary が
   `gripper_zero_crossing` を含む → merge されない
3. **multi source preserve**: 同上、boundary に複数 source がある場合の
   交差判定
4. **non-matching source**: 別 source (`hand_motion`) の boundary は merge
   される
5. **Op 2 後 re-merge**: `_merge_short` で新しく出来た pair が preserve
   対象 boundary でないなら merge される
6. **3 連続同一 phase + 中間 boundary 1 個だけ preserve**:
   `[A|A|A]` で中央 boundary だけ ZC source → 結果は `[A, A·A merged]` か
   `[A·A merged, A]` のどちらかになる。現実装は左→右 pass なので前者を
   期待値とするが、**この性質テストは "current-impl property" と明記**し、
   pass order を変えるリファクタが入った場合は test も更新する旨コメント
7. **chained preserve**: 全 boundary が ZC source → 全ペア merge されない
8. **multi-round 収束**: round 1 で preserve により skip された pair が、
   後続 round (Op 2 で別 segment 吸収後) に再判定されても挙動が一貫すること
9. **invariant 保持**: preserve により merge skip された結果に対し
   `_assert_segment_invariants` (smoother.py:519-540) が依然 pass
10. **Op 3 後の `_merge_same_label`**: Viterbi が adjacent phase を同一化
    した場合でも preserve_sources が効くこと (spec §3.7 契約)

### 5.2 設定テスト (`tests/test_config.py`)

- YAML round-trip (loader → to_dict → loader で同値)
- **未指定 (= 旧 YAML)** → `preserve_sources == ()` (旧 v3/v4 YAML 互換)
- 不正値: list of non-str → `SmootherConfigInvalid`
- `valid_top_keys` の更新が反映されているか
- **`to_dict()` byte-equivalence**: `SmootherConfig().to_dict()` の dict 内容が
  既存 v4 と完全一致 (新キーが emit されないこと、キー順序が変わらないこと)
- **`compute_config_hash` parity**: `compute_config_hash(legacy_cfg)` ==
  `compute_config_hash(SmootherConfig(merge_same_label_preserve_sources=()))`
  をユニットテストで直接 pin する (T7 の full CLI re-run より早く回帰検出)

### 5.3 統合テスト (T9 = SO101 23 ep re-run)

実行:
```bash
mimicanno annotate \
  --boundary-config mimicanno/configs/boundary/so101_zero_crossing.yaml \
  --smoother-config mimicanno/configs/smoother/so101_zc_preserve.yaml \
  --output runs/so101_phase4_v5/ ...
```

評価指標 (T8 比):

| 指標 | T8 v4 (現状) | T9 v5 目標 |
|---|---|---|
| mean ZC cands/ep | 3.57 | 3.57 (不変) |
| mean segs/ep | 2.78 | **≥ 4.0** (sim 4.83 に近付く) |
| seg ≥ 3 | 11/23 | **≥ 18/23** |
| `merge_same_label` 発火 ep | 17/23 | **≤ 5/23** (degraded ep のみ) |
| ep10 が 1 segment | ✓ | ✓ (cands=0 で不変) |
| ep31 (5 seg) 維持 | ✓ | ✓ |

## 6. Exit criteria

1. 全単体テスト (新規 7 ケース + 既存 smoother テスト) green
2. T9 で mean segs/ep ≥ 4.0、seg ≥ 3 が 18/23 ep 以上
3. `merge_same_label_preserve_sources=()` (= 既定) で T8 v4 を再実行して
   `config_hash` と segment 数が完全一致 (backward compat 回帰なし)
4. 既存 Phase 1–3 / v3 run の `config_hash` も不変
5. notes 2026-05-12-so101-phase4-v5-results.md (仮) に結果集計

## 7. Risks & follow-ups

- **Viterbi 段で再び collapse される可能性**: Op 3 は同一 phase に再
  relabel する可能性があり、その後の `_merge_same_label` で再 merge され得る。
  Op 3 は隣接 segment の phase を変えるだけで boundary source は変えない
  ので、preserve 判定はそのまま機能するはず。T9 で要確認。
- **VLM 粒度の根本問題は未解決**: ZC boundary 跨ぎで VLM が `approach_object`
  を返し続ける現象自体は残る。本 spec は表層対処であり、中期で VLM phase
  enum 改修 (別 spec) が必要。
- **`merge_same_label_preserve_sources` の YAML key 長**: 長くて読みづらいが、
  意味が明示的で alias を増やすほどではない。spec 名と一致させる。
- **boundary source の命名揺れ**: `gripper_zero_crossing` という string
  リテラルが detector ↔ smoother config の 2 箇所に登場する。constants 化は
  本 spec のスコープ外 (将来 task で `mimicanno/constants.py` 等に集約)。

## 8. Implementation order (for the plan)

1. `SmootherConfig` フィールド追加 + `to_dict` の conditional emit
2. YAML loader 拡張 + validation エラー
3. `_merge_same_label` / `_do_one_merge_round` シグネチャ変更 + 判定
4. `apply_smoothing` から config を伝搬
5. 単体テスト 7 ケース追加
6. `mimicanno/configs/smoother/so101_zc_preserve.yaml` 追加
7. T9 batch 実行 (3 GPU 並列、ep0-32)
8. notes に結果集計 + memory 更新
