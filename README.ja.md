# MimicAnno

[English](README.md) | **日本語**

ロボット模倣学習エピソード向けのオフラインサブタスクアノテーションパイプライン。LeRobot v3 データセットを入力すると、フレームごとのサブタスクラベル (`approach_object`, `grasp_object`, …) と SARM 学習可能な parquet 出力を返します。

```
LeRobot v3 episode (video + state + action + task text)
        │
        ▼  mimicanno annotate
runs/<canonical>/{annotation.json, manifest.json, ...}
        │
        ▼  mimicanno export
SARM-trainable LeRobot v3 dataset (subtask_index + sidecar)
```

## 機能

- **シグナルベースの境界検出** — gripper transition / EEF 速度の谷 / action-norm 変化点 (境界検出に ML は使わない)。
- **VLM ラベリング** — Gemma 4 (または任意の image-text-to-text HF モデル) でセグメントごとに、許可ラベルリストの強制 + JSON Schema 検証。
- **SAM3 物体追跡** — task text からプロンプト自動生成、サンプリングフレーム追跡、統合境界スコア。
- **時系列スムージング** — 同一ラベル merge / min-duration 吸収 / Viterbi relabel (オプション)。
- **SARM 即学習可能な export** — フレームごとの `subtask_index`、エピソードごとのサブタスクリスト、ロスレス `mimicanno_segments.parquet` サイドカー、atomic publish、冪等な reuse。
- **React/Vite レビュー UI** — タイムライン + 波形 + 境界マーカー、HTTP バックエンド経由で phase / boundary / reviewed / label の編集に対応。
- **プラガブルなロボットアダプタ** — SO100 / Koch / Aloha 同梱、SO101 や任意の LeRobot v3 レイアウトは YAML で設定可能。

## インストール

Linux + `uv`, `conda`, `python3.11+`, `node` (>=20), `pnpm`, `ffmpeg`, `git`, `curl`, `lsof` が必要。

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno

# 一発セットアップ (submodules / core / unidac / frontend / gated weights)。
# SAM3 と Gemma 4 のために事前に `HF_TOKEN` を export するか `hf auth login` を実行。
bash scripts/setup_envs.sh

# 個別実行 (不要な step を skip):
bash scripts/setup_envs.sh --core --frontend     # UI のみ
bash scripts/setup_envs.sh --all --skip-weights  # モデル DL を skip

# 再実行は idempotent (各 step は sentinel 一致で skip)。
```

レビュー UI を起動:

```bash
bash scripts/start_ui.sh                                  # :8000 / :5173
API_PORT=8001 VITE_PORT=5174 bash scripts/start_ui.sh
bash scripts/start_ui.sh --runs-root /path/to/runs
```

## クイックスタート

### 1. エピソード 1 本にアノテーション

```bash
mimicanno annotate \
  --video        path/to/dataset/videos/.../episode_000000.mp4 \
  --parquet      path/to/dataset/data/.../episode_000000.parquet \
  --task         "Put the tape into the bottle" \
  --robot        generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it@<sha>" \
  --sam3-checkpoint /path/to/sam3.ckpt \
  --runs-root    ./runs
```

`runs/<canonical_name>/{manifest,annotation,boundaries,signals,tracks}.json` を生成します。同じ config + 同じ入力での再実行は no-op (冪等)。

Phase は累積的: `--target-phase 1` (境界検出のみ、VLM/SAM3 不要)、`--target-phase 2` (+ VLM)、`--target-phase 3` (+ SAM3、checkpoint 必須)、`--target-phase 4` (+ smoothing)。

CPU のみ・driver 不一致の環境では `--vlm-device cpu --vlm-timeout-sec 600` を追加 (8 セグメントのエピソードで GPU 1 分 ≒ CPU 1 時間が目安)。

### 2. SARM 学習可能なデータセットへ export

```bash
mimicanno export \
  --dataset      path/to/dataset \
  --runs-root    ./runs \
  --target-phase 4 \
  --profile      so101_sarm \
  --out          path/to/dataset_annotated
