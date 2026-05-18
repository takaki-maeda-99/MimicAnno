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

Linux + `uv`, `conda`, `python3.11+`, `node` (>=22、Vite 8 が Node 20 サポート打ち切り)、`pnpm`, `ffmpeg`, `git`, `curl`, `lsof` が必要。

<details>
<summary>未インストールなら (one-liners — Ubuntu/Debian)</summary>

```bash
# uv (Python toolchain)
curl -Ls https://astral.sh/uv/install.sh | sh

# Node 22 (nvm) + pnpm (corepack)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
. "$HOME/.nvm/nvm.sh"
nvm install 22
corepack enable && corepack prepare pnpm@latest --activate

# Miniforge (conda)
curl -L -O https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh
bash Miniforge3-$(uname)-$(uname -m).sh

# ffmpeg + lsof (apt — distro 違うなら適宜)
sudo apt-get install -y ffmpeg lsof
```
</details>

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno

# 一発セットアップ (submodules / core / unidac / frontend / gated weights)。
# Hugging Face にログインしておく。gated repo (SAM3 / Gemma 4) には必須、
# それ以外も **強く推奨** — 匿名 DL は IP 単位レート制限があり、weights+
# datasets を一気に DL するとほぼ確実に弾かれる。
# `export HF_TOKEN=hf_xxx` か `hf auth login` で OK。
bash scripts/setup_envs.sh

# 個別実行 (不要な step を skip):
bash scripts/setup_envs.sh --core --frontend     # UI のみ
bash scripts/setup_envs.sh --all --skip-weights  # モデル DL を skip

# 再実行は idempotent (各 step は sentinel 一致で skip)。
```

bootstrap が自動化できない手動ステップが 2 つ — 下の Demo フローは両方使う:

**unsloth_env (GEM4 batch wrapper 用)**: Unsloth は CUDA 依存が壊れやすく
script 化していません。初回のみ:

```bash
conda create -n unsloth_env python=3.11 -y
conda activate unsloth_env
pip install unsloth
pip install -e .   # MimicAnno 本体 (wrapper が `import mimicanno` できるように)
```

**DINOv3 backbone (Hand pipeline Phase A 用)**: UniDAC が
`UniDAC/checkpoints/dinov3_vitl16_pretrain_lvd1689m-8aa4cbdd.pth`
(約 1.2 GB、Meta が license gate) を必須参照。
<https://ai.meta.com/resources/models-and-libraries/dinov3-downloads/>
で申請 → メールで届く署名付き URL を `wget` (ブラウザ不可) で
`UniDAC/checkpoints/` に落とす。別マシンから `scp` でも可。

> **`.venv` の管理は `setup_envs.sh` だけが行います。** 他のヘルパー
> (`start_ui.sh`、`mimicanno` CLI) は既存の `.venv` を読むだけで変更
> しません。`start_ui.sh` が `.venv` health-check failure を報告したら、
> `bash scripts/setup_envs.sh --core` を再実行して full extras
> (`dev`, `vlm`, `sam3`, `server`) を入れ直してください。

レビュー UI を起動:

```bash
bash scripts/start_ui.sh                                  # :8000 / :5173
API_PORT=8001 VITE_PORT=5174 bash scripts/start_ui.sh
bash scripts/start_ui.sh --runs-root /path/to/runs
```

## データ取得

clone 直後はデータが手元にありません。`setup_envs.sh` の `weights`
step がモデル重みと一緒に public dataset を DL します:

| HF dataset | 配置先 | 内容 |
|---|---|---|
| `Gayagaya/SO101_dataset` | `data/SO101/` | LeRobot v3 SO101 (33 ep / 4960 frames) |
| `Gayagaya/fisheye_videos_processed` | `data/video/` | 顔ぼかし済み GoPro Max Lens Mod fisheye 動画（現状 demo 1 本のみ、追加予定） |
| `takaki99/GEM4_open_the_jar` | `data/GEM4_open_the_jar/` | LeRobot v3、約 208 ep |
| `takaki99/GEM4_pick_up_bottle` | `data/GEM4_pick_up_bottle/` | LeRobot v3、約 304 ep |
| `takaki99/GEM4_replace_the_cookie` | `data/GEM4_replace_the_cookie/` | LeRobot v3、約 216 ep |

手動で DL:

```bash
hf download Gayagaya/SO101_dataset                --local-dir data/SO101                  --repo-type dataset
hf download Gayagaya/fisheye_videos_processed     --local-dir data/video                  --repo-type dataset
hf download takaki99/GEM4_open_the_jar            --local-dir data/GEM4_open_the_jar      --repo-type dataset
hf download takaki99/GEM4_pick_up_bottle          --local-dir data/GEM4_pick_up_bottle    --repo-type dataset
hf download takaki99/GEM4_replace_the_cookie      --local-dir data/GEM4_replace_the_cookie --repo-type dataset
```

## デモ

`bash scripts/setup_envs.sh` 完走後の動作確認用エンドツーエンドフロー。
各コマンドは冪等で再実行しても no-op。

```bash
# 1. 同梱の魚眼動画で hand pipeline (Phase A → C、~5 分 / 1 GPU)
bash scripts/run_all_pipeline.sh demo_hand_video_2.7k

