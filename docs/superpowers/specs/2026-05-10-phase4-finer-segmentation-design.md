# Phase 4 finer segmentation: 短尺 episode で boundary が空になる問題の解消

Date: 2026-05-10 (initial draft)
Updated: 2026-05-11 (ZC approach replaces threshold-drop)
Status: Draft
Related:
- `2026-04-29-mimicanno-phase4-smoothing-design.md`（Phase 4 元仕様 / temporal smoothing）
- `2026-04-28-mimicanno-phase3-sam3-tracking-design.md`（Phase 3 / signals 上流）
- `docs/superpowers/notes/2026-05-06-vlm-mask-overlay-batch-results.md`（症状観測）
- `docs/superpowers/notes/images/2026-05-11-ep0-zc-sim.png` 他（本 spec の検証プロット）

---

## 1. 動機

SO101 23 episode の v3 バッチ (`runs/so101_phase4_v3/`) を Phase 4 まで通したところ、**全 episode が 1 segment に潰れる**現象が確認された。期待されていたのは「approach → grasp → transport → release」の複数 segment 構成。

現状の挙動（ep0 / ep5 / ep32 で同一）:

- `boundaries.json: candidates=[]`（boundary detector が一切発火しない）
- VLM labeler が全 frame を 1 segment 扱いし、`approach_object` を貼って終了
- Phase 4 smoother は 1 segment しか入力されないため何も切れない
- `mimicanno export` は 1 行の `mimicanno_segments` を出す → SARM 学習データとして使い物にならない

**目的**: 短尺 episode でも grasp / release を含む boundary が検出され、複数 segment に分解されるよう Phase 4 の **boundary 検出層を拡張**する。**既存 detector はそのまま残し、新検出器を opt-in で追加**することで、既存テストと長尺 episode の挙動を一切壊さない。

**非目的**:

- VLM labeler のプロンプト調整（別タスク、ユーザが手動で実施予定）。
- `fps.unresolvable` バグ修正（13 episode が Phase 1 で落ちる別件）。
- Phase 1-3 の出力フォーマット変更（不変を保つ）。
- temporal smoothing ロジック (Phase 4 元仕様) の改変。

---

## 2. 実データから判明した事実

**この節は spec drafting 中に SO101 23 episode の `signals.json` を実際に読んで得た観察。** Phase 4 の挙動仮説はこの観察に駆動される。

### 2.1 Gripper signal の統計（23 episode 全数）

```
ep   n    min    max    span   max|Δ|  |Δ|>0.30  |Δ|>0.10  |Δ|>0.05  zc
000  151  0.043  0.388  0.346  0.075   0         0         12        4
001  151  0.040  0.428  0.387  0.078   0         0         12        4
…
010  150  0.049  0.049  0.000  0.000   0         0         0         0    ← 壊れ ep
024  150  0.045  0.407  0.362  0.078   0         0         20        6
032  151  0.044  0.423  0.380  0.079   0         0         13        4
```

ここから読み取れる事実:

1. **max 単フレーム |Δgripper| = 0.06-0.08** が全 ep で観測される。現状しきい値 0.30 は **4-5 倍高すぎる**ため、どの ep でも detector が一切発火しない。
2. |Δ|>0.10 を満たすフレームは 23 ep プールで 17 個 (0.5%)、|Δ|>0.30 はゼロ。
3. **|Δ|>0.05 で初めて意味のある数 (10-20 events/ep) になる**。
4. ほぼ全 ep で gripper の **zero-crossings (中点を跨ぐ回数) = 4** (中央値)。これは「閉じる→開く→閉じる→開く」を意味し、**1 episode あたり 2 回の grasp/release サイクル**が含まれていることを示す。
5. ep10 は gripper が全く動いていない (span=0) → 収録失敗の可能性。これは boundary 検出してはいけないので 1 segment のままが正しい。

### 2.2 信号波形の構造

ep0 のプロット (`docs/superpowers/notes/images/2026-05-11-ep0-signals-v3.png`) から:

- gripper signal は **インパルス的 (sharp Δ) ではなく、なだらかな台形** で変化する。閉じる動作は ~10 frames (0.67s) かけて段階的に進行する。
- これは制御側の rate-limit を示唆 (|Δ| が 0.08 で頭打ち)。**インパルス性は完全に失われている**。
- 単フレーム Δ ベースの detector はクラスタ化された Δ ピーク列を「複数の boundary」として返す傾向があり、後段の merge が必要。
- 期待される segment 数は **5 前後** (idle / approach / grasp / transport / release を 2 周分)。

