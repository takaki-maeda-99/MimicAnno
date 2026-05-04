# SAM3 backend swap: transformers → `sam3/` submodule native API

Date: 2026-05-04
Status: Draft（autonomy window 中、ユーザレビュー gate スキップ）
Supersedes: `2026-05-01-sam3-local-hf-snapshot-plan.md`（削除済み）

---

## 1. 動機

現状 `mimicanno/object_tracker/sam3_runtime.py` は **transformers の `Sam3Model` / `Sam3Processor` / `Sam3TrackerVideoModel`** を介して SAM3 を呼んでいる（spec phase3 §2.3）。

これを **`sam3/` git submodule（personal fork; `gayagayataiga/sam3`）の native API**（`sam3.model_builder.build_sam3_video_predictor`）に切り替える。

理由:

1. **チェックポイント取得 IO ゼロ** — `sam3/checkpoints/sam3.pt` がローカルに既に存在。HF 自動 DL 不要。
2. **動作確認済みコードを流用** — `sam3/tools/segment_video.py` がローカルで単体動作することを確認済み。同じ呼び出し系列を SAM3Runtime 内に取り込む。
3. **API 表現力** — sam3 native API は session-style（start_session → add_prompt → propagate_in_video → close_session）で、text / bbox / point すべての prompt を 1 系統で扱える。transformers 経路は機能が分散していて TODO(Task 25) の未確認項目が残っていた（`sam3_runtime.py:80-83, 215-220, 259-272, 327-330`）。

---

## 2. スコープ

### 2.1 in-scope

- `SAM3Runtime` の **内部実装の差し替え**（transformers → sam3 native）
- `SAM3Runtime` の **propagate() のシグネチャ変更**: `frames: Iterator` を `video_path: Path` に置換（理由は §4.2）
- `Propagator.run()` 側の `runtime.propagate(...)` 呼び出し変更
- preflight の checkpoint 解決を **単一ファイル sha**（`sam3.pt`）に固定
- CLI default checkpoint を `sam3/checkpoints/sam3.pt` に変更
- `pyproject.toml`: `sam3` を editable install（`uv add --editable ./sam3`）として追加。transformers SAM3 機能要件（`>=5.5`）は dev/optional 化（VLM 用途で transformers 自体は引き続き必要）
- spec phase3（§2.3, §2.5, §8）の更新
- 既存テストの fixture 更新（`tests/object_tracker/test_sam3_runtime.py` 等）

### 2.2 out-of-scope

- SAM3.1 multiplex predictor 採用（後続検討。今回は SAM3 base predictor だけ）
- multi-GPU（`Sam3VideoPredictorMultiGPU`）対応
- `sam3/agent/` の MLLM ループ採用
- transformers の他用途（VLM = Phase 2）はそのまま

### 2.3 backward compatibility

- 今回は autonomy window 中であり、Phase 5 出口に向けたパイプライン実装中。**外部ユーザはまだ存在しない**ため strict backward compat は不要。
- ただし、内部 fixture（`tests/conftest.py` の `FixtureSAM3Tracker`）の API は維持して、テストブレークを最小化。

---

## 3. SAM3Runtime 公開 API

### 3.1 維持するもの

```python
class SAM3Runtime:
    @classmethod
    def load(cls, *, checkpoint: str | Path, device: str = "cuda") -> SAM3Runtime: ...
    def ground_on_frame(self, frame: np.ndarray, prompt: str) -> list[tuple[BBox, float]]: ...
    def close(self) -> None: ...
```

`load`, `ground_on_frame`, `close` の **シグネチャは変わらない**（戻り値の意味も同じ）。`Propagator` 以外の呼び出し側（`mimicanno/object_tracker/grounder.py` 等）に影響しない。

### 3.2 変更するもの

