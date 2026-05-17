"""バッチ annotate ランナー (4B 版): Gemma 4 E4B-it を transformers 直接ロード。

26B 版 (batch_annotate.py) は Unsloth + QLoRA で精度寄りだが遅い。
こちらは fine-tune 前の素の E4B-it を使う高速ベースライン。

出力先: runs/<dataset>_4B/  (26B 版とは別ディレクトリ)

Usage:
  python scripts/batch_annotate_4B.py \\
      --dataset gem4_pick_up_bottle --gpu 0
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("batch_annotate_4B")

REPO = Path("/misc/dl00/gayagaya/MimicAnno")
GEMMA_4B_PATH = Path("/home/gayagaya/gemma_project/models/gemma-4-E4B-it")

DATASETS = {
    "so101": {
        "data_root": REPO / "data" / "SO101",
        "task": "Put the tape into the bottle",
        "robot_config": REPO / "tests/exports/fixtures/so101_robot_config.yaml",
        "video_subdir": "videos/chunk-000/observation.images.front",
        "runs_root": REPO / "runs/so101_4B",
        "default_end": 35,
        # SO101 gripper signals are weak — default BoundaryConfig yields
        # candidates: [] and the run collapses to one idle segment. Mirror
        # batch_annotate.py (26B path) so 4B picks up the same ZC config.
        "boundary_config": REPO / "mimicanno/configs/boundary/so101_zero_crossing.yaml",
        "smoother_config": REPO / "mimicanno/configs/smoother/so101_zc_preserve.yaml",
    },
    "gem4_pick_up_bottle": {
        "data_root": REPO / "data" / "GEM4_pick_up_bottle",
        "task": "Pick up the bottle",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_pick_up_bottle_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_pick_up_bottle_4B",
        "default_end": 303,
    },
    "gem4_replace_the_cookie": {
        "data_root": REPO / "data" / "GEM4_replace_the_cookie",
        "task": "Replace the cookie",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_replace_the_cookie_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_replace_the_cookie_4B",
        "default_end": 215,
    },
    "gem4_open_the_jar": {
        "data_root": REPO / "data" / "GEM4_open_the_jar",
        "task": "Open the jar",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_open_the_jar_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_open_the_jar_4B",
        "default_end": 207,
    },
}

SAM3_PATH = REPO / "sam3/checkpoints/sam3.pt"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True, choices=list(DATASETS.keys()))
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=None)
    p.add_argument("--gpu", type=int, required=True)
    args = p.parse_args()

    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

    ds = DATASETS[args.dataset]
    end = args.end if args.end is not None else ds["default_end"]

    # --- pre-flight: 4B はローカルパスを @<fake_sha> で渡す (LoRA ではない通常モデル) ---
    from mimicanno.preflight import resolve_vlm_model, resolve_sam3_checkpoint
    fake_sha = hashlib.sha1(b"gemma-4-E4B-it-local").hexdigest()
    vlm_arg = f"{GEMMA_4B_PATH}@{fake_sha}"
    pre = resolve_vlm_model(vlm_arg, offline=True)
    sam3_sha = resolve_sam3_checkpoint(SAM3_PATH)
    log.info(f"preflight ok: is_lora={pre.is_lora_adapter} (should be False)")

    # --- VLM を1回だけロード ---
    log.info("loading Gemma 4 E4B-it (one-time)...")
    t0 = time.time()
    from mimicanno.config import (
        VLMConfig, AnnotationConfig, BoundaryConfig, MaskOverlayConfig,
        TrackingConfig, build_model_config,
    )
    from mimicanno.vlm_labeler import LocalGemmaVLMLabeler

    vlm_cfg = VLMConfig(
        model_id=pre.model_id,
        resolved_checkpoint=pre.resolved_checkpoint,
        fixture_path=pre.fixture_path,
        is_lora_adapter=False,
        device="cuda",
        keyframes_per_segment=4,
        max_retries=3,
        mask_overlay=MaskOverlayConfig(enabled=True, alpha=0.4),
    )
    vlm = LocalGemmaVLMLabeler(vlm_cfg)
    log.info(f"VLM loaded in {time.time()-t0:.1f}s")

    # SAM3 も1回だけロードして全 ep で共有する。
    log.info("loading SAM3 (one-time)...")
    t_sam3 = time.time()
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime
    sam3_rt = SAM3Runtime.load(checkpoint=str(SAM3_PATH))
    log.info(f"SAM3 loaded in {time.time()-t_sam3:.1f}s")

    # --- Phase 4 共通設定 ---
    # Per-dataset boundary/smoother YAML を `mimicanno.cli annotate` 経路と
    # 同じローダで読み込む (batch_annotate.py L143-173 と同じパターン)。
    # YAML が指定されていないデータセット (現状 gem4_* 各種) は従来通り
    # デフォルトに fallback。
    from mimicanno.config import (
        load_boundary_config_yaml,
        load_smoother_config_yaml,
    )
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.smoother import SmootherConfig

    boundary_cfg_path: Path | None = ds.get("boundary_config")  # type: ignore[assignment]
    if boundary_cfg_path is not None:
        log.info(f"loading BoundaryConfig YAML: {boundary_cfg_path}")
        boundary_cfg = load_boundary_config_yaml(boundary_cfg_path)
    else:
        boundary_cfg = BoundaryConfig.with_defaults()

    smoother_cfg_path: Path | None = ds.get("smoother_config")  # type: ignore[assignment]
    if smoother_cfg_path is not None:
        log.info(f"loading SmootherConfig YAML: {smoother_cfg_path}")
        label_set = load_label_set(Path(default_labels_path("manipulation")))
        allowed_label_ids = [lbl.id for lbl in label_set.labels]
        smoother_cfg = load_smoother_config_yaml(
            smoother_cfg_path, allowed_labels=allowed_label_ids,
        )
    else:
        smoother_cfg = SmootherConfig()
    tracking_cfg = TrackingConfig(
        sam3_checkpoint=str(SAM3_PATH),
        sam3_offload=True,
        track_stride_frames=None,
    )

    # --- エピソードループ ---
    from mimicanno.pipeline import AnnotateRequest, annotate_episode_phase4

    data_root = ds["data_root"]
    video_dir = data_root / ds["video_subdir"]
    parquet_dir = data_root / "data/chunk-000"
    # BATCH_RUNS_ROOT で出力先を上書き可能 (smoke 用)
    runs_root = (
        Path(os.environ["BATCH_RUNS_ROOT"])
        if os.environ.get("BATCH_RUNS_ROOT")
        else ds["runs_root"]
    )
    runs_root.mkdir(parents=True, exist_ok=True)

    vlm_dump_root = runs_root / "_vlm_dumps"
    vlm_dump_root.mkdir(parents=True, exist_ok=True)

    n_ok, n_fail, n_skip = 0, 0, 0
    # Determine total episode count for progress markers
    episode_range = range(args.start, end + 1)
    total_eps = len(episode_range)
    try:
        for i in episode_range:
            ep = f"episode_{i:06d}"
            video = video_dir / f"{ep}.mp4"
            parquet = parquet_dir / f"{ep}.parquet"
            if not video.exists() or not parquet.exists():
                log.info(f"{ep}: SKIP (missing)")
                n_skip += 1
                continue

            # エピソードごとにダンプ先を切り替える
            os.environ["MIMICANNO_VLM_DUMP_DIR"] = str(vlm_dump_root / ep)

            t_ep = time.time()
            cfg = AnnotationConfig(
                boundary=boundary_cfg,
                target_phase=4,
                model_config=build_model_config(
                    target_phase=4, vlm=vlm_cfg,
                    tracking=tracking_cfg, sam3_checkpoint_sha256=sam3_sha,
                ),
                vlm=vlm_cfg,
                tracking=tracking_cfg,
                smoother=smoother_cfg,
            )
            req = AnnotateRequest(
                video=video,
                parquet=parquet,
                task=ds["task"],
                robot_adapter_name="generic",
                robot_adapter_config_path=ds["robot_config"],
                labels_path=None,
                runs_root=runs_root,
                link_video=False,
                force=True,
                config=cfg,
                preloaded_vlm=vlm,
                preloaded_sam3_runtime=sam3_rt,
            )
            try:
                annotate_episode_phase4(req)
                elapsed = time.time() - t_ep
                log.info(f"{ep}: OK ({elapsed:.1f}s)")
                n_ok += 1
                # U-A1 progress marker — parsed by the job runner
                print(
                    f"[mimicanno-job-progress] ep={i} finished={n_ok}/{total_eps}",
                    flush=True,
                )
            except Exception as e:
                log.exception(f"{ep}: FAIL — {e!r}")
                n_fail += 1
    finally:
        log.info("closing shared SAM3 runtime...")
        sam3_rt.close()

    log.info(f"summary: ok={n_ok}, fail={n_fail}, skip={n_skip}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
