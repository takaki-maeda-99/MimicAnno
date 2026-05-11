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
- **読み取り専用 React/Vite ビューア** — タイムライン + 波形 + 境界マーカー (`frontend/`)。
- **プラガブルなロボットアダプタ** — SO100 / Koch / Aloha 同梱、SO101 や任意の LeRobot v3 レイアウトは YAML で設定可能。

## インストール

Python 3.11+ と [uv](https://github.com/astral-sh/uv) が必要。

```bash
git clone git@github.com:takaki-maeda-99/MimicAnno.git
cd MimicAnno
uv sync                     # コアのみ
uv sync --extra dev         # + pytest / mypy / ruff (開発時推奨)
uv sync --extra vlm         # + transformers   (Phase 2 — Gemma)
uv sync --extra sam3        # + transformers + torch + torchvision (Phase 3 — SAM3)
```

CUDA driver が 13.0 未満の GPU 環境 (例: Ubuntu 24.04 + driver 12.8) は、`uv sync` 後にバージョンの合う torch wheel を上書きインストール:

```bash
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install transformers Pillow
```

CUDA が認識されているか確認:

```bash
uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
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

CPU のみ・driver 不一致の環境では:

```bash
--vlm-device cpu --vlm-timeout-sec 600
```

(8 セグメントのエピソードで GPU 1 分 ≒ CPU 1 時間が目安。)

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

### 3. 出力を確認

```bash
uv run python -c "
import pyarrow.parquet as pq
sub = pq.read_table('dataset_annotated/meta/subtasks.parquet')
print('使用された phase:', sub.to_pylist())

ep0 = pq.read_table('dataset_annotated/data/chunk-000/episode_000000.parquet')
print('per-frame subtask_index 分布:')
sti = ep0.column('subtask_index').to_pylist()
for v in sorted(set(sti)):
    print(f'  index={v} ({sub.to_pylist()[v][\"subtask\"]}): {sti.count(v)} frames')
"
```

SO101 ep0 ("Put the tape into the bottle") の出力例:

```
使用された phase: [{'subtask': 'approach_object', 'subtask_index': 0, 'description': ''},
                   {'subtask': 'grasp_object',    'subtask_index': 1, 'description': ''}]
per-frame subtask_index 分布:
  index=0 (approach_object): 121 frames
  index=1 (grasp_object):     30 frames
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

## ビューア

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:5173/?run=<canonical_name>
```

run ディレクトリ用の読み取り専用タイムライン + 波形ビューア。編集機能は Phase 5B に予定 (未着手)。

## 開発

```bash
env -u PYTHONPATH uv run pytest -q                    # 全テスト (約 40 秒)
env -u PYTHONPATH uv run mypy --strict mimicanno/     # 型チェック
env -u PYTHONPATH uv run ruff check mimicanno/        # lint
```

`PYTHONPATH=` は ROS2 humble がパス汚染してくる環境向けの対策。ROS2 を入れてなければ無害。

設計の経緯と理由は `docs/superpowers/specs/` 配下、TDD タスクリスト形式の実装プランは `docs/superpowers/plans/` 配下。親設計ドキュメントは `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md`。

## ライセンス

MIT ([`LICENSE`](LICENSE) を参照)。