```python
# 変更前
def propagate(
    self, *,
    frames: Iterator[tuple[int, np.ndarray]],
    prompts_with_initial_bbox: list[tuple[str, BBox]],
    stride: int,
) -> Iterator[FramePropagationResult]: ...

# 変更後
def propagate(
    self, *,
    video_path: Path,
    prompts_with_initial_bbox: list[tuple[str, BBox]],
    expected_frames: set[int],  # caller が事前計算した「Runtime に yield させたい frame_idx 集合」
) -> Iterator[FramePropagationResult]: ...
```

理由:
- sam3 の `start_session(resource_path=...)` は **動画ファイル / JPEG dir のパスを直接受ける**。ランタイム内で frame loader を持っている（`async_loading_frames` 等のオプションあり）。
- 現状 `Propagator.run()` は dummy ndarray を渡して frames iterator を作っている（`propagator.py:411-412` の TODO Task 19）。実フレーム読みを Propagator → Runtime に移譲したい意図はもとからある。
- ファイル入出力は sam3 にやらせた方が、(a) transformers の `Sam3TrackerVideoInferenceSession` 互換コードを書かなくて済む、(b) 動画圧縮対応・async 読み込み・GPU offload 等が無料で付いてくる。

`stride` を Runtime に渡さず **`expected_frames: set[int]` を渡す**：
- 既存の `_build_frame_iterator(n_frames, stride)`（`propagator.py:168-176`）は `range(0, n_frames, stride)` ＋末尾フレーム強制 include なので、単純な `frame % stride == 0` フィルタとは末尾扱いが**一致しない**。set ベースで明示的に渡すことでこのズレを排除する。
- Runtime は sam3 から streaming で受けた `frame_idx` を `if frame_idx in expected_frames: yield ...` で間引いて yield。
- 計算量上は sam3 が全フレーム forward するので無駄が大きい（リスク欄 §6 参照）。将来的には `propagation_direction="forward"` + 飛び飛び `start_frame_idx` を複数回呼ぶ「擬似 stride」最適化を検討するが、今回は out-of-scope。

### 3.3 SAM3Runtime 内部マッピング

| 公開 API | 内部実装 |
|---|---|
| `load(checkpoint=Path("sam3/checkpoints/sam3.pt"))` | `predictor = build_sam3_video_predictor(checkpoint_path=str(checkpoint), bpe_path=str(<sam3 root>/sam3/assets/bpe_simple_vocab_16e6.txt.gz))`。`bpe_path` の明示渡しは editable install での `pkg_resources` 不具合回避（§9 課題 7 参照）。device 引数は build 側で `.cuda()` するので明示 to は不要だが、`torch.cuda.set_device(device)` で固定。 |
| `ground_on_frame(frame, prompt)` | image model を別途用意するか、video predictor に **1フレームの session** を貼って `add_prompt(text=prompt, frame_idx=0)` の戻りを使う。後者を採用（モデルロード回数が減る）。詳細 §4.1。 |
| `propagate(video_path, prompts_with_initial_bbox, expected_frames)` | **N prompts = N session**。各 prompt ごとに `start_session(resource_path=video_path)` → `add_prompt(bounding_boxes=[xywh], obj_id=0, frame_idx=0, rel_coordinates=True)` → `propagate_in_video(propagation_direction="forward")` を別々に走らせ、frame_idx 単位でマージして yield。詳細 §4.2。 |
| `close()` | 保持中の session 全てに `close_session(session_id, run_gc_collect=False)`、最後に **1 回だけ** `gc.collect()` + `torch.cuda.empty_cache()` を呼ぶ。session ごとに empty_cache を呼ぶと VLM 等の他モデル allocator state を破壊するリスクあり。 |

---

## 4. 設計詳細

### 4.1 grounding（`ground_on_frame`）

sam3 video predictor の text prompt 機能を使う。1フレームだけのセッションを張る。

