# VLM mask overlay: Gemma 入力 keyframe への SAM3 マスク半透明合成

Date: 2026-05-04
Status: Draft（autonomy window 中、ユーザレビュー gate スキップ）
Related:
- `2026-04-28-mimicanno-phase3-sam3-tracking-design.md`（SAM3 tracking）
- `2026-04-27-mimicanno-phase2-vlm-labeling-design.md`（VLM labeling）
- `2026-04-30-mimicanno-phase5-export-design.md`（Phase 5 export）

---

## 1. 動機

現状 Gemma に渡される keyframe は **生のビデオフレーム** である（[clip_features.py:317](../../../mimicanno/clip_features.py#L317) `extract_frames_at_indices` の出力）。SAM3 が tracking で得た物体位置情報は `robot_state_summary` という**スカラー特徴のテキスト**としてプロンプトに注入されているが、Gemma が「いまどの object を操作しているか」を視覚的に把握するための情報は画像に含まれていない。

仮説: SAM3 が出している `out_binary_masks`（[sam3_runtime.py:169](../../../mimicanno/object_tracker/sam3_runtime.py#L169)）を keyframe に**半透明オーバーレイ**として焼き込むことで、Gemma の segment label 出力に object-aware な判断（"the gripper is grasping the red block" のような対象識別を伴う label）が乗りやすくなる。

**目的**: Phase 3 既存パイプラインの SAM3 propagation 段で出るマスクを、追加の SAM3 推論ゼロで keyframe に合成し、Gemma に渡す。

**非目的**:

- Amodal completion（隠れた部分の補完）。SAM3 は visible-only segmentation モデルなので、見えてない pixel は描画しない。
- マスクの永続化（中間生成物として扱い、`annotate_episode` 終了時に破棄）。
- マスク UI / 編集機能。Phase 5 edit UI とは別レイヤ。
- マスクベースのスカラー特徴の追加（既存の `robot_state_summary` で十分）。

---

## 2. 用語と前提

### 2.1 用語

- **mask**: 1 prompt × 1 frame の binary segmentation（H×W bool 配列）
- **prompt**: SAM3 に渡す 1 物体の追跡対象指示（bbox + 文字列ラベル）。例: `"red block"`, `"gripper"`
- **session**: SAM3 の 1 prompt 分の追跡セッション（[sam3_runtime.py:478](../../../mimicanno/object_tracker/sam3_runtime.py#L478)）
- **keyframe**: 1 segment あたり N 枚抽出される、Gemma 入力用フレーム
- **RLE**: Run-Length Encoding。pycocotools の COCO RLE フォーマット（column-major）を採用

### 2.2 前提

既存の所与で本設計が依拠するもの:

1. **1 prompt = 1 SAM3 session**: bbox prompt は SAM3 側の制約で multi-bbox 単一 session が不可（[sam3_runtime.py:446-447](../../../mimicanno/object_tracker/sam3_runtime.py#L446-L447)）。
2. **SAM3 は visible-only segmentation**: SAM 2 系統のマスク head はオクルージョンを跨いだ amodal 復元をしない（仕様）。
3. **GPU 排他**: SAM3 と Gemma は同じ GPU を使うため、Stage 2 の SAM3 close 後 Stage 3 で Gemma を載せる設計（[pipeline.py:860](../../../mimicanno/pipeline.py#L860)）。本機能はこの順序を変えない。
4. **propagation は keyframe 確定より先**: SAM3 は全フレームで propagation を回した後、segment 境界が決まり keyframe 位置が定まる（[pipeline.py:850-892](../../../mimicanno/pipeline.py#L850-L892)）。よって propagation 時点では「どのフレームを keyframe にするか」が未確定。マスクを保持するメカニズムが必要。

---

## 3. 設計概要

### 3.1 データフロー

```
SAM3 propagation (Stage 2)
   │
   │ 1 frame ごとに
   │   { boxes, probs, binary_masks } を出力
   ▼
SAM3Runtime
   │ binary_masks を keyframe size にダウンサンプル
   │ pycocotools で RLE encode
   ▼
MaskCache (in-memory, RLE bytes)
   │ frame_index × prompt → RLE
   ▼
ClipFeatureExtractor.extract (Stage 3)
   │ keyframe を ffmpeg で抽出
   │ MaskCache から該当 frame のマスクを取り出して decode
   │ alpha blend で合成（後勝ち、prompt 辞書順）
   ▼
合成済み keyframe + 色凡例つき prompt → Gemma
```

### 3.2 改修対象ファイル

| 層 | ファイル | 変更概要 |
|---|---|---|
| SAM3 ランタイム | `mimicanno/object_tracker/sam3_runtime.py` | `_coerce_outputs_arrays` に masks 追加、`FramePropagationResult` 拡張、ダウンサンプル + RLE encode |
| 新規 | `mimicanno/object_tracker/mask_cache.py` | `MaskCache` クラス（RLE 保管、frame×prompt 検索） |
| Tracker | `mimicanno/object_tracker/propagator.py` | propagate() 戻り値に MaskCache を含める（既存 `Track` には mask を持たせない） |
| Pipeline | `mimicanno/pipeline.py` | Stage 2 → Stage 3 で MaskCache を引き渡す配線 |
| Clip 特徴 | `mimicanno/clip_features.py` | overlay 合成ロジック、`MaskCache` 受け取り |
| 新規 | `mimicanno/vlm_overlay.py` | alpha blend、palette、色凡例文字列ビルダ |
| Prompt | `mimicanno/vlm_prompt.py` | 色凡例 1 行を prompt に追加 |
| Config | `mimicanno/config.py` | `MaskOverlayConfig` 追加、`VLMConfig.mask_overlay` |
| CLI | `mimicanno/cli.py` | `--vlm-mask-overlay/--no-vlm-mask-overlay`, `--vlm-mask-alpha` |

### 3.3 データフロー上の不変条件

- MaskCache のキーは「**SAM3 が見ていた frame_index**」と一致する。stride / FPS 変換は MaskCache の責務外で、ClipFeatureExtractor は keyframe の frame_index でそのまま検索する。
- マスクは**保管時点で keyframe size にダウンサンプル済み**。decode 後にリサイズしない（合成時の解像度を一意にし、テスト容易化）。
- 1 prompt が track lost した frame では `MaskCache.get(frame, prompt) == None`。空配列ではなく明示的 None を返す。

---

## 4. データ構造

### 4.1 `FramePropagationResult` 拡張

[sam3_runtime.py:59-71](../../../mimicanno/object_tracker/sam3_runtime.py#L59-L71) の既存 dataclass に `masks` フィールドを追加。

```python
@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    frame: int
    detections: dict[str, tuple[BBox, float] | None]
    masks: dict[str, np.ndarray | None]   # NEW: prompt -> H×W bool, None=track lost
```

**Why**: 既存 `detections` と並走させることで、bbox と mask の整合性（同じ prompt について両方 None または両方非 None）を呼び出し側で保証できる。別 dataclass にすると突合バグの温床になる。

### 4.2 `MaskCache` 新設

```python
@dataclass(frozen=True)
class MaskCache:
    """Frame-indexed RLE-encoded mask store.

    Lifetime: from SAM3 propagation start to annotate_episode exit.
    Memory profile: ~3-12 MB / episode (RLE compresses binary masks
    by 50-200x for typical segmentation shapes).
    """
    by_frame: dict[int, dict[str, bytes | None]]
    shape: tuple[int, int]                     # (h, w) in keyframe pixels
    palette: dict[str, tuple[int, int, int]]   # prompt -> RGB

    def get(self, frame_index: int, prompt: str) -> np.ndarray | None: ...
    def prompts_at(self, frame_index: int) -> list[str]: ...   # 辞書順返却
    def all_prompts(self) -> list[str]: ...                    # 辞書順
```

**Why frozen=True**: 構築後は読み取りのみ。propagation で全部詰めて以降は不変。並列読みの安全性確保。なお `frozen=True` は再代入のみを防ぐので、内部 `dict` の `update()` はランタイムでは止められない（型システムの制約）。**構築後 mutate しない規約**として運用し、テストで round-trip 確認する。

**Why palette を MaskCache に含めるか**: prompt → 色のマッピングは episode 内で**決定論かつ一意**でなければ、prompt 凡例と合成色がずれる。MaskCache 構築時に palette を確定させ、合成側 (`vlm_overlay.py`) と prompt 側 (`vlm_prompt.py`) の両方が同じ MaskCache を参照する。

### 4.3 RLE エンコーディング

pycocotools 採用（[pyproject.toml `pycocotools>=2.0.8`](../../../pyproject.toml) 既存依存、SAM3 自身も内部利用）。

ラッパで COCO 規約を隠蔽:

```python
# mimicanno/object_tracker/mask_cache.py
from pycocotools import mask as coco_mask

def encode_mask(arr: np.ndarray) -> bytes:
    """bool H×W -> opaque bytes. Caller never touches COCO column-major dict."""
    assert arr.dtype == np.bool_ and arr.ndim == 2
    fortran = np.asfortranarray(arr.astype(np.uint8))
    rle = coco_mask.encode(fortran)
    # rle = {"size": [h, w], "counts": bytes}; we serialize to a single bytes blob.
    return _serialize_rle(rle)

def decode_mask(blob: bytes) -> np.ndarray: ...
```

**Why ラッパ**: 呼び出し側が COCO 仕様（column-major、`size`/`counts` dict 形式）に依存しないようにする。将来 SAM3 のアウトプット仕様が変わった時、または RLE 実装を差し替える時に呼び出し側を触らずに済む。

### 4.4 マスクの解像度ポリシー

**ダウンサンプル時点**: SAM3Runtime が `_outputs_to_bbox_score` 系の helper を経由して frame 出力を返す直前。

**ダウンサンプル先解像度**: `VLMConfig.image_size_px`（keyframe と同じ）。

**ダウンサンプル法**: nearest-neighbor（cv2.INTER_NEAREST）。理由は 2 つ:
1. **意味論**: マスクは discrete な「object/non-object」二値表現で、連続補間（bilinear等）は型として不適切。0.5 という pixel に何の意味もない。
2. **実装上の都合**: bilinear だと bool が float になり、RLE 圧縮率が落ちる + alpha blend 時の境界がぼやける。

**Why 元解像度を捨てるか**: 現状の唯一の用途が keyframe overlay であり、keyframe size 以上の解像度は使い道がない。元解像度保持は **§11.4 未決事項** 参照（将来要件出たら二層化検討）。

### 4.5 ライフサイクル（§8 から吸収）

- **生成**: `Propagator.run()` 内で MaskCache を空で初期化し、SAM3 stream の各 frame で append。
- **引き渡し**: `Propagator.run()` の戻り値に `(tracks, mask_cache)` のタプルで含める。
- **消費**: `pipeline.annotate_episode_phase3` が MaskCache を `ClipFeatureExtractor` のコンストラクタに渡す。
- **破棄**: `annotate_episode_phase3` のスコープを抜けた時点で GC 回収。tempdir も外部ストレージも使わない。

メモリ見積もり（§3 で予算化済み）: 512×384 bool × 1500 frames × 5 prompts × 圧縮率 100:1 ≈ **6 MB/episode**。許容。上限ガードは設けない（前提が崩れたら §11 の再評価で対応）。

---

## 5. オーバーレイ合成

### 5.1 アルゴリズム

各 keyframe について:

1. MaskCache から該当 frame_index の全 prompt のマスクを取得（None は skip）
2. prompt 名の**辞書順**（NFC 正規化なし、Python `sorted()` のデフォルト）で並べる
3. 各 prompt について alpha blend を順に適用（**後勝ち**）:

```python
for prompt in sorted(mask_cache.prompts_at(frame_index)):
    mask = mask_cache.get(frame_index, prompt)
    if mask is None:
        continue
    color = mask_cache.palette[prompt]   # (R, G, B) uint8
    alpha = config.mask_overlay.alpha    # default 0.4
    m = mask.astype(np.float32)[..., None]   # H×W×1
    frame = frame * (1 - alpha * m) + np.asarray(color)[None, None, :] * alpha * m
return frame.astype(np.uint8)
```

### 5.2 重なり処理: 後勝ち、prompt 辞書順

**Why 後勝ち**: SAM3 は visible-only segmentation で、かつ各 prompt は独立 session で動く。よって 2D image 上で複数 prompt のマスクが同じ pixel に立つことは**物理的にほぼ起きない**（境界誤差で 1〜数 pixel が触れる程度。§9.3 smoke で <1% を verify）。重なりが発生しても辞書順最後の色になる、という挙動が予測可能なら十分。

**Why 辞書順**: `prompts_with_initial_bbox` の入力順は planner の都合で変わりうる（脆い）。track_id は内部表現で外部から見えない。**prompt 文字列の辞書順は人間が読みやすく、再現性 100%**。SO101 dataset の prompt は ASCII 想定（§11.2 で non-ASCII 時の挙動を未決事項として明示）。

### 5.3 Palette

10 色固定の **`builtin_10`** palette を採用（matplotlib `tab10` から取った RGB 値を本 spec 内に embed）:

```python
# RGB uint8 — matplotlib tab10 由来のスナップショット
BUILTIN_10 = [
    (31, 119, 180),    # blue
    (255, 127, 14),    # orange
    (44, 160, 44),     # green
    (214, 39, 40),     # red
    (148, 103, 189),   # purple
    (140, 86, 75),     # brown
    (227, 119, 194),   # pink
    (127, 127, 127),   # gray
    (188, 189, 34),    # olive
    (23, 190, 207),    # cyan
]
```

**割当方法**: prompt の出現順（辞書順 sort 後の index）で `BUILTIN_10[idx % 10]`。idx ≥ 10 のケースは §12.3 未決事項。

**Why `builtin_10` という名前か（"tab10" と呼ばない理由）**: 値は matplotlib `tab10` から取っているが、本実装は matplotlib に依存しない（mimicanno の declared deps に matplotlib は無い、§7.1 で `palette: Literal["builtin_10"] = "builtin_10"` と明示する）。`palette: str = "tab10"` と書くと「matplotlib が tab10 を更新したら追従するのか」「カスタム matplotlib palette を渡せるのか」という未来の誤解を招く。本実装は**固定 10 色 snapshot** であり、matplotlib のバージョンとは独立。よって名前も独立にする。

**Why この 10 色**: 人間にも Gemma にも識別容易（matplotlib が学術論文の図で使う標準色）。Gemma の事前学習データに登場する色名（red/blue/green/etc.）と一致しているはずで、色名認識精度が他 palette より高いと予想（§12.6 未検証）。

### 5.4 Track lost 時（部分的）

「ある keyframe で 1 prompt のマスクは取れたが、別 prompt のマスクが None」のケース。

- 該当 prompt のマスクは描画しない（skip）
- prompt 凡例（§6）には**残す**: 「red=gripper, blue=red_block」と書いてあるのに gripper のマスクが見えない frame でも、Gemma に「凡例どおりのマスクが見えるべき場所に何もない」=「gripper がいない / 見えない / 失敗」を推論させる方が情報量が多い
- 凡例の文言は §6.1 で「may be temporarily occluded」と一文足す（部分 lost を Gemma が解釈できるように）

**Why 凡例から除外しないか**: keyframe ごとに凡例を変えると §6.3 の「segment 共通凡例」と矛盾し、token 数も増える。さらに「green=red_block」と書いておいて画面に green が無くても、Gemma 側に「occlusion で隠れている」と解釈する手がかり（§6.1 の文言）を与えれば情報量は損なわれない。

### 5.5 全 prompt のマスクが空の keyframe

「ある keyframe で全 prompt が同時に track lost」のケース。

- **生フレームをそのまま渡す**（合成スキップ）
- **凡例文字列は prompt から省く**: マスクが 1 つも無いのに凡例があると Gemma が混乱する。「色付き領域は…」という説明文自体を suppress
- ただし**そのケースは error ではない**: 全 prompt 同時 lost は SO101 でも稀ではあるが、abort はしない

**Why 凡例 suppress（§5.4 との非対称）**: §5.4 は「一部 lost、視覚的アンカーが残る」ので凡例が「嘘の約束」にならない（一部の色は実際に見えている）。§5.5 は「視覚的アンカーがゼロ」で凡例を残すと**全色が嘘の約束**になり（"red=gripper" と言っているのに red が画面に無い）、Gemma が凡例自体を信用しなくなるリスク > 凡例の情報量。

**Why 凡例 suppress を keyframe 単位ではなく segment 単位で判定するか**: 凡例は segment 共通（§6.3）。1 segment 内に「全 lost keyframe」と「部分 lost keyframe」が混在することはあり得るが、その場合は「部分 lost あり」を優先して凡例を出す（= segment 内に視覚的アンカーが 1 frame でもある限り、凡例は出す）。「全 keyframe で全 prompt lost」の極端なケースだけ凡例 suppress。

---

## 6. プロンプト整合

### 6.1 色凡例の文言

`vlm_prompt.py` の system / user prompt の冒頭付近に 1 行追加:

> Colored translucent overlays (~40% opacity) mark tracked objects: red=gripper, blue=red_block, green=plate. An overlay may be absent in some frames if the object is temporarily occluded or out of view.

**Why "may be absent" 文言**: §5.4 の部分 track lost 時、凡例には残るが画面には色が出ない、という状況を Gemma に予告する。これがないと「凡例の約束が破られている = 凡例自体が信用できない」と Gemma が判断しかねない。

**Why "~40% opacity" を明示**: alpha 値を勝手に変えても凡例は同じ文言で運用したいので「概ね」を表す `~` を入れる。alpha=0.2 でも 0.6 でもこの文言で通る。

### 6.2 凡例ビルダ仕様

- 入力: `MaskCache` の `palette: dict[str, tuple[int, int, int]]`
- 出力: 文字列 `"red=gripper, blue=red_block, ..."`
- 色名は palette index → 英語色名（`tab10` の 10 色を本 spec で固定して英語名 dict を持つ）
- prompt は SAM3 へ渡したものをそのまま使う（英語想定）

### 6.3 keyframe ごとに凡例を作り直すか、segment 共通か

**segment 共通**: 1 segment 内で keyframe 間で prompt の出現はほぼ一定（track lost 程度の差）。凡例を keyframe 単位で動的に変えると Gemma に混乱を与える + token 数増。

`vlm_prompt.py` は segment 単位で 1 凡例を組み立て、prompt 全体を 1 回だけ生成する。

---

## 7. Config と後方互換性

### 7.1 `MaskOverlayConfig` 新設

[config.py:120 ClipFeatureConfig](../../../mimicanno/config.py#L120) の隣に追加し、`VLMConfig.mask_overlay` として nest:

```python
from typing import Literal

@dataclass(slots=True, frozen=True)
class MaskOverlayConfig:
    enabled: bool = True
    alpha: float = 0.4
    palette: Literal["builtin_10"] = "builtin_10"   # 現状この 1 種のみ。matplotlib に依存しない固定 10 色。将来 builtin_20 等を追加する想定

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "alpha": self.alpha, "palette": self.palette}


@dataclass(slots=True, frozen=True)
class VLMConfig:
    ...
    mask_overlay: MaskOverlayConfig = MaskOverlayConfig()
```

### 7.2 config_hash への取り込み

`VLMConfig.to_dict()` に `"mask_overlay": self.mask_overlay.to_dict()` を追加。**overlay の有無 / alpha 値で run_hash が変わる**ことで、ablation 比較時に同一 episode の異なる run が別 run として記録される。

### 7.3 CLI

- `--vlm-mask-overlay/--no-vlm-mask-overlay` (bool, default True)
- `--vlm-mask-alpha FLOAT` (default 0.4)
- palette 切替は CLI フラグを切らない（現状 tab10 のみ）

### 7.4 後方互換性

**enabled=False のときの保証**:

- `extract_frames_at_indices` 直後の生 keyframe をそのまま `ClipFeatureExtractor` の出力にする
- `vlm_prompt.py` の凡例文字列は出さない
- **bit-exact**: 既存の Phase 2/3 パイプライン（mask 機能登場以前）と完全に同じ keyframe 配列・prompt 文字列が出ることを §9.1 単体テストで保証

これは ablation の妥当性確保に必須。「マスク機能が役立っているか」を A/B 比較する際、同じ episode を `enabled=True/False` で 2 回回して Gemma 出力差分だけを見るためには、`enabled=False` 側が完全にレガシー挙動である必要がある。

**Why 既存テストへの影響**: `enabled` の default を `True` にすると既存テストの fixture がマスク合成版に変わる。回避策:

1. fixture 系テストは MaskCache を空で渡す（マスクが無い = 既存挙動と一致）
2. 実 SAM3 を使う smoke テスト側だけ enabled=True で動かす

**規約を実装で強制**: テストヘルパ `make_test_propagation_result(...)` の `masks` パラメータを default `None` にし、masks を渡すには明示が要る形にする。これにより「fixture テストでうっかり masks を埋めて CI が SAM3 fixture を要求し始める」事故を防ぐ。spec §9.1 のテスト設計に組み込む。

---

## 8. （旧 §8、§4.5 に吸収）

ライフサイクル / リソース管理は §4.5 にまとめた。本章は欠番。

---

## 9. テスト戦略

### 9.1 単体（fixture only、CI で回す）

| 対象 | テスト |
|---|---|
| SAM3Runtime mask 抽出 | fixture sam3 outputs dict（masks 含む）→ `FramePropagationResult.masks` の shape/dtype/値が一致 |
| RLE round-trip | `decode(encode(arr)) == arr` を任意 bool 配列 100 ランダムケース（hypothesis 既存依存にあれば使う、なければ自前 RNG） |
| Overlay 合成（性質ベース） | mask=0 → 出力 == 入力 / mask=1 単色 → `frame*(1-α) + color*α` pixel-exact / alpha=0 → 出力 == 入力 / alpha=1 + mask=1 → 出力 == 色 / 複数 mask 重なり → 辞書順最後の色 |
| ClipFeatureExtractor 統合 | MaskCache=空（None） → 既存 keyframe と bit-exact 一致（**§7.4 の後方互換性保証**） |
| ClipFeatureExtractor 統合 | MaskCache に 1 prompt 入り → 該当 pixel が変化、それ以外は不変 |
| MaskCache | get/prompts_at/all_prompts の決定性、辞書順返却 |
| 凡例ビルダ | palette 入力 → 期待文字列出力（snapshot 1本） |
| Track lost 挙動 | mask=None の prompt は描画 skip、凡例には残す |
| 全 mask 空挙動 | 全 prompt None → 生 keyframe + 凡例 suppress |
| Config | `enabled=False` で `to_dict()` の `mask_overlay.enabled == False`、config_hash が enabled 値で変わる |

### 9.2 統合（fixture）

- `vlm_prompt` スナップショット 1本: 色凡例文字列が prompt に含まれる
- `vlm_prompt` スナップショット 1本: `enabled=False` で凡例文字列が含まれない（後方互換性）

### 9.3 実 SAM3 smoke（CI 外、手動）

既存 `tests/test_phase3_real_sam3_smoke.py` 拡張 + 新規 case:

| Smoke | 内容 |
|---|---|
| Mask shape 確認 | `out_binary_masks` を含む propagation 出力が MaskCache に格納される、shape == keyframe size |
| Overlap 検証 | SO101 grasp segment（gripper × object 重なり）で全 prompt mask の logical AND coverage が **<1%**。**閾値根拠**: 境界誤差オーダー試算（~0.001%）に対し 3 桁余裕。実測値ログを §11 で再評価予定 |
| Prompt 区別 | segment 内 keyframe で「centroid 距離 > 10px の prompt ペアが少なくとも 1 frame 存在」。bbox 取り違えで全 prompt が同位置になるバグの最低限の検出 |

### 9.4 実データ sanity（autonomy exit criteria）

- SO101 1 episode をフル run（`mimicanno annotate ... --vlm-dump-dir <dir>`）
- 自動 assertion:
  - `<dir>/<segment_id>/attempt_*/keyframe_*.png` が全 segment 分生成される
  - 各 keyframe で mask coverage > 0（マスクが描画されている）
  - shape/dtype が想定通り（uint8 RGB）
  - prompt 文字列に色凡例が含まれる
- 人間レビュー（autonomy exit criteria の判断材料）:
  - マスクが正しい物体を覆っているか
  - Gemma の segment label が object-aware（label が物体名を参照）か
  - alpha=0.4 が視認バランス良いか（生画像が読めるか、色が判別できるか）

---

## 10. リスクと前提

### 10.1 SAM3 API drift

`out_binary_masks` の key 名 / shape / dtype は SAM3 native API の current 仕様（[sam3/sam3/model_builder.py:1294](../../../sam3/sam3/model_builder.py#L1294) で確認）。submodule pin を上げる時に変わる可能性があり、**SAM3Runtime layer に取得を隔離**することで影響範囲を 1 ファイルに閉じ込める設計（既に [sam3_runtime.py:1-5](../../../mimicanno/object_tracker/sam3_runtime.py#L1-L5) のレイヤ規約で「`sam3` を import するのはこのファイルのみ」が確立済み）。

### 10.2 SAM3 推論の determinism

GPU 上の non-determinism（cuDNN, batch ordering）が `out_binary_masks` の境界 1〜数 pixel に揺らぎを生む可能性がある。これは config_hash と再現性に影響する（同じ config で 2 回回すと keyframe pixel が微妙に違う）。**現状は許容**。Phase 3 既存パイプラインも同じ性質を持っており、本機能で新規導入される問題ではない。

### 10.3 メモリ膨張

§4.5 の見積もりは prompt 数 5、frames 1500 想定。これを超える episode では in-memory RLE が膨らむ。10 prompts × 5000 frames × 圧縮 100:1 ≈ 約 200 MB。**SO101 では非該当だが、より大きい dataset で破綻する可能性あり**。§11 で監視対象。

### 10.4 Gemma の色解釈失敗

Gemma が "red" と "orange" を混同する、"translucent" 概念を理解しない、色凡例を無視してマスク色を直接読まない、などの empirical なリスクがある。**未検証の前提**として §11 に明示。Phase 5 sanity check で alpha 値 + palette の組合せを軽く eval する。

---

## 11. 観測可能性 / ロギング

production run で以下をログに出す（`logger.info` レベル、§9.3 smoke の入力にもなる）:

| ログ項目 | 出力単位 | 用途 |
|---|---|---|
| segment 内 mask coverage 統計（mean / min / max） | segment 単位 | マスクが空 / 過剰のケース検知 |
| Track lost した prompt と frame_index range | episode 単位 | §5.4/5.5 の発動頻度 |
| RLE encode/decode のエラー | 例外時のみ | pycocotools の異常入力検知 |
| 全 prompt mask の overlap coverage（logical AND の pixel ratio） | segment 単位 | §9.3 の <1% 閾値の実測値、§11.1 の再評価入力 |
| MaskCache 総バイト数 | episode 単位 | §10.3 メモリ膨張監視 |
| Palette 割当（prompt → 色名） | episode 単位 | デバッグ容易化 |

ログは既存の `_emit_vlm_log`（[pipeline.py:122](../../../mimicanno/pipeline.py#L122)）パターンに合わせて構造化 JSON 出力。

---

## 12. 未決事項（open questions）

### 12.1 Smoke <1% overlap 閾値の再評価

**現状**: §9.3 で <1% を保守的閾値として採用。境界誤差オーダー（~0.001%）に対して 3 桁余裕。

**再評価予定**: §11 の overlap coverage ログを 10 episode 程度蓄積後に実測値分布を見て、`<0.1%` などへ締めるかを判断。SAM3 バージョンアップでの境界処理変動も観測対象。

### 12.2 Prompt が non-ASCII になった場合の辞書順挙動

**現状**: SO101 dataset の prompt は英語前提（`extract_entities` を Gemma で駆動するが、task 文も英語）。よって ASCII 辞書順で問題なし。

**未決**: 将来 task 多言語化（日本語 prompt 等）時、Python `sorted()` の Unicode codepoint 順は決定論ではあるが人間直感とずれる。NFC 正規化を挟むか、locale-aware sort にするか、ASCII 化を強制するかを再検討。

### 12.3 Palette 10 色超のケース

**現状**: `tab10` のみ採用、`idx % 10` で循環（11 個目が 1 個目と同色になる）。

**未決**: SO101 では 5 prompts 程度で十分だが、より複雑な dataset（household manipulation で multi-object scene）では 10 prompts を超え得る。`tab20` 切替、または高彩度色を 20 色程度自前定義する案。

### 12.4 将来の full-resolution mask 需要

**現状**: §4.4 で keyframe size にダウンサンプル済み保管。元解像度は捨てる。

**未決**: 別用途（例: high-res visualization、mask-based metric 計算、Phase 5 edit UI へ流用）で full-res が必要になったら、MaskCache を「keyframe 用ダウンサンプル層 + 元解像度層」の 2 層に拡張する。**現状の用途では keyframe size で十分**、要件出てから追加。

### 12.5 Alpha=0.4 のデフォルト根拠

**現状**: 経験則（半透明として標準的、生画像も読める）。

**再評価予定**: Phase 5 sanity check で `alpha={0.2, 0.4, 0.6}` の比較を行い、Gemma label 出力の object-awareness が最大化される値を選ぶ。比較は人間レビュー（label 文字列の質的評価）。

### 12.6 Gemma の色名解釈精度

**現状**: §10.4 のとおり未検証。Gemma が "red" と "orange" を確実に区別できるか、"translucent overlays" の概念を理解するか。

**再評価予定**: Phase 5 sanity check の人間レビューで、segment label が「マスク色を参照した object 識別」を示すかを確認。失敗パターンが多ければ、色凡例の文言を強化する（"the red-tinted region", "the object highlighted in blue" など）。

---

## 13. 参照

### 内部 spec

- `2026-04-27-mimicanno-phase2-vlm-labeling-design.md` — VLM labeling の元設計
- `2026-04-28-mimicanno-phase3-sam3-tracking-design.md` — SAM3 tracking の元設計
- `2026-05-04-sam3-submodule-backend-design.md` — SAM3 native API 採用の経緯

### 外部参照

- pycocotools mask format: <https://github.com/cocodataset/cocoapi>
- matplotlib tab10 palette
- SAM3 multiplex tracking: `sam3/sam3/model/sam3_multiplex_tracking.py`
