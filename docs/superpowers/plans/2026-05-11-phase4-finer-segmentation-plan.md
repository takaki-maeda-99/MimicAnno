# Phase 4 finer segmentation — implementation plan

Date: 2026-05-11 (updated 2026-05-12)
Status: T1–T9 完了 / T10 は別 spec へ deferral（results note 参照）
Spec: [`../specs/2026-05-10-phase4-finer-segmentation-design.md`](../specs/2026-05-10-phase4-finer-segmentation-design.md)
Branch: `feat/phase4-finer-segmentation` (current, ahead of `main` by 0)

---

## 0. ゴール

spec §3 の方針（既存 detector を残し、`detect_gripper_zero_crossing` を opt-in で追加、YAML で全パラメータ調整可能）を実装し、SO101 23 episode で:

- mean segment count ≥ 3.0
- seg ≥ 3 の ep 数 ≥ 22/23
- ep10 segment 数 == 1
- 既存テスト 100% green / 既存 run_hash 不変

を満たす。

---

## 1. 前提と作業順序の原則

- **既存挙動を絶対に壊さない**: YAML 未指定 → `enabled=false` → 全 detector の振る舞いが byte-identical。
- **TDD**: 各 task は「失敗するテストを書く → 実装 → green」の順。
- **タスク単位でコミット**: 1 task = 1 PR-able commit。下流タスクが上流タスクを破壊しないこと。
- **検証は uv 経由** (`uv run pytest ...`, `uv run mimicanno ...`)。

---

## 2. タスク分解（TodoWrite 用）

| # | タスク | 出力 | 依存 |
|---|---|---|---|
| **T0** ✅ | **SO101 新スケール (max=60) で ZC sim 再走 → hyst 決定 → spec 更新** | `notes/2026-05-11-so101-zc-resim-new-scale.md`, `images/2026-05-11-ep0-zc-new-scale.png`, spec §2.3/§4.2/§5.2/§8 Q5 更新済 | (完了 — hyst=0.12 採用) |
| T1 | `ZeroCrossingConfig` dataclass + `BoundaryConfig.zero_crossing` フィールド追加（コードのみ、ロード無し） | `mimicanno/config.py`, unit test | T0 (hyst=0.12 確定) |
| T2 | YAML ローダー拡張 (`load_boundary_config_yaml`) + バリデーション | `mimicanno/config.py`, unit test | T1 |
| T3 | `BoundaryConfig.to_dict()` の config_hash 互換性（Option A: `enabled=false` で省略） | `mimicanno/config.py`, hash 不変テスト | T1 |
| T4 | `detect_gripper_zero_crossing` を `boundaries.py` に追加 | `mimicanno/boundaries.py`, unit test | - |
| T5 | `pipeline.py` で ZC detector を events に追加（`_WEIGHT_KEY_TO_SOURCE` も拡張） | `mimicanno/pipeline.py` | T1, T4 |
| T6 | `mimicanno/configs/boundary/so101_zero_crossing.yaml` を追加 | YAML 1 本 | T2 |
| T7 | 結合テスト: 合成 2 サイクル台形 signal で boundaries ≥ 3 / segments ≥ 4 | `tests/integration/test_phase4_zero_crossing.py` | T5, T6 |
| T8 | SO101 23 ep バッチ実行 → `runs/so101_phase4_v4/` 生成 + 比較レポート | スクリプト & `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` | T5, T6 |
| T9 | 既存テスト全 green 確認 + run_hash 不変 spot check | テスト結果 | T1-T5 |
| T10 | 結果が exit criteria 満たさない場合の調整ループ | hyper-param 微調整 | T8 |

---

## 3. 各タスクの詳細

### T1: ZeroCrossingConfig dataclass

**目的**: spec §4.2 の 7 フィールドを dataclass 化し、`BoundaryConfig` に組み込む。ロード経路はまだ触らない。

**実装** (`mimicanno/config.py`):

```python
@dataclass(slots=True, frozen=True)
class ZeroCrossingConfig:
    enabled: bool = False
    signal: Literal["gripper"] = "gripper"  # 将来拡張余地
    ref: str = "midpoint"                    # "midpoint" | "median" | "fixed:<float>"
    hysteresis: float = 0.05
    span_eps: float = 0.05
    merge_window_sec: float = 0.0
    weight: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "signal": self.signal,
            "ref": self.ref,
            "hysteresis": self.hysteresis,
            "span_eps": self.span_eps,
            "merge_window_sec": self.merge_window_sec,
            "weight": self.weight,
        }
```