# 2. SO101 episode 1 本をアノテーション (Phase 1–4、GPU で ~1 分)
mimicanno annotate \
  --video        data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --parquet      data/SO101/data/chunk-000/episode_000000.parquet \
  --task         "Put the tape into the bottle" \
  --robot        generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it" \
  --sam3-checkpoint sam3/checkpoints/sam3.pt \
  --runs-root    ./runs

# 3. GEM4 episode を Gemma 4 QLoRA アダプタで一括アノテーション
#    (unsloth_env 必須、下記は 1 ep 切り出しで ~2 分)
GPU=0 START=0 END=0 bash scripts/run_4B_gem4.sh open_the_jar

# 4. レビュー UI を起動して結果を確認
bash scripts/start_ui.sh
# ブラウザで http://localhost:5173/
```

4 つとも成功すればインストール健全。詳細フラグや他データセット用途は
次節を参照。

## クイックスタート

### 1. エピソード 1 本にアノテーション

`setup_envs.sh --weights` で自動 DL される `data/SO101/` の episode を使った具体例:

```bash
mimicanno annotate \
  --video        data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --parquet      data/SO101/data/chunk-000/episode_000000.parquet \
  --task         "Put the tape into the bottle" \
  --robot        generic \
  --robot-config tests/exports/fixtures/so101_robot_config.yaml \
  --target-phase 4 \
  --vlm-model    "google/gemma-4-E2B-it" \
  --sam3-checkpoint sam3/checkpoints/sam3.pt \
  --runs-root    ./runs
```

`runs/<canonical_name>/{manifest,annotation,boundaries,signals,tracks}.json` を生成します。同じ config + 同じ入力での再実行は no-op (冪等)。

config を変えて (smoother/boundary YAML、adapter など) 再実行すると、
既存ディレクトリを上書きせず **新しい** `episode_NNNNNN__<short-hash>/`
が併存します。viewer はこの場合「N runs exist for this episode」の
chooser banner を表示し、URL の `&hash=...` で現在表示中の run を pin
します。古い run が要らなければ `runs/<set>/` 下の該当ディレクトリを
削除してください。

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

### 3. GEM4 データセットの一括アノテーション

ここでの "GEM4" は Gemma-4-VLA 学習用に収集されたデータセット族
(`open_the_jar` / `pick_up_bottle` / `replace_the_cookie`)。下記
wrapper はいずれも VLM (Gemma 4 系) をプロセス内 **1 回だけ**
ロードして全 episode で使い回すので、エピソード単位 CLI と比べて
モデルロード時間 (~2 分/ep) を ep 回数分節約できる。

4B / 26B Unsloth QLoRA アダプタは `setup_envs.sh --weights` が
<https://huggingface.co/Gayagaya/gem4_4B_adapter> と
<https://huggingface.co/Gayagaya/gem4_26B_adapter> から自動 DL。
手動取得:

```bash
hf download Gayagaya/gem4_4B_adapter  --local-dir models/gem4_4B_adapter
hf download Gayagaya/gem4_26B_adapter --local-dir models/gem4_26B_adapter
```

**26B QLoRA アダプタ** (`unsloth_env` conda 環境必須):

```bash
# GPU 1 枚で 1 タスクの全 episode を流す
GPU=0 bash scripts/run_26B_gem4.sh open_the_jar