実装スケッチ:
```python
def ground_on_frame(self, frame, prompt):
    # 1. sam3 の load_resource_as_video_frames は単一画像ファイルパスを直接受ける
    #    ため、temp dir の hidden file 混入リスクを避けて単一ファイルを渡す。
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        try:
            Image.fromarray(frame).save(tf.name, quality=95)
            resp = self._predictor.handle_request({
                "type": "start_session", "resource_path": tf.name,
            })
            sid = resp["session_id"]
            try:
                out = self._predictor.handle_request({
                    "type": "add_prompt", "session_id": sid,
                    "frame_index": 0, "text": prompt,
                    "rel_coordinates": True,
                })
                return _outputs_to_bbox_score_list(out["outputs"])
            finally:
                self._predictor.handle_request({
                    "type": "close_session", "session_id": sid,
                    "run_gc_collect": False,
                })
        finally:
            Path(tf.name).unlink(missing_ok=True)
```

`_outputs_to_bbox_score_list`:
- input: `{"out_obj_ids": ndarray[N], "out_boxes_xywh": ndarray[N,4](rel), "out_probs": ndarray[N], ...}`
- output: `[(BBox(x, y, w, h), score), ...]` score 降順
- xywh の規約は **2 つに分けて確認**:
  - (a) **入力規約**: `add_prompt(bounding_boxes=...)` は内部的に `boxes_xywh` 名で渡され `box_xywh_to_cxcywh` 変換が走るため **左上 xywh** が正と推察。implement 段で sam3 内 `box_ops.py` の変換点を grep して確定。
  - (b) **出力規約**: `out_boxes_xywh` が左上 xywh か cxcywh か。implement 段で `tools/segment_video.py` の出力 box を 1 例ログに吐いて目視確認（妥当な座標範囲か）。
- BBox は左上原点 xywh なので、出力が cxcywh だった場合のみ `cx-w/2, cy-h/2` 変換を挟む。

注意:
- `prompt` が hit しない（モデルが何も検出しない）ケースでは `out_obj_ids` が空配列になる。空リストを返すのが既存契約（`grounder.py` 側で「対象なし」として degrade 経路に乗る）。
- **設計トレードオフ**：grounding 用に video predictor のセッションを毎 prompt 張ると entities=5 で 5 回 init_state が走る。1 フレーム動画なので軽量だが、本来は `build_sam3_image_model` を別途ロードして使い回す方が筋（spec review #4）。今回は予算（モデル 2 個ロードの追加 GPU メモリ）と簡素さのトレードオフで video predictor 流用を採用。実機で grounding が遅い／OOM になった場合は image model 分離を後続最適化として検討する。
- `close_session` には `run_gc_collect=False` を渡し、empty_cache は `Runtime.close()` の最後に 1 回だけ。

### 4.2 propagation

**設計判断: 1 prompt = 1 session（segment_video.py のパターンに揃える）。**

理由（spec review #8）: `sam3_video_inference.py:188-202` の `_get_visual_prompt` は「visual prompt は同一 frame で box 1 個まで」と assert する。同一 session 内で複数 obj_id を `add_prompt` で追加すると、2 つ目以降は visual prompt 経路ではなく refinement prompt 経路に倒れる可能性が高く、bbox による初期登録としては機能しない。一方 `segment_video.py:96-127` の `merge_outputs` パターンは検証済みの動作実績がある。

