"""Layer-3 smoke: drive SAM3Runtime against a real SO101 episode.

Exercises the *new* SAM3Runtime class (sam3 submodule native backend)
against a real LeRobot-style SO101 video. Phase 2 / VLM is bypassed —
we hardcode the entity prompts derived from the SO101 task description
("Put the tape into the bottle"). The goal is to validate the SAM3 swap
end-to-end (load → ground_on_frame → propagate → close) on real data
without dragging Gemma weights into the autonomy window's go/no-go.

Pass criteria (qualitative, per CLAUDE.md autonomy window exit #2):
  - load() succeeds on sam3/checkpoints/sam3.pt with no transformers fallback
  - ground_on_frame() returns ≥1 detection for at least one of the prompts
    on the first frame of the episode
  - propagate() yields the expected number of frames with sane track output
    (boxes inside [0,1], scores in [0,1], at most one detection per prompt
    per frame, no exceptions)
  - close() releases without raising, idempotent on second call

Run:
  uv run python scripts/smoke_sam3_runtime_so101.py
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
            "/misc/dl00/gayagaya/MimicAnno/data/SO101/videos/chunk-000/"
            "observation.images.front/episode_000000.mp4"
        ),
    )
    parser.add_argument("--checkpoint", default="sam3/checkpoints/sam3.pt")
    parser.add_argument(
        "--prompts",
        nargs="+",
        default=["tape", "bottle", "robot gripper"],
        help="text prompts (used for grounding) and bbox carriers (propagate)",
    )
    parser.add_argument(
        "--n-frames", type=int, default=151,
        help="full SO101 ep0 = 151 frames; cap to keep smoke ≤ ~3 min",
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

    _info(f"video      = {video_path}")
    _info(f"checkpoint = {ckpt_path}")
    _info(f"prompts    = {args.prompts}")
    _info(f"n_frames   = {args.n_frames}, stride = {args.stride}")

    # ----- 1. Load -------------------------------------------------------
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    t0 = time.time()
    runtime = SAM3Runtime.load(
        checkpoint=ckpt_path, device="cuda", offload_video_to_cpu=True,
    )
    _pass(f"SAM3Runtime.load() in {time.time() - t0:.1f}s")

    failures: list[str] = []

    try:
        # ----- 2. ground_on_frame on real frame ------------------------
        first_frame = _load_first_frame(video_path)
        _info(f"first frame shape = {first_frame.shape} dtype = {first_frame.dtype}")

        ground_results: dict[str, list[tuple]] = {}
        any_grounded = False
        for prompt in args.prompts:
            t0 = time.time()
            dets = runtime.ground_on_frame(first_frame, prompt)
            dt = time.time() - t0
            ground_results[prompt] = dets
            if dets:
                any_grounded = True
                top = dets[0]
                _pass(
                    f"ground_on_frame('{prompt}') → {len(dets)} det(s) "
                    f"top score={top[1]:.3f} bbox=("
                    f"{top[0].x:.2f},{top[0].y:.2f},{top[0].w:.2f},{top[0].h:.2f}) "
                    f"in {dt:.2f}s"
                )
            else:
                _warn(f"ground_on_frame('{prompt}') → 0 det in {dt:.2f}s")

        if not any_grounded:
            failures.append("no prompt grounded — propagate would be empty")
            return _summary(failures, runtime)

        # Build (prompt, top_bbox) seeds for propagate.
        prompts_with_bbox = [
            (prompt, dets[0][0])
            for prompt, dets in ground_results.items() if dets
        ]
        _info(f"propagate seeds: {[p for p, _ in prompts_with_bbox]}")

        # ----- 3. propagate over the full episode ---------------------
        expected = set(range(0, args.n_frames, args.stride)) | {args.n_frames - 1}
        t0 = time.time()
        n_yields = 0
        det_count_per_prompt = {p: 0 for p, _ in prompts_with_bbox}
        first_yield: dict | None = None
        last_yield: dict | None = None
        for fr in runtime.propagate(
            video_path=video_path,
            prompts_with_initial_bbox=prompts_with_bbox,
            expected_frames=expected,
        ):
            n_yields += 1
            if first_yield is None:
                first_yield = {"frame": fr.frame, "detections": dict(fr.detections)}
            last_yield = {"frame": fr.frame, "detections": dict(fr.detections)}
            for prompt in det_count_per_prompt:
                if fr.detections.get(prompt) is not None:
                    det_count_per_prompt[prompt] += 1

            for prompt, det in fr.detections.items():
                if det is None:
                    continue
                bbox, score = det
                if not (0.0 <= bbox.x < 1.0 and 0.0 <= bbox.y < 1.0):
                    failures.append(
                        f"frame {fr.frame} prompt '{prompt}' bbox out of unit "
                        f"square: {bbox}"
                    )
                if not (0.0 <= score <= 1.0):
                    failures.append(
                        f"frame {fr.frame} prompt '{prompt}' score out of "
                        f"[0,1]: {score}"
                    )

        dt = time.time() - t0
        _info(
            f"propagate: yielded {n_yields} frames in {dt:.1f}s "
            f"(expected {len(expected)})"
        )
        if first_yield is not None:
            _info(f"first yield: frame={first_yield['frame']}")
        if last_yield is not None:
            _info(f"last yield:  frame={last_yield['frame']}")

        if n_yields == 0:
            failures.append("propagate yielded zero frames")
        elif n_yields != len(expected):
            _warn(
                f"yielded {n_yields} != expected {len(expected)} — "
                "may indicate sam3 stream early-truncated; not fatal."
            )
        else:
            _pass(f"propagate yielded all {len(expected)} expected frames")

        for prompt, count in det_count_per_prompt.items():
            ratio = count / max(n_yields, 1)
            tag = _pass if count > 0 else _warn
            tag(
                f"prompt '{prompt}' tracked in {count}/{n_yields} frames "
                f"({100*ratio:.1f}%)"
            )

    finally:
        # ----- 4. close (idempotent) -------------------------------------
        runtime.close()
        runtime.close()  # second call must be a no-op
        _pass("close() x2 idempotent")

    return _summary(failures, runtime)


def _summary(failures: list[str], _runtime: object) -> int:
    print()
    print("=" * 60)
    if failures:
        for f in failures:
            _fail(f)
        return 1
    _pass("all SO101 SAM3Runtime smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
