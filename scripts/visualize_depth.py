"""Visualize precomputed UniDAC depth maps in fisheye space.

Loads `.npy` depth files (ERP space, 512×704), back-warps them to the original
fisheye camera grid via ``_back_warp_depth``, and writes a colorized MP4 or
individual PNG files.

Usage::

    # single frame (PNG)
    python scripts/visualize_depth.py \
        --depth data/depth/GX010085 \
        --video data/video/new/GX010085.MP4 \
        --out   data/depth/GX010085/viz_frame0.png \
        --frames 0

    # full video (side-by-side original + depth)
    python scripts/visualize_depth.py \
        --depth data/depth/GX010085 \
        --video data/video/new/GX010085.MP4 \
        --out   data/depth/GX010085/viz.mp4

    # depth only, every 5th frame, half resolution
    python scripts/visualize_depth.py \
        --depth data/depth/GX010086 \
        --out   data/depth/GX010086/viz_depth_only.mp4 \
        --stride 5 --scale 0.5 --no-side-by-side

Run inside the unidac env with PYTHONPATH set::

    PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \\
        /home/gayagaya/anaconda3/envs/unidac/bin/python scripts/visualize_depth.py ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "UniDAC"))

from mimicanno.hand_pipeline.pipeline import _back_warp_depth


IMG_H, IMG_W = 1520, 2704


def _colorize(depth_fisheye: np.ndarray, vmin: float, vmax: float,
              colormap: int = cv2.COLORMAP_PLASMA) -> np.ndarray:
    """Return (H, W, 3) uint8 BGR colorized depth. Invalid pixels → black."""
    valid = np.isfinite(depth_fisheye)
    d = np.clip((depth_fisheye - vmin) / max(vmax - vmin, 1e-6), 0.0, 1.0)
    d[~valid] = 0.0
    colored = cv2.applyColorMap((d * 255).astype(np.uint8), colormap)
    colored[~valid] = 0
    return colored


def _depth_range(depth_dir: Path, sample_n: int = 20) -> tuple[float, float]:
    """Estimate global vmin/vmax from a random sample of frames."""
    npy_files = sorted((depth_dir / "frames").glob("frame_*.npy"))
    step = max(1, len(npy_files) // sample_n)
    vals = []
    for p in npy_files[::step]:
        d = np.load(p)
        fin = d[np.isfinite(d)]
        if fin.size:
            vals.append(fin)
    if not vals:
        return 0.0, 5.0
    all_v = np.concatenate(vals)
    return float(np.percentile(all_v, 2)), float(np.percentile(all_v, 98))


def run(args: argparse.Namespace) -> None:
    depth_dir = Path(args.depth)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    device = getattr(args, "device", None)

    # npy files live in <depth>/frames/ subdir
    frames_dir = depth_dir / "frames"
    npy_files = sorted(frames_dir.glob("frame_*.npy"))
    if not npy_files:
        raise FileNotFoundError(f"no frame_*.npy files in {depth_dir}")

    # Frame selection
    if args.frames is not None:
        indices = [int(x) for x in args.frames.split(",")]
        npy_files = [f for i, f in enumerate(npy_files) if i in indices]
    elif args.stride > 1:
        npy_files = npy_files[::args.stride]

    print(f"processing {len(npy_files)} frames from {depth_dir}", flush=True)

    # Global depth range for consistent colormap
    vmin, vmax = _depth_range(depth_dir)
    print(f"depth range (2nd–98th pct): {vmin:.3f}–{vmax:.3f} m", flush=True)

    # Output size
    out_h = int(IMG_H * args.scale)
    out_w = int(IMG_W * args.scale)
    out_w_total = out_w * 2 if (not args.no_side_by_side and args.video) else out_w

    # Open source video if side-by-side; read sequentially (no random seek)
    cap = None
    cap_pos = -1  # last video frame index read
    if not args.no_side_by_side and args.video:
        cap = cv2.VideoCapture(args.video)
        if not cap.isOpened():
            print(f"warning: cannot open {args.video}, falling back to depth-only", flush=True)
            cap = None

    # Single PNG output
    is_png = out_path.suffix.lower() == ".png"
    writer = None
    if not is_png:
        fps = 29.97
        if cap:
            fps = cap.get(cv2.CAP_PROP_FPS) or fps
        fps = fps / max(args.stride, 1)
        from mimicanno.hand_pipeline.h264_writer import H264VideoWriter
        writer = H264VideoWriter(out_path, out_w_total, out_h, fps)

    try:
        for k, npy_path in enumerate(npy_files):
            frame_idx = int(npy_path.stem.split("_")[1])

            depth_erp = np.load(npy_path)
            warped = _back_warp_depth(depth_erp, (IMG_H, IMG_W), device=device)
            depth_vis = _colorize(warped, vmin, vmax)
            depth_small = cv2.resize(depth_vis, (out_w, out_h))

            if cap and not args.no_side_by_side:
                # Advance sequentially to frame_idx (skip intermediate frames)
                while cap_pos < frame_idx:
                    ok, orig = cap.read()
                    cap_pos += 1
                    if not ok:
                        break
                if ok:
                    orig_small = cv2.resize(orig, (out_w, out_h))
                    frame_out = np.hstack([orig_small, depth_small])
                else:
                    frame_out = depth_small
            else:
                frame_out = depth_small

            if is_png:
                cv2.imwrite(str(out_path), frame_out)
                print(f"saved {out_path}", flush=True)
                break
            else:
                writer.write(frame_out)

            if (k + 1) % 50 == 0 or k == 0:
                print(f"  [{k+1}/{len(npy_files)}] frame {frame_idx}", flush=True)

        if not is_png:
            print(f"saved {out_path}", flush=True)
    finally:
        if writer:
            writer.release()
        if cap:
            cap.release()


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Visualize UniDAC depth maps back-warped to fisheye space.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--depth", required=True, help="directory of frame_*.npy depth files")
    ap.add_argument("--out", required=True, help="output .mp4 or .png path")
    ap.add_argument("--video", default=None, help="source .MP4 for side-by-side mode")
    ap.add_argument("--frames", default=None,
                    help="comma-separated frame indices to render (default: all)")
    ap.add_argument("--stride", type=int, default=1, help="render every N-th frame")
    ap.add_argument("--scale", type=float, default=0.5,
                    help="output scale relative to 2704×1520 (default: 0.5)")
    ap.add_argument("--no-side-by-side", action="store_true",
                    help="output depth only (no original video column)")
    ap.add_argument("--colormap", default="plasma",
                    choices=["plasma", "viridis", "magma", "jet"],
                    help="matplotlib-style colormap name (default: plasma)")
    ap.add_argument("--device", default=None,
                    help='torch device, e.g. "cuda:0" or "cuda:1" (default: auto)')
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    colormaps = {
        "plasma": cv2.COLORMAP_PLASMA,
        "viridis": cv2.COLORMAP_VIRIDIS,
        "magma": cv2.COLORMAP_MAGMA,
        "jet": cv2.COLORMAP_JET,
    }
    args._colormap_cv2 = colormaps[args.colormap]
    run(args)


if __name__ == "__main__":
    main()
