# TODO

## Hand pipeline

- [x] **人差し指と親指の間の距離計測** (pinch distance)
  - `HandEstimate.pinch_distance_m` として実装済み (`|joints_local[4] - joints_local[8]|` [m])
  - cam_t 非依存 (MANO joints_local はメトリック): refine=True/False 両パスで計算
  - `signals.json` に per-frame 出力 (Gaussian smoothing σ=2frames, NaN-aware)
  - フォーマット: `{"schema_version": 1, "frame_NNNNNN": {"right": {"value": float, "depth_ok": bool}, "left": ...}}`

## MimicAnno UI

- [ ] **手の状態ビューア** (MimicAnno UI に実装予定)
  - 上 70%: 元動画
  - 下 30%: 手首位置 (x, y, z)・手首の向き・親指–人差し指間の絶対距離 をフレームごとに表示
  - 計算はパイプライン済み (pkl / signals.json) → UI は読み込むだけでよい

  ### レイアウト
  ```
  ┌─────────────────────────────────────┐
  │                                     │
  │        元動画 (上 70%)              │
  │                                     │
  ├─────────────────────────────────────┤
  │  手の計測値パネル (下 30%)          │
  │                                     │
  │  [右手]  wrist xyz  / 向き / pinch  │
  │  [左手]  wrist xyz  / 向き / pinch  │
  └─────────────────────────────────────┘
  ```

  ### 表示項目と取得元
  | 項目 | 取得元 | 備考 |
  |------|--------|------|
  | 手首位置 x, y, z [m] | `HandEstimate.cam_t` | HaMeR カメラ座標系。UniDAC 深度補正済み (`wrist_depth_m` が非 None の場合) |
  | 手首の向き (Euler 角 or 回転行列) | `HandEstimate.global_orient` (3×3) | ロール・ピッチ・ヨーへの変換は UI 側で実施 |
  | 親指–人差し指 絶対距離 [m] | `HandEstimate.pinch_distance_m` | `depth_ok=True` のフレームのみ深度補正済み; それ以外は MANO メトリックスケール |

  ### データソース
  - per-frame: `data/hands/<episode>/frames/frame_NNNNNN.pkl` → `list[HandEstimate]`
  - 時系列 (smoothed): `data/hands/<episode>/signals.json`

  ### 実装上の注意
  - `depth_ok=False` のフレームは cam_t が HaMeR 擬似メトリックのため、xyz の絶対値は信頼性が低い (相対変化は有効)
  - 左手 MANO は右手の鏡像 (joint index は同一); global_orient の符号に注意
  - 計算自体はパイプライン実行時に完了しているため、UI は pkl / signals.json を読むだけでよい