`BoundaryConfig` に `zero_crossing: ZeroCrossingConfig = field(default_factory=ZeroCrossingConfig)` を追加。`with_defaults` も更新。

**テスト** (`tests/unit/test_boundary_config_loader.py` 拡張):
- `ZeroCrossingConfig()` のデフォルト値が spec §4.2 と一致
- `BoundaryConfig.with_defaults().zero_crossing.enabled == False`
- `ref` フィールドのパース: "midpoint", "median", "fixed:0.15" は accept、"fixed:abc" / "unknown" は別 task で reject（T2）

**完了条件**: `uv run pytest tests/unit/test_boundary_config_loader.py -k zero_crossing -v` green。

### T2: YAML ローダー拡張

**目的**: `--boundary-config some.yaml` で `zero_crossing:` セクションを正しく読めるように。

**実装** (`mimicanno/config.py:load_boundary_config_yaml`):

1. `_VALID_TOP_KEYS` に `"zero_crossing"` 追加
2. ローダー終盤に `if "zero_crossing" in raw:` 分岐を追加し、サブキーをバリデーション
3. `ref` が `"fixed:..."` のときは `:` 後の文字列を `float()` で parse、失敗時 `MimicAnnoError("boundary_config.invalid_value")`
4. `enabled` / 数値 / 文字列の型チェック、`hysteresis < 0` / `span_eps < 0` は reject

**テスト追加** (`tests/unit/test_boundary_config_loader.py`):
- 正常: 全フィールド入った YAML が `ZeroCrossingConfig` に乗る
- 一部省略: 省略フィールドはデフォルト値
- セクション欠落: 既存挙動 (enabled=False)
- 不正値: hysteresis=-0.1, ref="bogus", ref="fixed:abc" でそれぞれ `MimicAnnoError`
- 未知サブキー: `zero_crossing.foo: 1` で `MimicAnnoError`

**完了条件**: 上記テスト全 green。

### T3: config_hash 互換性（Option A）

**目的**: `enabled=false` のとき既存 run_hash を壊さない。

**実装**:

`BoundaryConfig.to_dict()` で:
```python
out = { ...既存... }
if self.zero_crossing.enabled:
    out["zero_crossing"] = self.zero_crossing.to_dict()
return out
```

**テスト** (`tests/unit/test_config_hash.py` 拡張):
- `BoundaryConfig.with_defaults()` の dict に `"zero_crossing"` キーが**ない**
- `BoundaryConfig` with `zero_crossing.enabled=True` の dict に `"zero_crossing"` が**ある**
- 既存 fixture 由来の config_hash 値が変更前後で完全一致（直接バイト比較 — 既存テストがあるなら流用）

**完了条件**: 既存 hash 関連テスト + 新テスト全 green。

### T4: detect_gripper_zero_crossing 実装

**目的**: spec §4.3 のアルゴリズムを `boundaries.py` に追加。

**実装** (`mimicanno/boundaries.py`):

- spec §4.3 の疑似コードをそのまま Python へ。`_resolve_ref(g, mode)` ヘルパで `midpoint/median/fixed:X` を処理
- `_merge_close_events(events, window)` は既存 `integrated_candidates` の merge を流用できれば不要だが、detector 単体で merge したい場合は新規ヘルパ（spec §4.2 の merge_window_sec ≠ BoundaryConfig.merge_window_sec の二段 merge になる点に注意）
- `source = "gripper_zero_crossing"`

**テスト** (`tests/unit/test_boundaries_zero_crossing.py` 新規):

```python
def _trapezoid(n_low, n_ramp, n_high, lo=0.05, hi=0.40):
    """ramp-up, plateau, ramp-down, ramp-up cycle...生成ヘルパ"""

def test_single_cycle_two_boundaries(): ...
def test_two_cycles_four_boundaries(): ...
def test_flat_signal_zero_boundaries(): ...
def test_shallow_excursion_below_hysteresis(): ...
def test_hysteresis_just_above_threshold(): ...
def test_ref_modes(): midpoint / median / fixed:0.15 で同 signal 異 ref
def test_merge_close_events(): merge_window_sec で 2 boundary が 1 に
def test_disabled(): enabled=False で空リスト
def test_linear_interpolation_subframe(): 交差時刻が frame*dt の倍数からずれる
def test_source_score_within_unit_interval(): score ∈ [0, 1]
```

