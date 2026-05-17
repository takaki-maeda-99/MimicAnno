"""Precompute UniDAC metric depth for every frame of a video / image folder.

Phase A of the MimicAnno hand pipeline. Runs inside ``conda activate unidac``.
The resulting ``.npy`` files are consumed offline by
``mimicanno.hand_pipeline.pipeline.estimate_hand`` (Phase B, HaMeR env).

Output layout::

    <out>/frames/frame_NNNNNN.npy   # float32 (H_erp, W_erp) metric depth in meters
    <out>/meta.json                 # see _build_meta() for fields
    <out>/viz/erp.mp4               # colorized ERP depth (skip with --no-viz)
    <out>/viz/depth_fisheye.mp4    # back-warped to fisheye space (skip with --no-viz)

Usage (run from MimicAnno/ with PYTHONPATH set)::

    # 1) mp4 input, every frame
    python scripts/precompute_depth.py --input data/video/new/GX010085.MP4 --out data/depth/GX010085/

    # 2) with visualization videos
    python scripts/precompute_depth.py --input data/video/new/GX010085.MP4 --out data/depth/GX010085/ --save-viz

    # 3) resume a half-finished run (existing .npy files are skipped)
    python scripts/precompute_depth.py --input data/video/new/GX010085.MP4 --out data/depth/GX010085/

    # Add --overwrite to re-process, --limit N for a quick smoke run, --stride K to subsample.
    # --viz-depth-range MIN MAX sets the colormap range (default: 0.3 5.0 metres).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

import cv2
import numpy as np

# `unidac.api` must be importable. Either `pip install -e UniDAC/` or set
# PYTHONPATH to include the UniDAC repo root.
import unidac
from unidac.api import UniDACPipeline


_UNIDAC_ROOT = Path(unidac.__file__).resolve().parent.parent


@contextlib.contextmanager
def _cwd(path: Path):
    """Temporarily change cwd so UniDAC's relative checkpoint/config paths resolve."""
    prev = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev)


IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def _unidac_version() -> str:
    """Best-effort version probe: git commit of the UniDAC checkout, else 'unknown'."""
    try:
        import unidac
        repo = Path(unidac.__file__).resolve().parent.parent
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0:
            sha = out.stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True, text=True, timeout=2,
            )
            return sha + ("-dirty" if dirty.stdout.strip() else "")
    except Exception:
        pass
    return "unknown"


def _iter_video(path: Path, stride: int) -> Iterator[Tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video: {path}")
    try:
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % stride == 0:
                yield i, frame
            i += 1
    finally:
        cap.release()


def _iter_dir(path: Path, stride: int) -> Iterator[Tuple[int, np.ndarray]]:
    files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMG_EXTS)
    for i, p in enumerate(files):
        if i % stride != 0:
            continue
        frame = cv2.imread(str(p))
        if frame is None:
            print(f"  ! could not read {p}", file=sys.stderr)
            continue
        yield i, frame


def _video_metadata(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    md = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        "total_input_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    }
    cap.release()
    return md


def _build_meta(args: argparse.Namespace, pipe: UniDACPipeline,
                source_type: str, source_meta: dict) -> dict:
    return {
        "unidac_version": _unidac_version(),
        "preset": args.preset,
        "fwd_sz": list(pipe.fwd_sz),
        "cano_sz": list(pipe.cano_sz),
        "source": str(args.input),
        "source_type": source_type,
        "source_metadata": source_meta,
        "stride": args.stride,
        "ref_w_native": 5312,
        "cam_params_at_W": (
            "fl_x = fl_x_ref * W/5312, fl_y = fl_y_ref * W/5312, "
            "cx = W/2, cy = H/2, k1..k4 = 0, camera_model = OPENCV_FISHEYE"
        ),
        "preset_params": pipe.params,
        "frames_processed": 0,
        "frames_skipped_existing": 0,
        "total_elapsed_seconds": 0.0,
        "fps_avg": 0.0,
        "failures": [],
        "interrupted": False,
    }


def _save_meta(out_dir: Path, meta: dict) -> None:
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))


