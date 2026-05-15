# Hand Viewer — design spec

**Date:** 2026-05-15 (rev2: 4 BLOCKER fixes)
**Status:** draft
**Author:** takaki-maeda-99

---

## 1. Goal

既存の hand pipeline (`mimicanno/hand_pipeline/`) が生成した per-frame `HandEstimate` データを、ブラウザで動画と並べて確認できる専用ページを追加する。

ユースケース: ロボット操作動画を再生しながら、手首の位置・向き・ピンチ距離をフレーム単位で確認する。

---

## 2. スコープ

### In scope
- `signals.json` フォーマットの拡張 — wrist xyz / Euler angles を追加 (v2)
- `run_hand_estimation.py` に `--signals-only --full-signals` フラグ追加で既存 pkl から v2 signals.json を再生成
- `mimicanno serve` に `--hands-root` オプション追加 + `/api/hands/` ルート群
- フロントエンド `HandViewer` ページ (`?hand=<episode>`)
- `RunList` ページに hand episodes へのリンクを追加

### Out of scope
- MANO mesh / skeleton の 3D レンダリング (overlay.mp4 で代替)
- 手の動きに基づく segment 境界の自動提案
- signals.json の per-frame 編集
- multi-camera 対応 (wrist cam 等)

---

## 3. データ構造

### 3.1 signals.json v2 フォーマット

```json
{
  "schema_version": 2,
  "frame_000000": {
    "right": {
      "pinch_m": 0.034,
      "cam_t": [0.12, -0.05, 0.63],
      "euler_deg": { "yaw": 45.6, "pitch": -8.1, "roll": 12.3 },
      "depth_ok": true
    },
    "left": null
  }
}
```

フィールド定義:
- `cam_t`: HaMeR カメラ座標系の手首位置 [m]。`depth_ok=true` の場合は UniDAC で補正済み。`depth_ok=false` の場合は HaMeR 擬似メトリック (絶対値の信頼性低、相対変化は有効)。smoothing なし。
- `euler_deg`: `global_orient` (3×3 回転行列) を `scipy.spatial.transform.Rotation.from_matrix(R).as_euler('ZYX', degrees=True)` で ZYX 分解。返り値配列の順は `[yaw, pitch, roll]` なので `euler_deg = {"yaw": arr[0], "pitch": arr[1], "roll": arr[2]}` と展開する。手が検出されている限り (`depth_ok` に関わらず) 常に出力する。
- `pinch_m`: 親指–人差し指間距離 [m]。Gaussian smoothing (σ=2 frames) 適用済み。cam_t 非依存。
- `depth_ok`: `wrist_depth_m is not None`。cam_t の補正品質と pinch 距離の参考品質を両方示す。v1 の `depth_ok` と同義。**v1 にあった `pinch_depth_ok` は v2 では廃止し `depth_ok` に統合。**
- 手が検出されなかったフレームは `"right": null` または `"left": null`。両手未検出でもフレームキーは `{"right": null, "left": null}` として保持する。
- `schema_version: 2` で v1 (pinch のみ、キー名 `value`) と区別。フロントエンドは v2 以外を拒否してエラー表示する (後述)。

v1 signals.json (GX010176 に既存) は v2 生成コマンドで上書きする。

### 3.2 `/api/hands/index.json`

```json
{
  "schema_version": "0.1.0",
  "episodes": [
    {
      "episode_id": "GX010085",
      "fps": 29.97,
      "total_frames": 1397,
      "frames_with_hands": 1397,
      "signals_ready": true,
      "video_url": "GX010085/video",
      "signals_url": "GX010085/signals.json",
      "meta_url": "GX010085/meta.json"
    }
  ]
}
```

- `signals_ready`: `signals.json` が存在し `schema_version == 2` であること。false の場合フロントエンドは再生成が必要な旨を表示。
- URL は `/api/hands/` 相対パス。

### 3.3 `/api/hands/{episode}/video`