**完了条件**: `uv run pytest tests/unit/test_boundaries_zero_crossing.py -v` 全 green、10+ テストケース。

### T5: pipeline.py 配線

**目的**: BoundaryConfig.zero_crossing.enabled=True なら events に追加。

**実装** (`mimicanno/pipeline.py:1258-`):

```python
events = list(detect_gripper_transition(gripper_s, fps=fps, ...))
if bcfg.zero_crossing.enabled:
    events.extend(detect_gripper_zero_crossing(gripper_s, fps=fps, cfg=bcfg.zero_crossing))
```

`_WEIGHT_KEY_TO_SOURCE` (定数 dict) に `"gripper_zero_crossing": "gripper_zero_crossing"` を追加し、`detector_weights` 構築時に拾えるように。weights dict 構築は `bcfg.weights.to_dict()` に加えて `if bcfg.zero_crossing.enabled: weights["gripper_zero_crossing"] = bcfg.zero_crossing.weight` で合流。

`pipeline.py` には Phase 1 と Phase 3 で 2 か所同等の events 構築コードがあるはず（grep で確認: line 369, 888, 1259 周辺）— **同じ修正を両方に入れる**。

**回帰テスト** (新規不要): 既存 `tests/integration/test_phase4_smoke.py` が `enabled=False` で従前通り pass することを確認。

**完了条件**: `uv run pytest tests/integration/test_phase4_smoke.py tests/integration/test_cli_boundary_config.py -v` 全 green。

### T6: SO101 用 YAML 配信

**実装**: `mimicanno/configs/boundary/so101_zero_crossing.yaml` を spec §5.2 の内容で作成。

**テスト**: T7 で結合的に検証（YAML 単体テストは不要 — loader テストで covered）。

### T7: 結合テスト（合成 signal で）

**目的**: SO101 動画+parquet を tests/ に入れずに、ZC 効果を end-to-end で検証。

**戦略**: `tests/fixtures/synthesize.py` に近い形で **gripper signal が明確な 2 サイクル台形** な合成 episode を作る。既存の `synthesize_aloha_episode` が gripper をどう生成しているか確認し、必要なら新規 helper `synthesize_so101_like_episode` を追加。

**テスト内容** (`tests/integration/test_phase4_zero_crossing.py`):

1. 合成 episode + ZC enabled YAML を `mimicanno annotate --target-phase 4` で投入
2. `boundaries.json: candidates` 長さ ≥ 3
3. `annotation.json: segments` 長さ ≥ 4
4. 同 episode を ZC 無し (default config) で回すと segments == 1 → 効果あり

**完了条件**: 新 integration test green、既存 integration 全 green。

### T8: SO101 23 ep バッチ実行

**目的**: 合成データで通っても実データで本当に効くか確認 (spec §6.5)。

**手順**:

1. `runs/so101_phase4_v4/` 出力先で 23 ep バッチ実行
   - 既存スクリプト `scripts/batch_so101_phase4_overlay.sh` を流用、`--boundary-config configs/boundary/so101_zero_crossing.yaml` を追加
2. 集計スクリプト (T8 で同梱) で v3 vs v4 比較:
   - segment count distribution (mean/median/min/max)
   - phase label diversity (unique phases per ep)
   - boundaries 数分布
   - ep10 が 1 segment のままか確認
3. 結果を `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` に記録
   - 集計表 + 代表 ep (ep0, ep10, ep24, ep31) の overlay 画像

**完了条件**: spec §6.5 / §7 の指標を満たす。満たさなければ T10 へ。

### T9: 既存テスト全 green + run_hash spot check

**手順**:

```bash
uv run pytest tests/ -x
```

加えて、既存 v3 run の `manifest.config_hash` が「同じ inputs + 同じ default config」で再走したときに変わらないことを確認:

1. v3 から 1 ep の inputs と config を取得
2. ZC 実装後のコードで `--target-phase 4` で再走
3. 出力 `manifest.config_hash` が v3 と一致