```

デフォルト `--symlink-data` モードでは `dataset_annotated/` を生成し、`videos/` は元データセットへの symlink、`data/` には `subtask_index` + canonical action 列を追加、`meta/` には `subtasks.parquet` / `episodes/.../file-NNN.parquet` (`<prefix>_subtask_*` リスト列) / ロスレスな `mimicanno_segments.parquet` サイドカーを新規生成します。

その他のモード:
- `--copy-data` — `videos/` も実コピー (完全独立)。
- `--in-place --yes-i-mean-it` — 元データセットを直接書き換え。`<source>/.mimicanno-backup-<ISO>/` にバックアップを残します。

冪等: 同一引数での再実行は短絡 (no-op)。

### 3. GEM4 タスクを 26B QLoRA アダプタで一括アノテーション

`scripts/batch_annotate.py` の thin wrapper。26B VLM を **1 回だけ**
ロードして全 episode で使い回すので、CLI 直叩きと比べてモデルロード
時間 (~2 分/ep) を ep 回数分節約できる。`unsloth_env` conda 環境と
`models/gem4_26B_adapter/` が必要。

```bash
# GPU 1 枚で 1 タスクの全 episode を流す
GPU=0 bash scripts/run_26B_gem4.sh open_the_jar

# 2 GPU で episode 範囲を分割して並列実行
GPU=0 START=0   END=151 bash scripts/run_26B_gem4.sh pick_up_bottle &
GPU=1 START=152 END=303 bash scripts/run_26B_gem4.sh pick_up_bottle
```

タスク: `open_the_jar` | `pick_up_bottle` | `replace_the_cookie`。
出力先デフォルトは `runs/gem4_<task>_26B/`。SO101 等 wrapper が無い
データセットは `batch_annotate.py` を直接呼ぶ:

```bash
python scripts/batch_annotate.py --dataset so101 --gpu 0
```

**4B ベースライン** (素の Gemma 4 E4B-it を transformers で直接ロード、
QLoRA なし) は parallel な wrapper を使う。26B より高速だが精度寄りでは
ない。リポジトリの `.venv` (uv) で動く、`unsloth_env` 不要:

```bash
GPU=0 bash scripts/run_4B_gem4.sh open_the_jar
GPU=0 START=0 END=103 bash scripts/run_4B_gem4.sh pick_up_bottle &
```

出力先は `runs/gem4_<task>_4B/`。実体は `scripts/batch_annotate_4B.py`
(26B 版と同じ CLI shape)。

### 4. プログラマティック API

```python
from mimicanno import export, ExportProfile

result = export(
    dataset_root="/path/to/dataset",
    runs_root="./runs",
    target_phase=4,
    profile="so101_sarm",            # 名前または YAML パス
    out="/path/to/dataset_annotated",
    output_mode="symlink",           # "symlink" | "copy" | "in_place"
)
print(result.episode_count, result.subtask_count, result.reused)
```

タスク・ロボット特化のバッチランナーは [`scripts/`](scripts/README.md) を参照。

## 対応ロボット

| Adapter | 備考 |
|---|---|
| `aloha` | LeRobot v3、aggregated 14-D `observation.state`、Cartesian EEF あり |
| `koch` | Joint-only、6-D `observation.state` |
| `so100` | Joint-only、6-D `observation.state` (`lerobot/svla_so100_pickplace` 等で使用) |
| `generic` | YAML 設定可。split-state レイアウト (SO101 等) と直接 rotvec passthrough をサポート |

SO101 用 generic adapter の例 (`tests/exports/fixtures/so101_robot_config.yaml`):

```yaml
schema_version: "0.2.0"
name: so101
gripper_column:        observation.state.gripper_pos
gripper_scale_min:     0.0
gripper_scale_max:     60.0   # SO101 全 36 ep の生 gripper 範囲: 3.95..53.79; 60 は +12% ヘッドルーム
eef_xyz_column:        observation.state.ee_pos
eef_rotvec_column:     observation.state.ee_rotvec
eef_quat_column:       null
```

新しいロボットを追加するには、このテンプレートをコピーして該当する列名と gripper の値域を書き、`--robot-config` で渡すだけ。コード変更は不要です。

## Export profile

`mimicanno/configs/exports/` に 3 つのデフォルトプロファイル:

- `so101_sarm.yaml` — generic adapter 経由の SO101、body-frame `ee_delta_6d` + gripper extra、`mimicanno_*` プレフィクス。
- `aloha_sarm.yaml` — Aloha 専用。
- `generic.yaml` — 新規データセット用テンプレート。

profile YAML が export の挙動全部 (source adapter / action 表現の delta_basis (`body_frame_t` / `world` / `base`) / per-frame extra columns / sidecar 配置 / gates (`require_reviewed`, `forbid_unlabeled_segments`, `forbid_degraded_pipeline`)) を制御します。`mimicanno/jsonschemas/export_profile.schema.json` でバリデート。

## Hand pipeline

GoPro Hero 11 Max Lens Mod の魚眼動画 (2704×1520, 29.97 fps, OPENCV_FISHEYE) から、フレームごとの 3D 手姿勢を抽出するオプションのサブパイプライン。

**MediaPipe Hand Landmarker** (2D キーポイント + palm-axis 由来の手首回転、Apache 2.0) と **UniDAC** monocular depth (MIT) を融合して、カメラ座標系での metric な手首位置と指間距離を出力します。

```bash
# Phase A — 深度前計算
conda activate unidac
python scripts/precompute_depth.py --video data/video/new/<NAME>.MP4