- `meta.json["video_source"]` のパスを解決して Range request 対応で配信。
- パス解決: `repo_root / meta["video_source"]`。`repo_root` は `mimicanno serve` を呼び出した時の `Path.cwd()` (ユーザーは常にリポジトリルートから実行)。
- セキュリティ: resolved path が `repo_root` の配下にあることを `resolved.resolve().is_relative_to(repo_root.resolve())` で確認。失敗時は 400。
- ファイルが存在しない場合は 404。

---

## 4. サーバー変更

### 4.1 `mimicanno serve` オプション

```
--hands-root PATH   hand pipeline 出力ディレクトリのルート (省略時: /api/hands/ は 503)
```

起動例:
```bash
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
  --runs-root runs/so101_phase4_v5 \
  --hands-root data/hands \
  --cors-origin http://localhost:5173
```

`repo_root = Path.cwd()` をサーバー起動時に確定し、hands router に渡す。

**制約 (既知の制限):** `mimicanno serve` は常にリポジトリルートから実行することを前提とする。systemd service 等で異なる CWD から起動した場合、`repo_root` が誤って解決され video endpoint が 400 を返す。その場合は `--repo-root PATH` オプション (将来追加、本 spec の out of scope) で明示指定する。

### 4.2 新規ルート (`mimicanno/server/hands_routes.py`)

| Method | Path | 説明 |
|--------|------|------|
| GET | `/api/hands/index.json` | episodes 一覧 |
| GET | `/api/hands/{episode}/meta.json` | meta.json をそのまま返す |
| GET | `/api/hands/{episode}/signals.json` | signals.json をそのまま返す |
| GET | `/api/hands/{episode}/video` | 元動画 (Range 対応 FileResponse) |

セキュリティルール (全ルート共通):
- `hands-root` が未設定 → `503 Service Unavailable` (`{"error": "hands_root not configured"}`)
- `episode` パスコンポーネントに `..` または `/` が含まれる、あるいは絶対パス → `400 Bad Request`
  - 実装: `episode` を `Path(episode)` に変換し `parts` が 1 要素かつ `..` でないことを確認
- ファイルが存在しない → `404 Not Found`
- `/video` ルートは上記に加えて:
  - `meta.json` に `video_source` キーが存在しない → `400 {"error": "meta.json missing video_source"}`
  - `video_source` が `repo_root` 外を指す → `400 {"error": "video_source outside repo_root"}`

---

## 5. フロントエンド変更

### 5.1 ルーティング

URL パターン: `/?hand=GX010085&api=1`

- `App.tsx`: `?hand=<episode>` が存在する場合 `<HandViewer episodeId={...} />` を描画。
- `?run=` と `?hand=` は排他 (両方ある場合は `?run=` 優先)。

### 5.2 `HandViewer` コンポーネント

```
frontend/src/components/HandViewer.tsx
```

レイアウト (TODO.md §「レイアウト」準拠):
```
┌─────────────────────────────────────┐
│                                     │
│   VideoPlayer (height: 70vh)        │
│                                     │
├─────────────────────────────────────┤
│  HandDataPanel (height: 30vh)       │
│                                     │
│  [右手] cam_t xyz | euler | pinch   │
│  [左手] cam_t xyz | euler | pinch   │
└─────────────────────────────────────┘
```

状態管理:
- signals.json を全フレーム一括ロード (`useEffect` で fetch)。
- `schema_version !== 2` の場合はエラー表示: `"signals.json が古いフォーマットです。--signals-only --full-signals で再生成してください"`。
- `currentTimeSec` → `currentFrame = Math.round(currentTimeSec * fps)` でフレーム index を算出。
- `HandDataPanel` は `signals["frame_NNNNNN"]` を参照して表示。
- `depth_ok=false` の場合は値をグレーアウト + `(推定)` バッジ。

graceful degrade / エラー状態:
- `/api/hands/index.json` が 503/network error → `<div>手のデータがありません</div>` (エラートースト不要、静かに非表示)
- `index.json` にリクエストの `episodeId` が含まれない → `<div>エピソードが見つかりません: {episodeId}</div>`
- signals.json なし (`signals_ready=false`) → `"このエピソードは signals.json が未生成です"` と表示
- signals.json の `schema_version !== 2` → `"signals.json が古いフォーマットです。--signals-only --full-signals で再生成してください"` と表示