```python
def propagate(self, *, video_path, prompts_with_initial_bbox, expected_frames):
    # Per-prompt session: each prompt gets its own session, then we zip-merge by frame_idx
    sessions: list[tuple[str, str]] = []  # [(prompt, session_id), ...]
    streams: dict[str, Iterator] = {}
    for prompt, bbox in prompts_with_initial_bbox:
        resp = self._predictor.handle_request({
            "type": "start_session", "resource_path": str(video_path),
            "offload_video_to_cpu": self._offload_video,
        })
        sid = resp["session_id"]
        self._open_sessions.append(sid)
        self._predictor.handle_request({
            "type": "add_prompt", "session_id": sid,
            "frame_index": 0, "obj_id": 0,
            "bounding_boxes": [[bbox.x, bbox.y, bbox.w, bbox.h]],
            "bounding_box_labels": [1],
            "rel_coordinates": True,
        })
        sessions.append((prompt, sid))
        streams[sid] = iter(self._predictor.handle_stream_request({
            "type": "propagate_in_video", "session_id": sid,
            "propagation_direction": "forward",
        }))

    try:
        # Round-robin pull: assume each stream yields strictly increasing frame_idx
        # starting from 0. Buffer one item per stream and emit frames in lock-step.
        # If a stream ends earlier than others (sam3 lost track), fill missing
        # prompts with None.
        active = {sid: next(streams[sid], None) for _, sid in sessions}
        while any(v is not None for v in active.values()):
            # find min frame_idx across active streams
            current_frame = min(
                v["frame_index"] for v in active.values() if v is not None
            )
            detections: dict[str, tuple[BBox, float] | None] = {}
            for prompt, sid in sessions:
                buf = active[sid]
                if buf is not None and buf["frame_index"] == current_frame:
                    detections[prompt] = _outputs_to_bbox_score(buf["outputs"])
                    active[sid] = next(streams[sid], None)
                else:
                    detections[prompt] = None
            if current_frame in expected_frames:
                yield FramePropagationResult(
                    frame=current_frame, detections=detections,
                )
    finally:
        for sid in list(self._open_sessions):
            try:
                self._predictor.handle_request({
                    "type": "close_session", "session_id": sid,
                    "run_gc_collect": False,
                })
            finally:
                self._open_sessions.remove(sid)
```

ポイント:
- N prompt は N セッション。**GPU メモリ消費が N 倍**になるリスクは §6 リスク欄に記載。`offload_video_to_cpu=True` で動画 tensor を CPU に逃す設定を CLI option `--sam3-offload`（default True）で公開。
- 各 session は同じ `video_path` を読むので、frame index 空間は揃っている前提。stream は frame 0 から始まる（§9 課題 5 で確認）。
- `propagation_direction="forward"`：grounding は frame 0 で行う前提なので backward は不要。
- `_outputs_to_bbox_score(outputs)` は obj_id=0 のエントリだけを取り出して `(BBox, score) | None` にする：sam3 が track lost 時に obj_ids から該当 id を落とすため、その場合は None。**visual prompt が複数 obj を返した場合（§9 課題 11）も obj_id=0 のみ採用**（その他は黙って捨てる）。
- session のリーク防止のため `_open_sessions: list[str]` を Runtime が保持し、`close()` で全部 close。

#### round-robin の正当性

sam3 の `propagate_in_video(propagation_direction="forward")` は frame index を **単調増加**で yield することを前提にしている（`sam3_video_inference.py` の processing order に基づく）。各セッションが同じ video を読み、同じ start_frame=0 から forward に進むなら、frame_idx 列は session 間で同一。よって min を取るロジックは「全セッションが進んだ frame_idx」を確定して yield することになる。

ただし sam3 が track lost で stream を早期終了させる仕様だと、active 数が減って min がジャンプする。その場合は他 session の frame_idx に揃え、消えた prompt は None で埋める（spec review #10 の対応）。

### 4.3 checkpoint 解決と preflight

- CLI default: `Path("sam3/checkpoints/sam3.pt")`（repo root 相対。実体は submodule 内）。
- `--sam3-checkpoint` は **単一ファイル** に戻す（`dir_okay=False, file_okay=True`）。
- preflight `resolve_sam3_checkpoint(path)`:
  1. `path.exists()` 確認
  2. `path.is_file()` 確認
  3. `(stat.st_mtime_ns, stat.st_size)` を cache key として、`~/.cache/mimicanno/sam3-sha/<key>.txt` から sha256 を読む。なければ `sha256_file(path)` を計算してキャッシュ書き込み。
  4. 結果を `ResolvedCheckpoint(path, sha256)` で返す