**完了条件**: 全テスト green、hash spot check 一致。

### T10: 調整ループ（→ 別 spec へ deferral, 2026-05-12 判断）

**結果**: T8 で「軽く下回る」ではなく「大きく外す」結果となった (mean_segs 2.78 vs 予測 4.83、seg≥3 11/23 vs 22/23)。
詳細と原因は `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` 参照。

ボトルネックは ZC detector 側ではなく **Phase 4 smoother `_merge_same_label` が VLM の同一 phase ラベル隣接 segment を collapse** することにある。本ブランチの spec は ZC detector 追加のみがスコープ (`boundaries.py` / `config.py`)。smoother や VLM labeler への変更は別 spec に切り出す。



~~T8 で指標不達の場合の調整候補（試す順）~~（本ブランチでは適用しない）:

1. `hysteresis` を 0.04 / 0.06 でリトライ
2. `ref: median` に変更
3. `merge_window_sec: 0.3` を試す（短セグ吸収）
4. weighted sum で ZC を支配的にするため `gripper`weight を下げて `zero_crossing.weight` を上げる
5. それでも不十分なら spec を改訂し新 task を起こす（boundaries.py 自体に手を入れる選択肢含む）

各試行で `runs/so101_phase4_v5/`, `v6/` … と分離。

---

## 4. 実装順の依存グラフ

```
T1 ──┬─→ T2 ─→ T6 ─┐
     ├─→ T3        ├─→ T7 ─→ T8 ─→ T10 (if needed)
T4 ──┴─→ T5 ───────┘            
                  └─→ T9 (parallel ok)
```

T1 と T4 は並列着手可能。T8 は実データ依存で時間がかかる（~30 分）ので、その間に T9 を回せる。

---

## 5. 検証チェックリスト（執行時）

- [ ] T1: ZeroCrossingConfig 単体テスト green
- [ ] T2: YAML loader 単体テスト green（正常 + 異常系）
- [ ] T3: config_hash 不変テスト green
- [ ] T4: ZC detector 単体テスト 10+ ケース green
- [ ] T5: 既存 Phase 4 smoke + boundary_config CLI test green
- [ ] T6: YAML ファイル commit 済み
- [ ] T7: 新規結合テスト green
- [ ] T8: SO101 23 ep バッチで spec §6.5 指標達成
- [ ] T9: `uv run pytest tests/` 全 green
- [ ] T9: run_hash spot check で v3 互換
- [ ] note ドキュメント (`2026-05-11-so101-phase4-v4-results.md`) 完成
- [ ] spec / plan / note の cross-link 確認

---

## 6. Open issues（plan レベル）

1. **`pipeline.py` の events 構築箇所が 3 か所ある可能性**（line 369/888/1259）。grep で確認の上、全て同じ修正を適用。
2. **`tests/fixtures/synthesize.py` の API**: gripper 信号を任意波形で差し替えできるか、それとも新規 helper が要るか実装時に決定（T7）。
3. **T8 の run_hash 衝突**: ZC enabled で同 inputs / 同 config を回すと毎回同じ canonical_name になり、既存 v4 出力を上書きする恐れ。`--force` フラグ存在を確認、なければ `--runs-root` を別に切る。
4. **spec §8 の merge_window_sec デフォルト**: 0 のままで Phase 4 smoother に任せるか、0.3 程度で detector 段階で吸収するか。**まず 0 で T8 を回し、必要なら T10 で 0.3 を試す**。
5. **T10 の改訂判断**: §3.2 の成功条件 (seg≥3 を 22/23 ep) を「軽く下回る」場合は hyper-param 調整、「大きく外す」場合は spec を改訂する（後者は別 spec を切る）。

---

## 7. 想定 LOC とレビュー粒度

- T1+T3: 30-50 LOC (config.py 内)
- T2: 50-80 LOC (loader 拡張)
- T4: 100-150 LOC (detector + ヘルパ + テスト)
- T5: 10-20 LOC (pipeline.py 3 か所修正)
- T6: 20 LOC (YAML)
- T7: 80-120 LOC (synth helper + test)
- T8: 50 LOC (集計スクリプト) + note md

合計 約 350-500 LOC。PR 1 本に収まる規模。
