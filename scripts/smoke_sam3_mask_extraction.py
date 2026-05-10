"""Task 5 smoke gate (vlm-mask-overlay plan): SAM3 mask extraction on SO101 ep0.

Drives the mask-collecting path of ``Propagator.run`` against real SAM3
weights and a real SO101 video. Plan §Task 5 says **if this fails, halt
and report**, because every later overlay task assumes
``out_binary_masks`` shape/dtype work the way we believe.

Pass criteria (qualitative, per plan):
  - ``Propagator.run`` returns a populated ``MaskCache`` whose
    ``shape == (image_size_px, image_size_px)``.
  - At least one frame of the cache has ``mask.sum() > 0`` for the
    "tape" prompt — i.e. SAM3 actually emitted a non-empty mask we
    successfully downsampled and stored.
  - RLE compression ratio (raw bool bytes ÷ encoded bytes) is logged
    for capacity planning; not a pass/fail criterion.

Run:
  uv run python scripts/smoke_sam3_mask_extraction.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _info(msg: str) -> None:
    print(f"{CYAN}[INFO]{RESET} {msg}")


def _pass(msg: str) -> None:
    print(f"{GREEN}[PASS]{RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def _load_first_frame(video_path: Path) -> np.ndarray:
    import cv2  # type: ignore

    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read frame 0 of {video_path}")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video",
        default=(
            "/home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/"
            "observation.images.front/episode_000000.mp4"
        ),
    )
    parser.add_argument(
        "--checkpoint",
        default="/home/gayagaya/MimicAnno/sam3/checkpoints/sam3.pt",
    )
    parser.add_argument("--prompt", default="tape")
    parser.add_argument(
        "--image-size-px", type=int, default=256,
        help="MaskCache target shape; matches default VLMConfig.image_size_px",
    )
    parser.add_argument(
        "--n-frames", type=int, default=151,
        help="full SO101 ep0 = 151 frames",
    )
    parser.add_argument("--stride", type=int, default=5)
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    ckpt_path = Path(args.checkpoint).resolve()
    if not video_path.is_file():
        _fail(f"video not found: {video_path}")
        return 2
    if not ckpt_path.is_file():
        _fail(f"checkpoint not found: {ckpt_path}")
        return 2

    _info(f"video         = {video_path}")
    _info(f"checkpoint    = {ckpt_path}")
    _info(f"prompt        = {args.prompt!r}")
    _info(f"image_size_px = {args.image_size_px}")
    _info(f"n_frames      = {args.n_frames}, stride = {args.stride}")

    from mimicanno.config import TrackingConfig
    from mimicanno.object_tracker.planner import EntityPlan
    from mimicanno.object_tracker.propagator import (
        Propagator,
        TrackingPlan,
        ground_initial_detections,
    )
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    # 1. Load runtime
    t0 = time.time()
    runtime = SAM3Runtime.load(
        checkpoint=ckpt_path, device="cuda", offload_video_to_cpu=True,
    )
    _pass(f"SAM3Runtime.load() in {time.time() - t0:.1f}s")

    failures: list[str] = []
    try:
        first_frame = _load_first_frame(video_path)

        # 2. Ground the prompt on frame 0 to seed propagation
        entities = EntityPlan(
            object_prompts=[args.prompt],
            target_prompts=[],
            tool_prompts=[],
        )
        plan = ground_initial_detections(
            runtime=runtime, entities=entities, initial_frame=first_frame,
        )
        if not plan.initial_detections:
            failures.append(f"prompt {args.prompt!r} did not ground on frame 0")
            return _summary(failures, runtime)
        _pass(f"grounded {args.prompt!r}: {plan.initial_detections}")

        # 3. Propagate WITH mask collection
        config = TrackingConfig(track_stride_frames=args.stride)
        t0 = time.time()
        tracks, mask_cache = Propagator().run(
            runtime=runtime,
            plan=plan,
            video_path=video_path,
            fps=15.0,
            n_frames=args.n_frames,
            stride=args.stride,
            config=config,
            mask_image_size_px=args.image_size_px,
        )
        dt = time.time() - t0
        _pass(
            f"Propagator.run() with masks in {dt:.1f}s "
            f"({len(tracks)} tracks, {len(mask_cache.by_frame) if mask_cache else 0} frames cached)"
        )

        # 4. Validate cache shape
        if mask_cache is None:
            failures.append("mask_cache is None despite mask_image_size_px set")
            return _summary(failures, runtime)
        expected_shape = (args.image_size_px, args.image_size_px)
        if mask_cache.shape != expected_shape:
            failures.append(
                f"mask_cache.shape {mask_cache.shape} != {expected_shape}"
            )
        else:
            _pass(f"mask_cache.shape == {expected_shape}")

        # 5. Coverage: at least one frame's mask has sum > 0
        nonempty_frames: list[int] = []
        empty_frames: list[int] = []
        per_frame_pixels: list[int] = []
        rle_bytes_total = 0
        for fr_idx in sorted(mask_cache.by_frame):
            decoded = mask_cache.get(fr_idx, args.prompt)
            if decoded is None:
                empty_frames.append(fr_idx)
                continue
            if decoded.shape != expected_shape:
                failures.append(
                    f"frame {fr_idx}: decoded shape {decoded.shape} "
                    f"!= {expected_shape}"
                )
                continue
            n_pix = int(decoded.sum())
            per_frame_pixels.append(n_pix)
            if n_pix > 0:
                nonempty_frames.append(fr_idx)
            blob = mask_cache.by_frame[fr_idx][args.prompt]
            if blob is not None:
                rle_bytes_total += len(blob)

        if not nonempty_frames:
            failures.append(
                f"no frame has mask.sum() > 0 for prompt {args.prompt!r} — "
                "smoke gate FAILED, halt per plan"
            )
        else:
            cov_pct = 100.0 * len(nonempty_frames) / max(
                len(nonempty_frames) + len(empty_frames), 1,
            )
            _pass(
                f"non-empty masks: {len(nonempty_frames)} frames "
                f"(coverage {cov_pct:.1f}%); first={nonempty_frames[0]}, "
                f"last={nonempty_frames[-1]}"
            )

        # 6. RLE compression ratio (info)
        if per_frame_pixels:
            raw_bytes = (
                args.image_size_px * args.image_size_px * len(per_frame_pixels)
            )
            ratio = raw_bytes / max(rle_bytes_total, 1)
            mean_pix = float(np.mean(per_frame_pixels))
            _info(
                f"raw bool bytes={raw_bytes}, RLE bytes={rle_bytes_total}, "
                f"compression ratio={ratio:.1f}x, mean pixels/mask={mean_pix:.0f}"
            )

    except Exception as exc:
        failures.append(f"unhandled exception: {exc!r}")
        raise
    finally:
        runtime.close()
        runtime.close()  # idempotent

    return _summary(failures, runtime)


def _summary(failures: list[str], runtime: object) -> int:
    del runtime  # no-op, caller already closed
    if failures:
        for f in failures:
            _fail(f)
        _fail(f"smoke FAILED ({len(failures)} issue(s))")
        return 1
    _pass("smoke PASSED — Task 5 gate cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