- これで `ModelConfig.sam3_checkpoint`（再現性ハッシュ要素）は単一ファイルの sha256 そのまま使え、かつ毎起動の数 GB ハッシュ計算を avoid（spec review #15）。
- HF snapshot dir 連結 sha は破棄。

### 4.4 依存関係

`pyproject.toml`（uv 正攻法）:
```toml
[project]
dependencies = [
    # ... 既存 ...
    "sam3",
    # transformers は VLM (Phase 2) で引き続き必要。SAM3 機能要件は外す
    # ※下限は VLM が要求するバージョンで決まる（implement 段で `vlm_labeler.py` を
    #   実機テストして最低バージョンを確定）。とりあえず 4.45 仮置き。
    "transformers>=4.45,<6",
]

[tool.uv.sources]
sam3 = { path = "sam3", editable = true }
```

`optional-dependencies` 経由は不要（`extras=["sam3"]` で sam3 自身を入れるのは循環で意味がない）。

VLM 互換性確認（spec review #13）:
- `mimicanno/vlm_labeler.py:473` で `from transformers import AutoProcessor` を使用。
- 実装時に `transformers==4.45` / `5.x` の両方で Phase 2 unit/integration テストを green にすることを確認する。CI matrix に追加するかは決定事項として実装段で記録。

### 4.5 sam3 submodule の制約

- sam3 の `pyproject.toml` は Python 3.8+ 宣言だが README は 3.12+。MimicAnno は 3.12 を使っているので問題なし。
- sam3 は `flash-attn-3` を optional で recommends。なくても動く（`build_sam3_video_predictor` 内で fallback）。
- CUDA 12.6+ 推奨。本サーバ環境は要確認（実行段で `torch.version.cuda` を log）。

---

## 5. テスト戦略

### 5.1 unit

- `tests/object_tracker/test_sam3_runtime.py`: モック化方針を変更。transformers シンボルをパッチする旧方式から、`sam3.model_builder.build_sam3_video_predictor` をパッチする新方式へ。fixture predictor は `handle_request` / `handle_stream_request` を持つ duck-typed mock。
- `tests/preflight/test_resolve_sam3_checkpoint.py`: dir 経路の旧テストを削除、単一ファイル経路のテストを再アクティブ化。

### 5.2 integration

- `tests/integration/test_phase3_pipeline.py`: `FixtureSAM3Tracker` の API（`ground_on_frame`, `propagate`, `close`）は維持。`propagate` だけシグネチャ変更（`frames` → `video_path` + `expected_frames`）。

`FixtureSAM3Tracker.propagate` の擬似コード:
```python
def propagate(self, *, video_path, prompts_with_initial_bbox, expected_frames):
    # video_path は実際には読まない（フィクスチャ）
    sorted_frames = sorted(expected_frames)
    for fi in sorted_frames:
        if fi == self.raise_on_propagate_at_frame:
            raise RuntimeError("simulated SAM3 mid-propagation failure")
        detections = {p: self._fake_detection(p, fi) for p, _ in prompts_with_initial_bbox}
        yield FramePropagationResult(frame=fi, detections=detections)
```

`raise_on_propagate_at_frame` セマンティクスは維持。stride 仕様変更を fixture に反映するのが本変更の主作業。

### 5.3 real-data smoke（Phase 5 autonomy 出口条件）

- `~/MimicRec/datasets/SO101` の 1 episode で `mimicanno run --target-phase 3` を実行。Phase3 まで通り、track が出ることを確認。
- 既存 viewer で track 描画が正しいことを目視。
- 結果が完全に従来パイプラインと bit-for-bit 一致する必要はない（モデル backend が変わるため）。**「人間が見て妥当」レベルでよい**（CLAUDE.md autonomy window 出口条件）。

---

## 6. リスクと緩和