def _colorize_depth(depth: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """Return (H, W, 3) uint8 BGR colorized depth (PLASMA). Invalid pixels → black."""
    valid = np.isfinite(depth) & (depth > 0)
    d = np.clip((depth - vmin) / max(vmax - vmin, 1e-6), 0.0, 1.0)
    d[~valid] = 0.0
    colored = cv2.applyColorMap((d * 255).astype(np.uint8), cv2.COLORMAP_PLASMA)
    colored[~valid] = 0
    return colored


def precompute(args: argparse.Namespace) -> dict:
    """Run UniDAC over every frame and save results. Returns the final meta dict."""
    src = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        source_type = "directory"
        source_meta = {"n_files": sum(1 for p in src.iterdir()
                                       if p.suffix.lower() in IMG_EXTS)}
        iterator = _iter_dir(src, args.stride)
    elif src.is_file():
        source_type = "video"
        source_meta = _video_metadata(src)
        iterator = _iter_video(src, args.stride)
    else:
        raise FileNotFoundError(f"input not found: {src}")

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading UniDAC preset={args.preset} device={args.device or 'auto'}...", flush=True)
    with _cwd(_UNIDAC_ROOT):
        pipe = UniDACPipeline(preset=args.preset, device=args.device)
    print(f"loaded. fwd_sz={pipe.fwd_sz}", flush=True)

    meta = _build_meta(args, pipe, source_type, source_meta)

    # --save-viz: set up VideoWriters for ERP and fisheye depth videos.
    erp_writer = fisheye_writer = None
    if args.save_viz:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from mimicanno.hand_pipeline.pipeline import _back_warp_depth
        from mimicanno.hand_pipeline.h264_writer import H264VideoWriter

        viz_dir = out_dir / "viz"
        viz_dir.mkdir(parents=True, exist_ok=True)

        fps_out = float(source_meta.get("fps", 29.97)) / max(args.stride, 1)

        erp_h, erp_w = pipe.fwd_sz                                 # e.g. (512, 704)
        erp_writer = H264VideoWriter(viz_dir / "erp.mp4", erp_w, erp_h, fps_out)

        orig_h = int(source_meta.get("height", 1520))
        orig_w = int(source_meta.get("width", 2704))
        fish_w = int(orig_w * args.viz_scale)
        fish_h = int(orig_h * args.viz_scale)
        fisheye_writer = H264VideoWriter(
            viz_dir / "depth_fisheye.mp4", fish_w, fish_h, fps_out)

        vmin, vmax = args.viz_depth_range
        print(f"viz: erp.mp4={erp_w}x{erp_h}  depth_fisheye.mp4={fish_w}x{fish_h}  "
              f"depth_range={vmin:.1f}-{vmax:.1f}m -> {viz_dir}", flush=True)

    # Ctrl+C: save meta then exit cleanly.
    interrupted = {"flag": False}
    def _sigint(_sig, _frame):
        interrupted["flag"] = True
        print("\n[precompute] SIGINT received, finishing current frame then exiting...",
              file=sys.stderr, flush=True)
    signal.signal(signal.SIGINT, _sigint)

    t_start = time.time()
    n_done = 0
    n_skip = 0
    try:
        for k, (i, frame) in enumerate(iterator):
            if args.limit is not None and k >= args.limit:
                print(f"--limit {args.limit} reached; stopping.", flush=True)
                break

            out_path = frames_dir / f"frame_{i:06d}.npy"
            if out_path.exists() and not args.overwrite:
                n_skip += 1
                continue

            try:
                depth = pipe.predict_frame(frame)
                np.save(out_path, depth)

                if erp_writer is not None:
                    erp_writer.write(_colorize_depth(depth, vmin, vmax))
                if fisheye_writer is not None:
                    warped = _back_warp_depth(depth, (orig_h, orig_w),
                                              device=args.device)
                    colored = _colorize_depth(warped, vmin, vmax)
                    fisheye_writer.write(cv2.resize(colored, (fish_w, fish_h)))

                n_done += 1
                if n_done % 10 == 0 or n_done == 1:
                    el = time.time() - t_start
                    rate = n_done / el if el > 0 else 0.0
                    print(f"  [{n_done}] frame {i}: depth {depth.shape} "
                          f"min={depth.min():.3f} max={depth.max():.3f}m  "
                          f"({rate:.2f} fps)", flush=True)
            except Exception as e:
                err = {"frame": i, "err": repr(e)}
                meta["failures"].append(err)
                print(f"  ! frame {i}: {e!r}", file=sys.stderr, flush=True)

            if interrupted["flag"]:
                meta["interrupted"] = True
                break
    finally:
        if erp_writer:
            erp_writer.release()
        if fisheye_writer:
            fisheye_writer.release()
        elapsed = time.time() - t_start
        meta["frames_processed"] = n_done
        meta["frames_skipped_existing"] = n_skip
        meta["total_elapsed_seconds"] = round(elapsed, 3)
        meta["fps_avg"] = round(n_done / elapsed, 3) if elapsed > 0 else 0.0
        _save_meta(out_dir, meta)
        print(f"done. processed={n_done} skipped={n_skip} "
              f"failures={len(meta['failures'])} "
              f"elapsed={elapsed:.1f}s -> {out_dir}", flush=True)
    return meta


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Precompute UniDAC depth for every frame of a video / image dir.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--input", required=True, help="video file or directory of images")
    ap.add_argument("--out", required=True, help="output directory for .npy files")
    ap.add_argument("--stride", type=int, default=1, help="process every N-th input frame")
    ap.add_argument("--preset", default="A", choices=["A", "B"], help="UniDAC camera preset")
    ap.add_argument("--device", default=None, help='torch device, e.g. "cuda:0" or "cpu"')
    ap.add_argument("--overwrite", action="store_true", help="re-process frames whose .npy exists")
    ap.add_argument("--limit", type=int, default=None, help="stop after N frames (debug)")
    ap.add_argument("--no-viz", action="store_false", dest="save_viz",
                    help="skip writing viz/erp.mp4 and viz/fisheye.mp4")
    ap.set_defaults(save_viz=True)
    ap.add_argument("--viz-scale", type=float, default=0.5,
                    help="fisheye viz output scale relative to source resolution (default: 0.5)")
    ap.add_argument("--viz-depth-range", type=float, nargs=2, default=[0.3, 5.0],
                    metavar=("MIN", "MAX"),
                    help="depth colormap range in metres (default: 0.3 5.0)")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = _build_argparser().parse_args(argv)
    meta = precompute(args)
    return 0 if not meta["failures"] else 2


if __name__ == "__main__":
    sys.exit(main())