### 2.3 Zero-crossing シミュレーション（23 ep, 新スケール max=60）

⚠️ 初稿時点では旧スケール (max=100) で hyst=0.05 を採用していたが、**2026-05-11 に gripper_scale_max を 100→60 に再調整した**ため、本節は新スケールで再走した結果に書き換えた。再走の詳細: `docs/superpowers/notes/2026-05-11-so101-zc-resim-new-scale.md`

**Gripper 統計の変化**:

| 指標 | 旧 (max=100) | 新 (max=60) |
|---|---|---|
| mean span | 0.354 | 0.589 |
| pooled max \|Δ\| | 0.080 | 0.134 |

**Hyst sweep (新スケール)**:

| config | mean seg | median | seg≥3 | seg≥5 | min | max |
|---|---|---|---|---|---|---|
| **v3 baseline (旧 scale, threshold 0.30)** | 1.00 | 1.0 | 0/23 | 0/23 | 1 | 1 |
| ZC, hyst=0.05 | 4.91 | 5.0 | 22/23 | 21/23 | 1 | 7 |
| ZC, hyst=0.08 | 4.91 | 5.0 | 22/23 | 21/23 | 1 | 7 |
| ZC, hyst=0.10 | 4.83 | 5.0 | 22/23 | 20/23 | 1 | 7 |
| **ZC, hyst=0.12 (採用)** | **4.83** | **5.0** | **22/23** | **20/23** | 1 | 7 |
| ZC, hyst=0.15 | 4.52 | 5.0 | 22/23 | 17/23 | 1 | 7 |
| ZC, hyst=0.18 | 4.22 | 5.0 | 22/23 | 14/23 | 1 | 5 |
| ZC, hyst=0.20 | 3.91 | 4.0 | 21/23 | 11/23 | 1 | 5 |
| ZC, hyst=0.25 | 3.30 | 3.0 | 20/23 | 4/23 | 1 | 5 |

主な観察:

- **plateau は hyst ∈ [0.05, 0.15]** — この範囲では 22/23 ep が seg≥3。**中央値 hyst=0.12 を採用** (キャリブレーション余裕が最大、span の ~20%)。
- **手動 hyst=0.12 は Otsu 二クラス判別法と整合**: 全 SO101 36 ep の pooled gripper 分布に Otsu を適用すると threshold=0.334、cluster 統計から `0.5 × min_dist(Otsu, μ_cluster) = 0.119` および `0.25 × cluster_separation = 0.120` が得られ、sweep の plateau 中央と一致 (`2026-05-11-so101-otsu-justification.md`)。経験値ではなく data-driven 値として正当化される。
- **ep10 (span=0) は全 config で 0 boundaries** — `span_eps=0.05` ガードで壊れ ep を自然に除外。
- **ep23 のみ常に 2 boundaries (3 segments)**: 実際に 1 cycle しかない episode で正しい挙動。
- **ep29 は新スケールで取りこぼしが解消** (旧スケール hyst=0.10 では 4 boundary、新スケール hyst=0.12 では 6 boundary)。

### 2.4 設計への含意

- gripper signal の **zero-crossing を一次 boundary 検出量に**: cluster merge ロジック不要 (1 開閉動作 = 1 boundary)、threshold 依存が ref と hyst の 2 値だけに減る、span_eps で壊れ ep が自然に弾かれる。
- 単フレーム Δ ベースの既存 detector はそのまま残す: 長尺 / 高 fps episode で発火する可能性があり、回帰させたくない。**新 ZC detector は opt-in (`enabled: false` がデフォルト)**。
- eef_velocity 由来 detector は今回触らない。velocity の Δ も |Δ|max が 0.13 程度で 0.30 を超えないため別問題だが、本 spec のスコープ外。

---

## 3. 設計方針

### 3.1 既存 detector を残し、ZC detector を新規追加

`mimicanno/boundaries.py` に `detect_gripper_zero_crossing(gripper, fps, cfg) -> list[RawEvent]` を追加。`pipeline.py` で BoundaryConfig.zero_crossing の `enabled` フラグを見て、true なら events リストに追加する。

旧 `detect_gripper_transition` は変更しない。両方発火した場合は、既存の `integrated_candidates` の merge_window_sec で近接 event が自動 merge されるので衝突しない。

### 3.2 既存挙動の保護