| リスク | 緩和 |
|---|---|
| `out_boxes_xywh` の座標系（top-left vs center）誤認 | implement 段で 1 件ログ確認＋unit test で BBox 範囲を assert（§4.1 で入出力規約を分けて確認）|
| `add_prompt(bounding_boxes=...)` を「visual prompt」（初期1個）と「refinement」（以降）として sam3 が区別する（`sam3_video_inference.py:188-202`） | **§4.2 で 1 prompt = 1 session に変更済み**（multi-object を単一 session で扱おうとすると 2 つ目の box が visual prompt assert で raise されるため）|
| sam3 の editable install が他環境（CI）で壊れる | uv lock でバージョン固定。CI ジョブでも `git submodule update --init` を実行 |
| `flash-attn-3` 不在で速度劣化 | optional のままにして本実装で warn ログのみ |
| GPU メモリ：N prompt = N session で動画 tensor が N 倍メモリを食う | `offload_video_to_cpu=True` を CLI option `--sam3-offload`（default True）で公開 |
| stride 計算量：sam3 が全フレームを forward 計算（caller-side 間引きでは GPU 計算は減らない） | 実機 smoke で速度測定。SO101 で許容範囲を超えるなら「飛び飛び `start_frame_idx` × max_frame_num_to_track=1 を複数回」の擬似 stride を後続最適化として検討（spec review #7）|
| `bbox-only` セッション（text なし）が sam3 で許容されるか未検証 | implement 段の最初に最小ユニットテスト（1 obj × 1 bbox prompt × 短尺動画）を 1 件入れる（§9 課題 6）|
| Phase 2 VLM の transformers 最低バージョン未確定 | implement 段で `vlm_labeler.py` の実機テスト。互換 break あれば `>=` を上げる |
| sha256 の毎起動コスト（数 GB ファイル） | `ResolvedCheckpoint` を `(path, mtime, size, sha256)` に拡張し sha は cache。invalidation は path+mtime+size の組合せ（§4.3 補足）|

---

## 7. ロールバック

問題が出たら git で `experiment/sam3-local` ブランチを `main`（`1b180b5`）に戻すだけで transformers 経路に復帰可能。`main` は触らない。

---

## 8. 影響を受けるファイル一覧

| ファイル | 変更内容 |
|---|---|
| `mimicanno/object_tracker/sam3_runtime.py` | 全面書き換え（公開 API は §3.1 維持） |
| `mimicanno/object_tracker/propagator.py` | `runtime.propagate(video_path=..., n_frames=...)` 呼び出しに変更、frames iterator 廃止 |
| `mimicanno/preflight.py` | `resolve_sam3_checkpoint` を単一ファイル sha 専用に戻す |
| `mimicanno/cli.py` | `--sam3-checkpoint` を `dir_okay=False`、default を `sam3/checkpoints/sam3.pt` |
| `mimicanno/config.py` | `TrackingConfig.sam3_model_id` の意味付け：`"sam3"` 固定に簡略化 |
| `pyproject.toml` | sam3 editable source 追加、transformers ピン緩和 |
| `tests/conftest.py` | `FixtureSAM3Tracker` の `propagate` シグネチャ更新 |
| `tests/object_tracker/test_sam3_runtime.py` | モック対象を `build_sam3_video_predictor` に変更 |
| `tests/preflight/*` | dir 経路テスト削除 |
| `docs/superpowers/specs/2026-04-28-mimicanno-phase3-sam3-tracking-design.md` | §2.3 / §2.5 / §8 を本 spec の決定で上書き（または「2026-05-04 本 spec で更新」と note） |

---

## 9. オープン課題（implement 段で解決）

`scripts/smoke_sam3_bbox_only.py`（Task 4）で確認済みのものを ✓、残課題を ☐ で示す。

### ✓ 検証済み（2026-05-04 smoke）