# 2 GPU で episode 範囲を分割して並列実行
GPU=0 START=0   END=151 bash scripts/run_26B_gem4.sh pick_up_bottle &
GPU=1 START=152 END=303 bash scripts/run_26B_gem4.sh pick_up_bottle
```

出力先は `runs/gem4_<task>_26B/`。

**4B QLoRA アダプタ** (同じ `unsloth_env`、26B より軽量で高速):

```bash
GPU=0 bash scripts/run_4B_gem4.sh open_the_jar
GPU=0 START=0 END=103 bash scripts/run_4B_gem4.sh replace_the_cookie &
ADAPTER=/other/path GPU=0 bash scripts/run_4B_gem4.sh open_the_jar
```

出力先は `runs/gem4_<task>_4B/`。両 wrapper とも実体は
`scripts/batch_annotate.py` の薄いラッパ。SO101 等 wrapper が無い
データセットは直叩き:

```bash
python scripts/batch_annotate.py --dataset so101 --gpu 0
```

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
python scripts/precompute_depth.py --video data/video/<NAME>.MP4

# Phase B — 手姿勢推定
python scripts/run_hand_estimation.py --video data/video/<NAME>.MP4

# 全 phase (A + B + depth-viz C) を data/video/ 内の魚眼動画全部について実行
bash scripts/run_all_pipeline.sh

# 動画名指定（.MP4 / .mp4 どっちでも OK）
bash scripts/run_all_pipeline.sh demo_hand_video_2.7k

# GPU 単一 (デフォルト 0 0) / 2 GPU 並列
bash scripts/run_all_pipeline.sh --gpus 0 1

# 入出力 root を変える（CLI または VIDEO_DIR / DEPTH_DIR / HANDS_DIR env）
bash scripts/run_all_pipeline.sh --video-dir data/demo_hand_video

# Phase 個別スキップ
bash scripts/run_all_pipeline.sh --skip-phase-a --skip-phase-b   # depth-viz だけ
```

出力は `outputs/depth/<NAME>/` と `outputs/hands/<NAME>/` 配下。スキーマ・フィールド定義・バッチオプションは [`docs/hand-pipeline.md`](docs/hand-pipeline.md) を参照。

### Third-party data collection (MediaPipe)

このパイプラインは手検出に **MediaPipe Solutions** を使用しています。MediaPipe は動画フレーム自体は **完全に on-device** で処理し、メディアを Google に送信することはありません。ただし MediaPipe は **使用状況とパフォーマンスのメトリクス** を Google に送信します (SDK 利用状況、推論回数、ハードウェア性能、アプリケーション識別子、ホスト OS バージョン)。詳細は Google の [MediaPipe APIs Terms of Service](https://ai.google.dev/edge/mediapipe/legal/tos) を参照。

**本ソフトウェアを再配布する場合**、適用される法令 (GDPR、CCPA 等) で求められる範囲で、エンドユーザーへの告知と同意取得は再配布者の責任となります。

### Offline / air-gapped deployment

ネット接続のない環境で動かす場合、接続可能なマシンで先に MediaPipe モデルを取得しておきます。`setup_envs.sh` の `weights` step に含まれてる:

```bash
bash scripts/setup_envs.sh --weights
# 保存先を指定したい時:
MIMICANNO_HAND_LANDMARKER_PATH=/path/to/deployment/models/hand_landmarker.task \
    bash scripts/setup_envs.sh --weights
```

本番環境で `MIMICANNO_HAND_LANDMARKER_PATH=...` を設定すると、runner の `_resolve_model_path()` は以下の順で asset を解決します:

1. `MIMICANNO_HAND_LANDMARKER_PATH` — 明示的な override。ファイルが無ければ即 fail。
2. `~/.cache/mimicanno/hand_landmarker.task` — 存在しサイズ検証を通れば、ネットワークアクセス無しで使用。
3. pin された URL から step 2 の cache に download。

URL は `/1/` リビジョンに pin されており再現可能なバイト列が得られます。step 1 は step 2/3 を短絡するので、air-gapped 環境では step 1 のみが実行されます。

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