- `BoundaryConfig.zero_crossing.enabled = false` が **デフォルト** → 全ての既存テスト・既存 run は config_hash 含めて完全不変。
- ZC を使う SO101 run は専用 YAML (`mimicanno/configs/boundary/so101_zero_crossing.yaml`) を明示的に渡す。
- ZC enabled のときも `gripper_transition` detector はデフォルト動作のまま (発火しないだけ)。weights から「両方を加算」できる構成。

### 3.3 段階性は廃止

旧 spec の「Phase 1: 絶対値しきい値の引き下げ → 不十分なら Phase 2」案は §2.3 のシミュレーション結果から **ZC 一発で目標達成可能**と判明したため廃止。本 spec は単一段階で完結する。

---

## 4. アルゴリズム: gripper zero-crossing detector

### 4.1 入力

- `gripper: np.ndarray (shape=[T], dtype=float)` — gaussian smoothed gripper signal（既存 pipeline の sigma=`smoothing_sigma_sec * fps` を継承）
- `fps: float`
- `cfg: ZeroCrossingConfig`

### 4.2 パラメータ

| field | type | default | 意味 |
|---|---|---|---|
| `enabled` | bool | **false** | 検出 on/off。false のときは空リストを返す（既存挙動と同等） |
| `signal` | str (`"gripper"`) | `"gripper"` | 将来 `"eef_velocity"` 等を選べる余地。現状 gripper 固定 |
| `ref` | str | `"midpoint"` | 参照値の決め方。`"midpoint"` = `(max+min)/2`、`"median"` = `np.median`、`"fixed:0.15"` = 固定値 |
| `hysteresis` | float | **0.12** | 反対側の振れ幅がこの値以上でないと次の交差を発火しない（ノイズ抑制）。SO101 new scale 前提。Otsu 二クラス判別で求めた cluster 統計から `0.5 × min_dist(Otsu, μ_cluster) = 0.25 × cluster_separation ≈ 0.12` と data-driven に導出 — `2026-05-11-so101-otsu-justification.md` |
| `span_eps` | float | **0.05** | `max - min` がこの値未満なら detector skip（壊れ ep 対策） |
| `merge_window_sec` | float | **0.0** | 連続する 2 boundary がこの間隔未満なら merge（0 = 無効）。短瞬間グリップ対策の任意機能 |
| `weight` | float | **0.5** | weighted sum に渡す重み（既存 `gripper_transition` と同名のソースを別キーで足す） |

### 4.3 検出ロジック（疑似コード）

```python
def detect_gripper_zero_crossing(gripper, fps, cfg) -> list[RawEvent]:
    if not cfg.enabled or gripper.size < 2:
        return []
    span = float(gripper.max() - gripper.min())
    if span < cfg.span_eps:
        return []                                # 壊れ ep スキップ

    ref = _resolve_ref(gripper, cfg.ref)         # midpoint / median / fixed:X
    events = []
    last_extreme = gripper[0] - ref              # 直近側に振れた最大絶対値（符号付き）
    last_side = np.sign(gripper[0] - ref) or 1.0

    for i in range(1, gripper.size):
        d = gripper[i] - ref
        s = np.sign(d)
        if s == 0:
            continue
        if s != last_side:
            if abs(last_extreme) >= cfg.hysteresis:
                # 線形補間で交差時刻を frame 内精度で
                a, b = gripper[i-1] - ref, gripper[i] - ref
                frac = a / (a - b) if (a - b) != 0 else 0.5
                t_cross = (i - 1 + frac) / fps
                score = float(np.clip(abs(last_extreme) / (span / 2), 0.0, 1.0))
                events.append(RawEvent(
                    frame=i, time=t_cross,
                    source="gripper_zero_crossing",
                    source_score=score,
                ))
                last_extreme = d
                last_side = s
            # else: 微小ノイズ交差は無視
        else:
            if abs(d) > abs(last_extreme):
                last_extreme = d

    if cfg.merge_window_sec > 0:
        events = _merge_close_events(events, cfg.merge_window_sec)

    return events
```

`source_score` は `|last_extreme| / (span/2)` でクリップ。深く振れた grasp ほど高 score になる。

### 4.4 既存パイプラインへの組み込み

`pipeline.py:1258-` の events 構築箇所に分岐を追加:

```python
events = list(detect_gripper_transition(gripper_s, fps=fps, ...))
if bcfg.zero_crossing.enabled:
    events.extend(detect_gripper_zero_crossing(gripper_s, fps=fps, cfg=bcfg.zero_crossing))
# ... 他 detector ...
```

