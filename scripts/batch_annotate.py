"""バッチ annotate ランナー: 26B Unsloth QLoRA VLM を1回だけロードし、
複数エピソードに渡って再利用する。

CLI ラッパー (`mimicanno annotate`) はエピソードごとに毎回 26B モデルを
ロードし直すため、26B では1ep ~2分のロード時間がボトルネックになる
(全 GEM4 300+ ep で 10時間以上)。

このランナーは:
  1. VLM を1回だけロードする
  2. エピソードごとに annotate_episode_phase4 を直接呼ぶ
     (preloaded_vlm 経由で同じ instance を共有)
  3. SAM3 は各 ep ごとに load/close する (同一プロセス内なので
     CUDA キャッシュは温まったまま)

Usage:
  python scripts/batch_annotate.py \\
      --dataset gem4_pick_up_bottle \\
      --start 0 --end 303 \\
      --gpu 0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("batch_annotate")

REPO = Path("/misc/dl00/gayagaya/MimicAnno")


DATASETS = {
    "so101": {
        "data_root": REPO / "data" / "SO101",
        "task": "Put the tape into the bottle",
        "robot_config": REPO / "tests/exports/fixtures/so101_robot_config.yaml",
        "video_subdir": "videos/chunk-000/observation.images.front",
        "runs_root": REPO / "runs/so101_26B",
        "default_end": 35,
    },
    "gem4_pick_up_bottle": {
        "data_root": REPO / "data" / "GEM4_pick_up_bottle",
        "task": "Pick up the bottle",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_pick_up_bottle_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_pick_up_bottle_26B",
        "default_end": 303,
    },
    "gem4_replace_the_cookie": {
        "data_root": REPO / "data" / "GEM4_replace_the_cookie",
        "task": "Replace the cookie",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_replace_the_cookie_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_replace_the_cookie_26B",
        "default_end": 215,
    },
    "gem4_open_the_jar": {
        "data_root": REPO / "data" / "GEM4_open_the_jar",
        "task": "Open the jar",
        "robot_config": REPO / "mimicanno/configs/robot/gem4_open_the_jar_robot_config.yaml",
        "video_subdir": "videos/observation.images.front/chunk-000",
        "runs_root": REPO / "runs/gem4_open_the_jar_26B",
        "default_end": 207,
    },
}

ADAPTER_PATH = REPO / "models/gem4_26B_adapter"
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

    # `import unsloth` は CUDA_VISIBLE_DEVICES 設定後に行う必要がある
    # (import 時点でCUDAコンテキストを掴むため)
    import unsloth  # noqa: F401

    ds = DATASETS[args.dataset]
    end = args.end if args.end is not None else ds["default_end"]

    # --- pre-flight (sha 解決のみ; モデルロードはここでは不要) ---
    from mimicanno.preflight import resolve_vlm_model, resolve_sam3_checkpoint
    fake_sha = hashlib.sha1(b"gem4-26B-adapter").hexdigest()
    vlm_arg = f"{ADAPTER_PATH}@{fake_sha}"
    pre = resolve_vlm_model(vlm_arg, offline=True)
    sam3_sha = resolve_sam3_checkpoint(SAM3_PATH)
    log.info(f"preflight ok: is_lora={pre.is_lora_adapter}, sam3_sha={sam3_sha[:20]}...")

    # --- VLM を1回だけロード ---
    log.info("loading 26B Unsloth VLM (one-time)...")
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
        is_lora_adapter=pre.is_lora_adapter,
        device="cuda",
        keyframes_per_segment=4,
        max_retries=3,
        mask_overlay=MaskOverlayConfig(enabled=True, alpha=0.4),
    )
    vlm = LocalGemmaVLMLabeler(vlm_cfg)
    log.info(f"VLM loaded in {time.time()-t0:.1f}s")

    # SAM3 も1回だけロードして全 ep で共有する。
    # 毎 ep load/close すると PyTorch CUDA allocator が断片化して
    # GPU メモリが累積するのを防ぐ目的。
    log.info("loading SAM3 (one-time)...")
    t_sam3 = time.time()
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime
    sam3_rt = SAM3Runtime.load(checkpoint=str(SAM3_PATH))
    log.info(f"SAM3 loaded in {time.time()-t_sam3:.1f}s")

    # --- Phase 4 共通設定 ---
    from mimicanno.smoother import SmootherConfig
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
    try:
        for i in range(args.start, end + 1):
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
                boundary=BoundaryConfig.with_defaults(),
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
