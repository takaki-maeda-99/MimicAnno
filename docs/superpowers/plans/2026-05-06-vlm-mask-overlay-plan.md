# 実装計画: VLM mask overlay（Gemma 入力 keyframe への SAM3 マスク半透明合成）

Date: 2026-05-06
Spec: [2026-05-04-vlm-mask-overlay-design.md](../specs/2026-05-04-vlm-mask-overlay-design.md)
Branch: `experiment/sam3-local`（または専用ブランチ `feature/vlm-mask-overlay` を切る）
Status: Ready to execute（autonomy window 中、ユーザレビュー gate スキップ）

---

## 概要

タスクは依存順に並べた 13 件。早期に **MaskCache + RLE round-trip** を固めて以降の実装を pure-fixture で回せるようにし、SAM3 native API への接続は中盤に持ってくる構成。

最終 deliverable は次の 2 つ:

1. `--vlm-mask-overlay` フラグありで SO101 を再アノテーションして、`_vlm_dumps/episode_*/<seg>/attempt_*/keyframe_*.png` に**マスクオーバーレイ済み画像**が出る状態。
2. 既存（マスク無し版）23 件と同じ集計スクリプト (`scripts/aggregate_gemma_pairs.py`) でオーバーレイ版 jsonl を出力。FT 用ペアとして v2 と並べる。

## 進行ルール

- 各タスク完了時に対象テストファイルだけ `uv run pytest -q tests/<path>` で green を確認。
- 並列化可能なタスクは `[parallel-ok]` でマーキング。
- **Task 5（SAM3 mask 抽出 smoke）が失敗したら一時停止**。SAM3 native API の `out_binary_masks` shape/dtype 前提が崩れると以降が成立しない。
- 残り 13 ep の `fps.unresolvable` バグは本計画外（別ブランチで対応）。本計画では**現状成功している 23 ep + 新規 ep31-32**＝ 25 ep が対象。

---

## Task 1: `MaskOverlayConfig` の追加と `VLMConfig` への組み込み

**Goal**: `MaskOverlayConfig(enabled=True, alpha=0.4, palette="builtin_10")` が `VLMConfig.mask_overlay` として配置され、`to_dict()` / `config_hash` に反映される。

- `mimicanno/config.py` に `MaskOverlayConfig` (frozen dataclass) を追加。
- `VLMConfig` に `mask_overlay: MaskOverlayConfig = MaskOverlayConfig()` を nest。
- `VLMConfig.to_dict()` に `"mask_overlay": self.mask_overlay.to_dict()` を追加。
- `tests/config/test_vlm_config.py`（既存 or 新規）に:
  - `to_dict()` に mask_overlay が出ること
  - `enabled=True/False` で `compute_config_hash` の出力が変わること

**Out**: 該当テスト green。`config_hash` が overlay 設定で分岐する。

---

## Task 2: RLE encode/decode ラッパと `MaskCache` 新設 [parallel-ok with Task 1]

**Goal**: `mimicanno/object_tracker/mask_cache.py` に `MaskCache` と pycocotools ラッパが実装され、round-trip テストが通る。

- 新規 `mimicanno/object_tracker/mask_cache.py`:
  - `encode_mask(arr: np.ndarray) -> bytes`
  - `decode_mask(blob: bytes) -> np.ndarray`
  - `class MaskCache(frozen=True)`: `by_frame`, `shape`, `palette`, メソッド `get`, `prompts_at`, `all_prompts`
  - palette 割り当てヘルパ `assign_palette(prompts, palette_name="builtin_10")`
  - `BUILTIN_10` RGB tuple list を spec §5.3 そのままで定義
- `tests/object_tracker/test_mask_cache.py`:
  - RLE round-trip: ランダム bool 配列 100 件で `decode(encode(a)) == a`
  - `MaskCache.get` が None / ndarray を正しく返す
  - `prompts_at`, `all_prompts` が **辞書順**
  - palette 割り当ての決定性（同 prompt 集合 → 同色）
  - palette index >= 10 で `idx % 10` 循環

**Out**: 該当テスト green。pycocotools 依存を呼び出し側に露出させない。

---

## Task 3: `vlm_overlay.py` 新設（alpha blend + legend builder）[parallel-ok with Task 2]

**Goal**: pure 関数だけで `compose_overlay(frame, mask_cache, frame_index, alpha)` と `build_color_legend(mask_cache)` が動く。

- 新規 `mimicanno/vlm_overlay.py`:
  - `compose_overlay(frame: np.ndarray, mask_cache: MaskCache, frame_index: int, alpha: float) -> np.ndarray`
    - prompts を辞書順で iterate、後勝ち alpha blend
    - 全 prompt None → 入力フレームをそのまま返す（コピーは作る）
  - `build_color_legend(mask_cache: MaskCache, frame_indices_in_segment: list[int]) -> str | None`
    - 「segment 内 1 frame でも mask を持つ prompt」だけ凡例に出す（spec §5.5）
    - 出力例: `"Colored translucent overlays (~40% opacity) mark tracked objects: red=gripper, blue=red_block. An overlay may be absent in some frames if the object is temporarily occluded or out of view."`
    - 全 prompt 全 frame None → `None`
  - 色 index → 英語色名 dict（red, blue, green, ...）を内部定数で持つ