`integrated_candidates(events, ..., weights=detector_weights, ...)` の `detector_weights` に `"gripper_zero_crossing": cfg.weight` を追加する。`merge_window_sec` (既存の BoundaryConfig.merge_window_sec, default 0.10s) によって、`gripper_transition` と `gripper_zero_crossing` が同じ箇所で同時発火しても自動 merge される。

---

## 5. 設定スキーマ (YAML)

### 5.1 BoundaryConfig 拡張

`mimicanno/config.py` の `BoundaryConfig` dataclass に `zero_crossing: ZeroCrossingConfig` フィールドを追加。`_VALID_TOP_KEYS` に `"zero_crossing"` を追加。

### 5.2 YAML 例

```yaml
# mimicanno/configs/boundary/so101_zero_crossing.yaml
# Phase 4 finer segmentation: SO101 (50 Hz, 10s episode) 用設定

# 既存セクション（変更なし — 旧 detector はそのまま）
thresholds:
  gripper_delta: 0.30
  velocity_valley: 0.05
weights:
  gripper: 0.5
  velocity: 0.25
  acceleration: 0.15
  action: 0.10
score_threshold: 0.30
merge_window_sec: 0.10

# 新セクション（Phase 4 finer-seg）
zero_crossing:
  enabled: true
  signal: gripper
  ref: midpoint
  hysteresis: 0.12          # SO101 new scale (max=60) plateau 中央。詳細: notes/2026-05-11-so101-zc-resim-new-scale.md
  span_eps: 0.05
  merge_window_sec: 0.0
  weight: 0.5
```

### 5.3 デフォルト (YAML 渡さない場合)

```yaml
zero_crossing:
  enabled: false        # ← デフォルト false なので何も起きない
  ...
```

### 5.4 config_hash への寄与

`BoundaryConfig.to_dict()` に `zero_crossing` を含めることで run identity が変わる。**enabled=false のときも dict には含めるが**、既存 run の hash 互換性のため:

- Option A: `enabled=false` のときは `to_dict()` で `zero_crossing` キー自体を出力しない（旧 hash と完全一致を維持）
- Option B: 常に出力（既存 run も再計算で新 hash になる → re-annotate 必要）

→ **Option A 採用**: 既存 v3 / Phase 1-3 の run_hash を壊さないため。`enabled=true` のときだけ `zero_crossing` ブロックが config_hash に入る。

---

## 6. テスト戦略

### 6.1 単体テスト (`tests/unit/test_boundaries_zero_crossing.py`)

- **basic**: 合成台形 signal (1 サイクル: 0→0.4→0) で 2 boundary が出ること
- **two_cycles**: 2 サイクル signal で 4 boundary
- **flat_skip**: 平坦 signal (span < eps) で 0 boundary
- **hysteresis**: 浅い振れ (< hyst) で発火しない、深い振れで発火する
- **ref_modes**: midpoint / median / fixed:X それぞれで期待 ref が使われる
- **merge_close**: merge_window_sec で近接 event が結合される
- **disabled**: `enabled=false` で空リスト

### 6.2 BoundaryConfig YAML ローダーテスト (`tests/unit/test_config_boundary_yaml.py` 拡張)

- `zero_crossing` セクション無しで既存挙動 (enabled=false)
- 全フィールド指定で正しく BoundaryConfig に乗る
- 不正値 (hysteresis < 0, ref 不明文字列) で `MimicAnnoError`
- 既存セクション (weights/thresholds) と共存しても他フィールドに影響なし

### 6.3 結合テスト (`tests/integration/test_phase4_so101_zero_crossing.py` 新規)

- SO101 ep0 fixture (動画 + parquet + task_text) で `annotate_episode --target-phase 4 --boundary-config configs/boundary/so101_zero_crossing.yaml` を回す
- assertion:
  - `boundaries.json: candidates` 長さ ≥ 3
  - `annotation.json: segments` 長さ ≥ 4
  - smoother 適用後の segment phase が同一値で埋め尽くされていない（≥2 ユニーク phase）

### 6.4 回帰テスト

- 既存の Phase 1/2/3/4 ユニット・結合テスト全 green（YAML 未指定 → enabled=false → 旧挙動）
- 既存 ep の run_hash が変わっていないことの直接 assert (Option A 検証)

### 6.5 実データ smoke

実装後、SO101 23 episode をバッチ実行し:

| 指標 | 期待 (§2.3 から) |
|---|---|
| mean segment count | ≥ 3.0 |
| seg ≥ 3 の ep 数 | ≥ 22/23 |
| ep10 segment 数 | == 1 |
| boundaries 平均 | ≈ 4 |
| phase ラベル多様性 (run 全体) | ≥ 3 unique phases |