1. **入力 bbox 規約**: ✓ **左上 xywh normalized**。`bounding_boxes=[[x, y, w, h]]` + `rel_coordinates=True`。
2. **出力 bbox 規約**: ✓ **左上 xywh normalized**。BBox との変換不要。
3. **track lost 挙動**: ✓ `out_obj_ids` 配列から該当 id が落ちる（残った id だけが配列に並ぶ）。lost 検出は `prompt → None` 変換で扱う。
4. **frame 0 yield**: ✓ propagate_in_video は frame 0 を最初に yield する。
5. **bbox-only セッション**: ✓ text 引数なしの `add_prompt` で動作。RuntimeError なし。
6. **N=2 セッション frame_idx 同期**: ✓ 同じ video に対して N 個のセッションは frame_idx を一致させて yield。
7. **editable install**: ✓ `uv pip install -e ./sam3` で `from sam3.model_builder import build_sam3_video_predictor` 成功。**ただし** sam3 の editable install では `pkg_resources.resource_filename("sam3", "assets/...")` が None を返す問題があり、`build_sam3_video_predictor(checkpoint_path=..., bpe_path=str(<sam3 root>/sam3/assets/bpe_simple_vocab_16e6.txt.gz))` のように **`bpe_path` を明示渡し**する必要がある。SAM3Runtime.load() でこれをやる。
8. **dtypes**: ✓ `out_obj_ids: int64`, `out_boxes_xywh: float32`, `out_probs: float32`, `out_binary_masks: bool`。
9. **close_session 冪等性**: ✓ 二重呼びは `WARNING` ログを出すが例外を投げない。Runtime.close() の二重呼び対策は不要（既存の `_closed` flag で十分）。
10. **追加発見: add_prompt vs propagate frame 0 出力の不一致**: `add_prompt` の戻り `outputs` と、続く `propagate_in_video` の frame 0 yield の `outputs` は **異なる**ことがある（モデルの異なる経路を通るため）。grounding 用途では add_prompt 戻りを使うのが正解（spec §4.1 通り）。propagate 用途では「propagate stream の frame 0」を採用するが、不安定挙動が観測されたら **add_prompt 戻りで frame 0 を上書き** する保険を Runtime に入れる（実装段で必要性判断）。
11. **追加発見: visual bbox prompt の multi-detection 性質**: 1 個の bbox を visual prompt として渡しても、sam3 は exemplar 解釈で **複数 instance を返す**ことがある。`prompts_with_initial_bbox` での「特定の 1 物体を追跡」という意図と乖離。出力側で `obj_id=0` のみ採用すればロジック的には問題ないが、内部的に複数 obj が track されることでメモリ・計算が無駄になる可能性。**Runtime はとりあえず obj_id=0 のみ採用する（他 obj_id は捨てる）** 方針で進める。

### ☐ 残課題（実装段で対応）

12. **add_prompt 戻りで frame 0 上書きの要否**: 実機（SO101）で grounding 由来の bbox を渡したとき、propagate frame 0 が空にならないかを Task 14 smoke で観察。空になるようなら Runtime に上書きロジックを追加。
13. **VLM (transformers) との互換**: 現環境は transformers 5.6.2 で動作。pin を `>=4.45,<6` でいいか Phase 2 の最低テストで確認。
14. **`pkg_resources` deprecation**: sam3 が `pkg_resources` 依存。setuptools<81 にピンするか、bpe_path 明示渡しで回避（後者を採用）。spec §4.4 の依存関係に `setuptools` 制約は不要。

---

## 10. 完了基準

1. `mimicanno run --target-phase 3 --video <SO101 episode>` がエラーなく完走。
2. 出力 `tracks.json` を viewer で読み、bbox がオブジェクトに追従していることを目視確認。
3. 既存 unit/integration テスト（fixture 経路）が green。
4. `git grep -n "from transformers import Sam3"` の結果が **空**（mimicanno コードから transformers SAM3 シンボル参照が消えていること）。