- `tests/test_vlm_overlay.py`:
  - 性質ベース: mask=0 → 入力 == 出力 / mask=1 単色 + alpha=1 → 出力 == 色 / 複数 mask → 辞書順最後の色 / alpha=0 → 入力 == 出力
  - legend snapshot: palette 入力 → 期待文字列
  - 全 lost segment → legend == None

**Out**: 該当テスト green。SAM3/Gemma に依存しない pure unit テスト。

---

## Task 4: `FramePropagationResult` に `masks` フィールド追加

**Goal**: `FramePropagationResult.masks: dict[str, np.ndarray | None]` が存在し、`detections` と prompt key 集合が一致する不変条件を保つ。

- `mimicanno/object_tracker/sam3_runtime.py` の `FramePropagationResult` dataclass を拡張。
- 既存テスト fixture（masks 無し）が壊れないよう、デフォルト `masks={}` ではなく **明示渡しを必須**にする（spec §7.4）。
- ヘルパ `make_test_propagation_result(...)` を `tests/conftest.py` 等に集約し、`masks` パラメータを `default None` に。

**Out**: 既存テストが（masks 渡さず）通り続ける。新フィールドの presence は型チェックで保証。

---

## Task 5: SAM3Runtime で `out_binary_masks` を取得・ダウンサンプル・MaskCache 構築（[早期 smoke ゲート]）

**Goal**: `propagate(...)` が `MaskCache` を返り値に含む。SO101 ep0 で実走させて mask shape == keyframe size、coverage > 0 が出る。

- `_outputs_to_bbox_score` 系の helper 隣に `_outputs_to_mask` を追加し、`out_binary_masks[i]` を取り出して keyframe size に nearest-neighbor downsample。
- `propagate` の戻り値型を変更:
  - 現状: 各 frame の `dict[prompt, (BBox, score) | None]`
  - 新: `Iterator[FramePropagationResult]` のまま、`masks` を埋めて流す
- `Propagator`（`propagator.py`）側でも masks を貯め込んで MaskCache を構築 → `run()` の戻り値に `(tracks, mask_cache)` のタプルで返す。
- スモーク: `scripts/smoke_sam3_mask_extraction.py`（新規、CI 外）
  - SO101 ep0 で 1 prompt（"tape"）のみ propagate
  - `mask.shape == (image_size_px, image_size_px)`
  - 少なくとも 1 frame で `mask.sum() > 0`
  - RLE 圧縮率を log 出力（情報用）
- **このスモークが失敗したら一時停止してユーザに報告。**

**Out**: スモーク green、`tracks.json` の shape は変えず、MaskCache が in-memory で保持される。

---

## Task 6: `ClipFeatureExtractor` を MaskCache 受け取り対応に拡張

**Goal**: `extract_clip_features` が `MaskCache | None` を受け取り、`enabled=True` のときに keyframe へ overlay 合成する。

- `mimicanno/clip_features.py` の `ClipFeatureConfig` / `extract_clip_features` を拡張:
  - 引数に `mask_cache: MaskCache | None = None`, `mask_alpha: float = 0.4` を追加
  - keyframe 抽出後、`mask_cache is not None` なら `vlm_overlay.compose_overlay(frame, mask_cache, frame_idx, alpha)` を適用
- 既存テスト互換: `mask_cache=None` で bit-exact に既存挙動と一致することをテストで保証（spec §7.4）。
- `tests/test_clip_features.py` に:
  - `mask_cache=None` で生 keyframe と pixel-exact 一致
  - 単純な合成 fixture（黒フレーム + 全 1 mask + 赤）→ 出力 pixel == 期待色

**Out**: 該当テスト green。

---

## Task 7: `vlm_prompt.py` に色凡例の挿入

**Goal**: `enabled=True` かつ legend != None のとき、prompt 冒頭付近に凡例 1 行が入る。`enabled=False` で完全に旧挙動。

- `mimicanno/vlm_prompt.py` に `legend: str | None = None` 引数を増やし、本文に挿入。
- スナップショットテスト 2 本:
  - legend あり → 期待文字列に `"red=gripper, blue=..."` が入る
  - legend == None → 旧 prompt 文字列と一致（後方互換性）

**Out**: 該当テスト green。token 数増は数十程度を想定（許容）。

---

## Task 8: Pipeline 配線（Stage 2 → Stage 3 で MaskCache 引き渡し）

**Goal**: `annotate_episode_phase3`（または該当箇所）で SAM3 propagation の MaskCache を受け取り、`extract_clip_features` と `vlm_prompt` の両方に同じ `MaskCache` を渡す。

- `mimicanno/pipeline.py` の Stage 2 → Stage 3 接続を修正:
  - `Propagator.run()` の戻り値タプルから MaskCache を unpack
  - `VLMConfig.mask_overlay.enabled = False` のときは MaskCache を `None` 化して渡す（後方互換）