不一致があれば実装か設定値を見直す。

> **2026-05-12 追記 (post-T8)**: T8 実行の結果、ZC detector は予測通りの candidate を出した (3.57 cands/ep) が、最終 segment 数は mean 2.78 と本節の期待 (≥3) を下回った。原因は ZC 側ではなく Phase 4 smoother の `_merge_same_label` が、VLM が同じ phase ラベルを返す隣接 segment を collapse することにあると判明。詳細と次手は `docs/superpowers/notes/2026-05-11-so101-phase4-v4-results.md` 参照。本 spec のスコープ (boundaries.py への ZC 追加) としては実装は仕様通り完了しており、smoother / VLM 粒度の問題は別 spec として切り出す。

---

## 7. Exit criteria

1. ZC detector のユニットテスト全 green
2. YAML ローダーのテスト全 green
3. SO101 ep0 結合テスト green (boundaries ≥ 3, segments ≥ 4)
4. 既存テスト全 green (YAML 未指定で旧挙動完全不変、run_hash 互換)
5. SO101 23 ep smoke: §6.5 の指標を満たす
6. spec / plan / 実装後の notes が docs/superpowers 配下に揃っている

---

## 8. Open questions

1. **`merge_window_sec` のデフォルトをどうするか**: 0 にすると ep0 の短セグ (5.8-6.6s) がそのまま残る。0.5 程度にすると吸収されるが、本来意味のある grasp も消える恐れ。**Phase 4 smoother の `min_segment_duration_sec` に任せる方が筋が良さそう**（boundary 検出層では捨てない）。
2. **`ref` のデフォルトは midpoint で良いか**: episode ごとに ref が変わるが、§2.3 シミュレーションでは固定 0.15 でも midpoint でも 23 ep 結果はほぼ同じ。midpoint は span に対する適応性があり妥当。
3. **score 計算式**: `|last_extreme| / (span/2)` だと span が小さい ep で score がインフレする。`min(1.0, |last_extreme| / 0.20)` 等の絶対値正規化に変える選択肢あり。
4. **テストフィクスチャ**: 結合テストで SO101 ep0 の動画+parquet (~3 MB) を `tests/fixtures/` に置くか、既存 `tests/exports/fixtures/mini_so101/` を流用するか実装時に決定。
5. **gripper 正規化スケールへの依存** ✅ **解決済 (2026-05-11)**:
   - 初稿時点では SO101 robot-config の `gripper_scale_max=100` を所与とし、正規化後 span≈0.35 の前提で hyst=0.05 を採用していた。
   - **2026-05-11 に SO101 用 `gripper_scale_max` を 100 → 60 に再調整** (`docs/superpowers/notes/2026-05-11-so101-gripper-scale-max.md`)。36 ep / 5286 frame 計測の結果、生 gripper 範囲は 3.95–53.79 で、100 は過大。60 (= 観測 max +12%) に変更。
   - 新スケールで ZC sim を再走し、安全 plateau の中央値 **hyst=0.12** を採用 (`docs/superpowers/notes/2026-05-11-so101-zc-resim-new-scale.md`)。
   - §2.3 表、§4.2 default、§5.2 YAML 例はすべて新スケール基準に更新済み。
   - 検討された代替案（採用見送り）:
     - `hyst = k · span` 適応化 → 旧シミュレーションで低 span ep の取りこぼし発生
     - `hyst = k · (max - ref)` 片側適応化 → 未検証、将来の改善案として保留

---

## 9. リスクとロールバック

### 9.1 リスク

- **score 値の妥当性**: ZC で出る score が gripper_transition より高く出すぎて、weighted sum で他 detector を圧倒する可能性。`weight: 0.5` の調整余地あり。
- **frame 内精度の線形補間**: 補間で出た t_cross が `frame * dt` 倍数からズレるが、下流の bracketing は frame 単位なので影響軽微（最寄り frame に丸める）。
- **長尺 episode (30s+) で過剰発火**: 現状 SO101 (10s) でしか検証できていない。長尺 fixture が手に入り次第追検証。
- **enabled=true 時の run_hash 変化**: ZC を使う run は新規 hash になるので新規ディレクトリに出力される。既存 v3 出力は不変。

### 9.2 ロールバック

- 設定面: YAML から `zero_crossing.enabled: false` にすれば即座に旧挙動。
- コード面: `detect_gripper_zero_crossing` と `ZeroCrossingConfig` を revert すれば完全に元に戻る。pipeline.py への追加分岐は 3 行程度なので revert 簡単。