### 5.3 `RunList` への追加

`RunList.tsx` 下部に手エピソード一覧セクションを追加。`/api/hands/index.json` を fetch し (失敗時は非表示)、各エピソードへのリンク `/?hand=<id>&api=1` を表示。`signals_ready=false` のエピソードはリンクをグレーアウトして `(signals未生成)` と付記。

---

## 6. `run_hand_estimation.py` 変更

### 6.1 新フラグ

```
--signals-only      per-frame 推定をスキップし、既存の frames/*.pkl から signals.json のみを再生成する。
                    --video と --depth は省略可能になる。fps と画像サイズは --out ディレクトリの
                    meta.json から読み込む。meta.json が存在しない場合はエラー終了。
--full-signals      signals.json を v2 フォーマットで生成 (cam_t + euler_deg 付き)。デフォルトは v1 互換
```

`--signals-only --full-signals` の組み合わせで、既存 pkl から v2 signals.json を一括生成できる。

### 6.2 `_generate_signals()` 変更

`full: bool = False` パラメータ追加:
- `full=False` (デフォルト): 既存 v1 フォーマット (`schema_version: 1`, pinch のみ)。後方互換。v1 のキー名は `value` (pinch_m ではない)。
- `full=True`: v2 フォーマット。`"value"` を `"pinch_m"` にリネームし、各手エントリに `cam_t` (list[float] 3要素), `euler_deg` (dict: yaw/pitch/roll, 手検出時は必ず出力), `depth_ok` (bool) を追加。`pinch_depth_ok` フィールドは出力しない (v2 では `depth_ok` に統合)。

**フレームキー保持ルール:** 両手とも未検出のフレームも `{"right": null, "left": null}` としてフレームキーを出力する (現行実装のようにキーを削除しない)。フロントエンドはキー不在 (`undefined`) を考慮しなくてよい。

Euler 変換:
```python
from scipy.spatial.transform import Rotation
arr = Rotation.from_matrix(h.global_orient).as_euler('ZYX', degrees=True)
# arr = [yaw, pitch, roll]
euler_deg = {"yaw": round(float(arr[0]), 3), "pitch": round(float(arr[1]), 3), "roll": round(float(arr[2]), 3)}
```

既存 pkl は変更しない。

### 6.3 `--signals-only` 実装

フレーム推定ループをスキップし、`frames/` ディレクトリの既存 pkl を読み込んで `_generate_signals()` を呼ぶ。フレーム index はファイル名から `int("frame_NNNNNN".split("_")[1])` で復元。

---

## 7. テスト方針

| レイヤー | テスト |
|---------|--------|
| `_generate_signals` v2 | `tests/hand_pipeline/test_pipeline_signals.py` — schema_version=2, euler shape (3 keys), cam_t shape (list[float] len 3), depth_ok bool, NaN 手フレームで null |
| `/api/hands/` routes | `tests/server/test_hands_routes.py` — index 正常系, signals_ready フラグ, 404, 400 (path traversal `../`), 400 (video_source outside repo_root), 503 (hands-root なし), video Range request → 206 |
| `HandViewer` component | `frontend/.../HandViewer.test.tsx` — frame index 計算, depth_ok グレーアウト, schema_version≠2 エラー表示, 503 graceful degrade |
| `RunList` + hands | `frontend/.../RunList.test.tsx` — 新規作成: 503 のとき手セクション非表示, signals_ready=false でグレーアウト |

---

## 8. 制約・注意事項

- 元動画 MP4 は大きい (GX010085 ≈ 47秒)。`FileResponse` は Range 対応済みなので `<video>` のシーク負荷は許容範囲。
- signals.json は全フレーム一括ロード (GX010085 で 1397 フレーム × ~5フィールド ≈ 数 100KB)。許容範囲。
- `cam_t` の絶対値は `depth_ok=false` のフレームで信頼性低。UI でフラグ表示必須。
- ZYX Euler の出力順は `[yaw, pitch, roll]` であり `[roll, pitch, yaw]` でないことに注意 (SciPy 仕様)。
- v1 signals.json (GX010176 に存在) は T1 の `--signals-only --full-signals` で上書きする。