- `extract_clip_features(..., mask_cache=mask_cache, mask_alpha=cfg.alpha)` で keyframe 合成
- `vlm_prompt` 構築時に `legend = build_color_legend(mask_cache, segment_frame_indices)`
- ログ出力（spec §11）:
  - `mask_coverage_mean / min / max` per segment
  - `palette_assignment` per episode
  - MaskCache size bytes per episode
- 既存統合テストが通り続けることを確認。

**Out**: フルパイプライン smoke で fixture episode が end-to-end で完走。

---

## Task 9: CLI フラグ追加

**Goal**: `--vlm-mask-overlay/--no-vlm-mask-overlay` (default True), `--vlm-mask-alpha FLOAT` (default 0.4) が CLI から効く。

- `mimicanno/cli.py` の annotate コマンドに 2 つのフラグを追加。
- 反映先は `VLMConfig.mask_overlay`。
- `tests/test_cli.py` に簡単な引数パーステストを追加。

**Out**: `mimicanno annotate --no-vlm-mask-overlay ...` で旧挙動、フラグ有りで新挙動。

---

## Task 10: 実 SAM3 統合 smoke（`tests/test_phase3_real_sam3_smoke.py` 拡張）

**Goal**: spec §9.3 の 3 ケース（mask shape / overlap <1% / prompt centroid 距離）を SO101 ep0 で確認。

- 既存テストファイルに 3 ケース追加。
- `pytest.mark.slow` 等で marker し、CI からは除外（手動実行）。
- 実行コマンドを `docs/superpowers/notes/` 側に記録。

**Out**: 手動実行で all green。

---

## Task 11: `MIMICANNO_VLM_DUMP_DIR` で出る `keyframe_*.png` がオーバーレイ版になる挙動を確認

**Goal**: 既存の dump hook がそのまま使える（`vlm_labeler.py` の `_maybe_dump_vlm_input` は `request["keyframes"]` を保存しており、`keyframes` は overlay 適用済みになっているので無改修で OK）。

- `vlm_labeler.py` を一読し、`request["keyframes"]` が overlay 後のフレームになっていることを再確認（多分修正不要）。
- 必要なら 1 行 dump しているところに「overlay 適用済み」コメントを足すだけ。
- Smoke run（手動）で実際に dump 画像を目視確認。

**Out**: 1 ep 実走 → dump dir に色付き keyframe が出る。

---

## Task 12: SO101 を再アノテーション → ペア再収集

**Goal**: `runs/so101_phase4_v3/` に overlay 版で 25 ep（既存成功した 0-10, 21-32）を流し、`_vlm_dumps/aggregated/{planner,labeler}.jsonl` を生成。

- バッチドライバを少し変更（or 新規 `scripts/batch_so101_phase4_overlay.sh`）:
  - `RUNS_ROOT=runs/so101_phase4_v3`
  - 既存 `--vlm-mask-overlay` 有効（default なので明示不要）
- GPU 2 枚で並列実行（前回と同じ pattern）。
- 完走後 `scripts/aggregate_gemma_pairs.py --dumps runs/so101_phase4_v3/_vlm_dumps` で集約。

**Out**: `planner.jsonl` 25 行 + `labeler.jsonl` 25 行（全 parse_ok=True 期待）。dump 画像を 5 件目視チェック。

---

## Task 13: Autonomy exit criteria の判断材料をまとめる

**Goal**: 人間レビュー用に、overlay あり/なし両方の dump 画像 + Gemma 出力を並べたサマリを `docs/superpowers/notes/2026-05-06-vlm-mask-overlay-results.md` に記録。

- v2（マスク無し）と v3（オーバーレイ）の labeler 出力を 5 ep 分横並びで比較:
  - segment label の object 言及（"the tape", "the bottle" 等）の有無
  - phase confidence の差
- Spec §12.5（alpha=0.4 の妥当性）, §12.6（Gemma 色解釈）の所感を 1 段落で記述。
- exit criteria 判定（autonomy window を抜けるかどうかの提案）をユーザに渡せる形にする。

**Out**: notes ファイル commit。autonomy window のクロージング判断材料が揃う。

---

## 並列化マップ

```
Task 1 ─┐
        ├─ Task 4 ─ Task 5 (SAM3 smoke gate) ─ Task 6 ─ Task 8 ─ Task 9 ─ Task 10 ─ Task 11 ─ Task 12 ─ Task 13
Task 2 ─┤                                       │
Task 3 ─┘                                       └─ Task 7
```

Task 1/2/3 は各 30〜60 分目安、独立に着手可能。Task 5 が早期スモークゲート。

## メモ

- pycocotools は既存依存（pyproject.toml）。新規依存なし。
- numpy は SAM3 制約で 1.x。OpenCV (`cv2.INTER_NEAREST`) も既存。
- 既存 v2 dump（23 ep × planner + labeler）は破棄せず残す。**FT データセットとして overlay あり / なしの 2 ロットが揃う形を目指す**。
- 13 ep（11-20, 33-35）の `fps.unresolvable` 救出は本計画外。Task 12 完了後に別計画で対応する。