# Phase B — 手姿勢推定
python scripts/run_hand_estimation.py --video data/video/new/<NAME>.MP4

# 両 phase をすべての動画について GPU 並列で実行
bash scripts/run_all_pipeline.sh
```

出力は `data/depth/<NAME>/` と `data/hands/<NAME>/` 配下。スキーマ・フィールド定義・バッチオプションは [`docs/hand-pipeline.md`](docs/hand-pipeline.md) を参照。

## サーバ

静的な `runs/` ツリーと同じ JSON 形状を返し、optimistic locking 付きでセグメント編集を受け付ける HTTP バックエンド。`[server]` optional dependency group で遅延インストール。

```bash
uv sync --extra server
MIMICANNO_REVIEWER=takaki uv run --extra server mimicanno serve \
    --runs-root runs/ \
    --host 127.0.0.1 --port 8000 \
    --cors-origin http://localhost:5173
```

`MIMICANNO_REVIEWER` は起動時にキャプチャされ、各編集の `reviewer_id` として保存されます。未設定・空文字なら `reviewer_id=null`。

エンドポイント (read):
- `GET /healthz` — liveness probe
- `GET /api/runs/index.json`, `GET /api/runs/<name>/<artifact>` — 静的ツリーと同形状 (`manifest`, `annotation`, `boundaries`, `signals`, `tracks`)
- `GET /api/labelset` — `{labels, labels_yaml_sha256}`

エンドポイント (編集、`If-Match: "<run_hash>"` 必須):
- `PATCH /api/runs/<name>/segments/<id>` — `phase` を変更
- `PATCH /api/runs/<name>/segments/<id>/labels` — segment ごとの label リストを更新
- `PATCH /api/runs/<name>/segments/<id>/reviewed` — reviewed フラグを更新
- `PATCH /api/runs/<name>/boundaries/<id>` — 境界を移動

PATCH 成功時は `runs/index.json.lock` の file lock 下で annotation → manifest → index を atomic に書き換え、新しい `ETag` を返します。内部レイアウト・契約・テスト階層は [`mimicanno/server/README.md`](mimicanno/server/README.md) を参照。

フロントエンド: ビューアを `?api=1` 付きで開くと `/api/runs/` 経由でフェッチし、編集 UI が有効になります。

## 開発

```bash
env -u PYTHONPATH uv run pytest -q                    # 全テスト (約 40 秒)
env -u PYTHONPATH uv run mypy --strict mimicanno/     # 型チェック
env -u PYTHONPATH uv run ruff check mimicanno/        # lint
```

`PYTHONPATH=` は ROS2 humble がパス汚染してくる環境向けの対策。ROS2 を入れてなければ無害。

設計の経緯と理由は `docs/superpowers/specs/` 配下、TDD タスクリスト形式の実装プランは `docs/superpowers/plans/` 配下。

## ライセンス

MIT ([`LICENSE`](LICENSE) を参照)。
