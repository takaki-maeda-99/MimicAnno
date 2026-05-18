"""Phase B: MediaPipe hand-landmark estimation with UniDAC metric depth.

Reads precomputed UniDAC depth (.npy) from Phase A and runs the MediaPipe
HandLandmarker backend frame-by-frame. Wrist depth is sampled directly from
UniDAC (euclid distance) and back-projected through the fisheye camera model
to produce metric cam_t.

Two-pass architecture:
  Pass 1: per-frame MediaPipe + depth sampling → frames/frame_NNNNNN.pkl
  Pass 2: temporal gap-filling (≤ max_interp_gap frames) for each hand side
  Viz:    overlay.mp4 generated after Pass 2

Output layout::

    <out>/frames/frame_NNNNNN.pkl   # list[HandEstimate] ([] if no hands)
    <out>/meta.json
    <out>/viz/overlay.mp4           # 2D keypoints on original frame (skip with --no-viz)

Usage::

    uv run python scripts/run_hand_estimation.py \\
        --video data/video/new/GX010085.MP4 \\
        --depth data/depth/GX010085 \\
        --out   data/hands/GX010085
"""
from __future__ import annotations

import argparse
import json
import pickle
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "UniDAC"))

from mimicanno.hand_pipeline.pipeline import (
    HandEstimate,
    _apply_metric_depth,
    _run_mediapipe,
)


# ---------------------------------------------------------------------------
# Helpers

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


def _video_metadata(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    md = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        "total_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    }
    cap.release()
    return md


def _load_pkl(path: Path) -> Optional[List[HandEstimate]]:
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_pkl_atomic(path: Path, data: List[HandEstimate]) -> None:
    tmp = path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(data, f, protocol=4)
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Pass 2: temporal depth interpolation

def _slerp_rotation(R0: np.ndarray, R1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation between two 3x3 rotation matrices.

    Uses scipy.spatial.transform.Rotation.slerp when available; falls back to a
    linear blend + re-orthonormalisation (via SVD) if scipy.slerp is unusable.
    """
    try:
        from scipy.spatial.transform import Rotation, Slerp
        key = Rotation.from_matrix(np.stack([R0.astype(float), R1.astype(float)]))
        out = Slerp([0.0, 1.0], key)([t]).as_matrix()[0]
        return out.astype(np.float32)
    except Exception:
        blended = (1.0 - t) * R0.astype(float) + t * R1.astype(float)
        u, _, vt = np.linalg.svd(blended)
        R = u @ vt
        if np.linalg.det(R) < 0:
            u[:, -1] *= -1
            R = u @ vt
        return R.astype(np.float32)


def _interpolate_side(
    frame_indices: List[int],
    estimates: Dict[int, Optional[HandEstimate]],
    max_gap: int,
) -> None:
    """Fill short depth gaps for one hand side (left or right) in-place.

    For each contiguous run of frames where the hand was detected but
    ``wrist_depth_m`` is ``None`` (UniDAC missed at the wrist pixel), linearly
    interpolate ``wrist_depth_m``, ``cam_t``, ``joints_3d``, and
    ``pinch_distance_m`` between the bracketing frames, and SLERP the
    ``global_orient`` rotation. Gaps longer than ``max_gap`` or at the video
    boundary are skipped.
    """
    n = len(frame_indices)
    gap_start = 0
    while gap_start < n:
        fi = frame_indices[gap_start]
        h = estimates.get(fi)
        if h is None or h.wrist_depth_m is not None:
            gap_start += 1
            continue
        # h detected but wrist_depth_m is None → start of a gap
        gap_end = gap_start
        while gap_end < n:
            fj = frame_indices[gap_end]
            hj = estimates.get(fj)
            if hj is None or hj.wrist_depth_m is not None:
                break
            gap_end += 1
        gap_len = gap_end - gap_start

        if gap_len > max_gap:
            gap_start = gap_end
            continue

        prev_idx = gap_start - 1
        next_idx = gap_end
        if prev_idx < 0 or next_idx >= n:
            gap_start = gap_end
            continue

        h_prev = estimates.get(frame_indices[prev_idx])
        h_next = estimates.get(frame_indices[next_idx])
        if (h_prev is None or h_prev.wrist_depth_m is None
                or h_next is None or h_next.wrist_depth_m is None):
            gap_start = gap_end
            continue

        d0, d1 = h_prev.wrist_depth_m, h_next.wrist_depth_m
        c0, c1 = h_prev.cam_t.astype(np.float32), h_next.cam_t.astype(np.float32)
        j0, j1 = h_prev.joints_3d.astype(np.float32), h_next.joints_3d.astype(np.float32)
        R0, R1 = h_prev.global_orient, h_next.global_orient
        p0 = h_prev.pinch_distance_m
        p1 = h_next.pinch_distance_m

        for k in range(gap_len):
            t = (k + 1) / (gap_len + 1)
            fi_k = frame_indices[gap_start + k]
            h_k = estimates[fi_k]
            if h_k is None:
                continue
            interp_depth = float(d0 * (1.0 - t) + d1 * t)
            new_cam_t = ((1.0 - t) * c0 + t * c1).astype(np.float32)
            new_joints = ((1.0 - t) * j0 + t * j1).astype(np.float32)
            new_R = _slerp_rotation(R0, R1, t)
            if p0 is not None and p1 is not None:
                new_pinch = float((1.0 - t) * p0 + t * p1)
            else:
                new_pinch = h_k.pinch_distance_m
            estimates[fi_k] = HandEstimate(
                is_right=h_k.is_right,
                joints_2d=h_k.joints_2d,
                joints_3d=new_joints,
                cam_t=new_cam_t,
                global_orient=new_R,
                bbox=h_k.bbox,
                wrist_depth_m=interp_depth,
                depth_interpolated=True,
                pinch_distance_m=new_pinch,
            )

        gap_start = gap_end


# ---------------------------------------------------------------------------
# Signals

def _generate_signals(
    frame_indices: List[int],
    frame_results: Dict[int, List[HandEstimate]],
    out_path: Path,
    sigma: float,
    full: bool = False,
) -> None:
    """Write signals.json.

    full=False (default): schema_version 1 — pinch distance only (key "value").
    full=True: schema_version 3 — pinch_m, cam_t, euler_deg, depth_ok, joints_2d per hand.
      - All frames where a hand is detected are written; both-hands-undetected
        frames emit {"right": null, "left": null} (key is NOT dropped).
      - cam_t and euler_deg are present for every detected hand regardless of
        depth_ok; depth_ok=False indicates pseudo-metric (unreliable absolute
        value, relative change still valid).
    """
    from scipy.ndimage import gaussian_filter1d

    right_pinch: List[float] = []
    left_pinch: List[float] = []
    right_depth_ok: List[bool] = []
    left_depth_ok: List[bool] = []
    right_detected: List[bool] = []
    left_detected: List[bool] = []

    for fi in frame_indices:
        hands = frame_results.get(fi, [])
        rh = next((h for h in hands if h.is_right), None)
        lh = next((h for h in hands if not h.is_right), None)
        right_pinch.append(rh.pinch_distance_m if (rh is not None and rh.pinch_distance_m is not None) else float("nan"))
        left_pinch.append(lh.pinch_distance_m if (lh is not None and lh.pinch_distance_m is not None) else float("nan"))
        right_depth_ok.append(rh.wrist_depth_m is not None if rh is not None else False)
        left_depth_ok.append(lh.wrist_depth_m is not None if lh is not None else False)
        right_detected.append(rh is not None)
        left_detected.append(lh is not None)

    r_arr = np.array(right_pinch, dtype=np.float64)
    l_arr = np.array(left_pinch, dtype=np.float64)

    def _smooth_nan(vals: np.ndarray, sig: float) -> np.ndarray:
        if sig <= 0 or len(vals) == 0:
            return vals.copy()
        nans = np.isnan(vals)
        filled = np.where(nans, 0.0, vals)
        weights = (~nans).astype(np.float64)
        sm_v = gaussian_filter1d(filled, sigma=sig, mode="nearest")
        sm_w = gaussian_filter1d(weights, sigma=sig, mode="nearest")
        return np.where(sm_w > 1e-9, sm_v / sm_w, np.nan)

    r_smooth = _smooth_nan(r_arr, sigma)
    l_smooth = _smooth_nan(l_arr, sigma)

    if full:
        from scipy.spatial.transform import Rotation
        out: dict = {"schema_version": 3}
        for i, fi in enumerate(frame_indices):
            key = f"frame_{fi:06d}"
            hands = frame_results.get(fi, [])
            rh = next((h for h in hands if h.is_right), None)
            lh = next((h for h in hands if not h.is_right), None)
            rv = r_smooth[i]
            lv = l_smooth[i]

            def _hand_entry(h: Optional[HandEstimate], pinch_smooth: float) -> Optional[dict]:
                if h is None:
                    return None
                arr = Rotation.from_matrix(h.global_orient.astype(float)).as_euler("ZYX", degrees=True)
                j2d = h.joints_2d  # (21, 2) float ndarray in source-image px
                joints_2d = [[round(float(j2d[i, 0]), 1), round(float(j2d[i, 1]), 1)] for i in range(21)]
                return {
                    "pinch_m": round(float(pinch_smooth), 6) if np.isfinite(pinch_smooth) else None,
                    "cam_t": [round(float(v), 6) for v in h.cam_t],
                    "euler_deg": {
                        "yaw": round(float(arr[0]), 3),
                        "pitch": round(float(arr[1]), 3),
                        "roll": round(float(arr[2]), 3),
                    },
                    "depth_ok": h.wrist_depth_m is not None,
                    "joints_2d": joints_2d,
                }

            out[key] = {
                "right": _hand_entry(rh, rv),
                "left": _hand_entry(lh, lv),
            }
    else:
        out = {"schema_version": 1}
        for i, fi in enumerate(frame_indices):
            key = f"frame_{fi:06d}"
            rv = r_smooth[i]
            lv = l_smooth[i]
            out[key] = {
                "right": {"value": round(float(rv), 6), "depth_ok": right_depth_ok[i]}
                         if right_detected[i] and np.isfinite(rv) else None,
                "left": {"value": round(float(lv), 6), "depth_ok": left_depth_ok[i]}
                        if left_detected[i] and np.isfinite(lv) else None,
            }
            # v1 omits frames where neither side was detected
            if out[key]["right"] is None and out[key]["left"] is None:
                del out[key]

    out_path.write_text(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# Viz overlay

_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),           # index
    (5, 9), (9, 10), (10, 11), (11, 12),      # middle
    (9, 13), (13, 14), (14, 15), (15, 16),    # ring
    (13, 17), (17, 18), (18, 19), (19, 20),   # pinky
    (0, 17),                                  # palm closure
]


def _draw_hands(bgr: np.ndarray, hands: List[HandEstimate], draw_all_kp: bool) -> None:
    """Draw MediaPipe 21-keypoint hand skeleton onto a BGR frame."""
    for h in hands:
        color = (0, 255, 0) if h.is_right else (255, 128, 0)
        j2d = h.joints_2d
        # skeleton
        for a, b in _HAND_CONNECTIONS:
            pa = tuple(int(x) for x in j2d[a])
            pb = tuple(int(x) for x in j2d[b])
            cv2.line(bgr, pa, pb, color, 2, cv2.LINE_AA)
        # wrist marker
        wrist = tuple(int(x) for x in j2d[0])
        cv2.circle(bgr, wrist, 6, color, -1)
        # depth label
        depth_str = (
            f"{h.wrist_depth_m:.2f}m{'[I]' if h.depth_interpolated else ''}"
            if h.wrist_depth_m is not None else "?m"
        )
        cv2.putText(bgr, depth_str, (wrist[0] + 10, wrist[1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        # bbox
        b = h.bbox.astype(int)
        cv2.rectangle(bgr, (b[0], b[1]), (b[2], b[3]), color, 1)
        if draw_all_kp:
            for j in range(21):
                pt = tuple(int(x) for x in j2d[j])
                cv2.circle(bgr, pt, 3, color, -1)


def _generate_overlay(
    video_path: Path,
    frame_results: Dict[int, List[HandEstimate]],
    out_path: Path,
    fps: float,
    draw_all_kp: bool,
) -> None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  ! cannot open {video_path} for viz", file=sys.stderr)
        return
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i in frame_results:
            _draw_hands(frame, frame_results[i], draw_all_kp)
            cv2.putText(frame, f"frame {i:06d}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            writer.write(frame)
        i += 1
    cap.release()
    writer.release()
    # Re-encode to H.264 for broader compatibility
    tmp = out_path.with_suffix(".h264.mp4")
    ret = subprocess.run(
        ["ffmpeg", "-y", "-i", str(out_path),
         "-vcodec", "libx264", "-crf", "23", str(tmp)],
        capture_output=True,
    )
    if ret.returncode == 0:
        out_path.unlink()
        tmp.rename(out_path)


# ---------------------------------------------------------------------------
# Main

def run(args: argparse.Namespace) -> dict:
    video_path = Path(args.video)
    depth_dir = Path(args.depth)
    out_dir = Path(args.out)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Load Phase A meta to get stride
    depth_meta_path = depth_dir / "meta.json"
    depth_meta: dict = {}
    if depth_meta_path.exists():
        depth_meta = json.loads(depth_meta_path.read_text())
    stride = args.stride if args.stride is not None else int(depth_meta.get("stride", 1))

    video_meta = _video_metadata(video_path)
    image_shape = (video_meta["height"], video_meta["width"])

    meta = {
        "video_source": str(video_path),
        "video_fps": video_meta["fps"],
        "video_width": video_meta["width"],
        "video_height": video_meta["height"],
        "video_total_frames": video_meta["total_frames"],
        "depth_source": str(depth_dir),
        "depth_meta": depth_meta,
        "stride": stride,
        "max_interp_gap": args.max_interp_gap,
        "frames_processed": 0,
        "frames_with_hands": 0,
        "frames_left_hand": 0,
        "frames_right_hand": 0,
        "frames_depth_missing": 0,
        "frames_left_interpolated": 0,
        "frames_right_interpolated": 0,
        "failures": [],
        "interrupted": False,
        "pass1_complete": False,
        "total_elapsed_seconds": 0.0,
        "fps_avg": 0.0,
    }

    def _save_meta():
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # --- SIGINT handler ---
    interrupted = {"flag": False}
    def _sigint(_sig, _frame):
        interrupted["flag"] = True
        print("\n[run_hand_estimation] SIGINT — finishing current frame…",
              file=sys.stderr, flush=True)
    signal.signal(signal.SIGINT, _sigint)

    # -----------------------------------------------------------------------
    # Pass 1
    # -----------------------------------------------------------------------
    # Buffer for Pass 2: frame_idx → HandEstimate|None per side
    left_estimates: Dict[int, Optional[HandEstimate]] = {}
    right_estimates: Dict[int, Optional[HandEstimate]] = {}
    all_frame_indices: List[int] = []

    t_start = time.time()
    n_done = 0
    try:
        for k, (frame_idx, bgr) in enumerate(_iter_video(video_path, stride)):
            if args.limit is not None and k >= args.limit:
                print(f"--limit {args.limit} reached", flush=True)
                break

            all_frame_indices.append(frame_idx)

            pkl_path = frames_dir / f"frame_{frame_idx:06d}.pkl"
            if pkl_path.exists() and not args.overwrite:
                # Resume: load existing result into buffer.
                # Note: raws are NOT stored in pkl, so interpolation (Pass 2) is
                # skipped for frames loaded from cache — _interpolate_side handles
                # this gracefully via the `if raw_k is None: continue` guard.
                existing = _load_pkl(pkl_path)
                if existing is not None:
                    for h in existing:
                        if h.is_right:
                            right_estimates[frame_idx] = h
                        else:
                            left_estimates[frame_idx] = h
                    left_estimates.setdefault(frame_idx, None)
                    right_estimates.setdefault(frame_idx, None)
                    n_done += 1
                    continue

            depth_npy = depth_dir / "frames" / f"frame_{frame_idx:06d}.npy"
            depth_erp: Optional[np.ndarray] = None
            if depth_npy.exists():
                try:
                    depth_erp = np.load(depth_npy)
                except Exception as e:
                    print(f"  ! frame {frame_idx}: failed to load depth: {e!r}",
                          file=sys.stderr)

            try:
                raws = _run_mediapipe(bgr)
                if raws and depth_erp is not None:
                    hands = _apply_metric_depth(raws, depth_erp, image_shape)
                elif raws:
                    # No depth available: passthrough (wrist_depth_m=None)
                    from mimicanno.hand_pipeline.pipeline import _passthrough_estimate
                    hands = [_passthrough_estimate(r) for r in raws]
                else:
                    hands = []

                # Populate per-side buffers
                left_h = right_h = None
                for h in hands:
                    if h.is_right:
                        right_h = h
                    else:
                        left_h = h

                left_estimates[frame_idx] = left_h
                right_estimates[frame_idx] = right_h

                _save_pkl_atomic(pkl_path, hands)
                n_done += 1

                if n_done % 20 == 0 or n_done == 1:
                    el = time.time() - t_start
                    rate = n_done / el if el > 0 else 0.0
                    print(f"  [{n_done}] frame {frame_idx}: "
                          f"{len(hands)} hand(s)  ({rate:.2f} fps)", flush=True)

            except Exception as e:
                meta["failures"].append({"frame": frame_idx, "err": repr(e)})
                print(f"  ! frame {frame_idx}: {e!r}", file=sys.stderr, flush=True)
                left_estimates.setdefault(frame_idx, None)
                right_estimates.setdefault(frame_idx, None)

            if interrupted["flag"]:
                meta["interrupted"] = True
                break

    finally:
        elapsed = time.time() - t_start
        meta["frames_processed"] = n_done
        meta["total_elapsed_seconds"] = round(elapsed, 3)
        meta["fps_avg"] = round(n_done / elapsed, 3) if elapsed > 0 else 0.0
        _save_meta()

    if meta["interrupted"]:
        print(f"Pass 1 interrupted. frames_processed={n_done}", flush=True)
        return meta

    meta["pass1_complete"] = True
    _save_meta()

    # -----------------------------------------------------------------------
    # Pass 2: temporal interpolation
    # -----------------------------------------------------------------------
    print("Pass 2: interpolating depth gaps…", flush=True)
    _interpolate_side(all_frame_indices, left_estimates, args.max_interp_gap)
    _interpolate_side(all_frame_indices, right_estimates, args.max_interp_gap)

    # Rewrite pkl files with interpolated values; collect stats
    frame_results: Dict[int, List[HandEstimate]] = {}
    n_with_hands = n_left = n_right = n_depth_miss = n_left_interp = n_right_interp = 0
    for fi in all_frame_indices:
        hands = []
        lh = left_estimates.get(fi)
        rh = right_estimates.get(fi)
        if lh is not None:
            hands.append(lh)
            n_left += 1
            if lh.wrist_depth_m is None:
                n_depth_miss += 1
            if lh.depth_interpolated:
                n_left_interp += 1
        if rh is not None:
            hands.append(rh)
            n_right += 1
            if rh.wrist_depth_m is None:
                n_depth_miss += 1
            if rh.depth_interpolated:
                n_right_interp += 1
        if hands:
            n_with_hands += 1
        frame_results[fi] = hands
        pkl_path = frames_dir / f"frame_{fi:06d}.pkl"
        _save_pkl_atomic(pkl_path, hands)

    meta.update({
        "frames_with_hands": n_with_hands,
        "frames_left_hand": n_left,
        "frames_right_hand": n_right,
        "frames_depth_missing": n_depth_miss,
        "frames_left_interpolated": n_left_interp,
        "frames_right_interpolated": n_right_interp,
    })
    _save_meta()
    print(f"Pass 2 done. with_hands={n_with_hands} "
          f"left={n_left} right={n_right} "
          f"depth_missing={n_depth_miss} "
          f"interp=({n_left_interp},{n_right_interp})", flush=True)

    # -----------------------------------------------------------------------
    # Signals
    # -----------------------------------------------------------------------
    signals_path = out_dir / "signals.json"
    print(f"generating signals.json (pinch_smooth_sigma={args.pinch_smooth_sigma}, full={args.full_signals})…", flush=True)
    _generate_signals(all_frame_indices, frame_results, signals_path, args.pinch_smooth_sigma, full=args.full_signals)
    meta["signals_path"] = str(signals_path)
    _save_meta()

    # -----------------------------------------------------------------------
    # Viz
    # -----------------------------------------------------------------------
    if args.save_viz:
        viz_dir = out_dir / "viz"
        viz_dir.mkdir(exist_ok=True)
        overlay_path = viz_dir / "overlay.mp4"
        print(f"generating viz → {overlay_path}", flush=True)
        _generate_overlay(
            video_path, frame_results, overlay_path,
            fps=video_meta["fps"] / max(stride, 1),
            draw_all_kp=args.viz_keypoints,
        )

    total_elapsed = time.time() - t_start
    meta["total_elapsed_seconds"] = round(total_elapsed, 3)
    meta["fps_avg"] = round(n_done / total_elapsed, 3) if total_elapsed > 0 else 0.0
    _save_meta()

    print(f"done. processed={n_done} with_hands={n_with_hands} "
          f"failures={len(meta['failures'])} elapsed={total_elapsed:.1f}s → {out_dir}",
          flush=True)
    return meta


def run_signals_only(args: argparse.Namespace) -> None:
    """Regenerate signals.json from existing frames/*.pkl without re-running detection."""
    out_dir = Path(args.out)
    frames_dir = out_dir / "frames"
    meta_path = out_dir / "meta.json"

    if not meta_path.exists():
        print(f"error: {meta_path} not found — cannot read fps/shape without meta.json", file=sys.stderr)
        sys.exit(1)

    pkl_paths = sorted(frames_dir.glob("frame_*.pkl"))
    if not pkl_paths:
        print(f"error: no frame_*.pkl found in {frames_dir}", file=sys.stderr)
        sys.exit(1)

    frame_results: Dict[int, List[HandEstimate]] = {}
    for p in pkl_paths:
        frame_idx = int(p.stem.split("_")[1])
        with open(p, "rb") as f:
            frame_results[frame_idx] = pickle.load(f)

    frame_indices = sorted(frame_results.keys())
    signals_path = out_dir / "signals.json"
    print(f"generating signals.json from {len(frame_indices)} frames "
          f"(sigma={args.pinch_smooth_sigma}, full={args.full_signals})…", flush=True)
    _generate_signals(frame_indices, frame_results, signals_path, args.pinch_smooth_sigma, full=args.full_signals)
    print(f"wrote {signals_path}", flush=True)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Phase B: MediaPipe hand-landmark estimation with UniDAC metric depth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--video", default=None, help="input MP4 video (not required with --signals-only)")
    ap.add_argument("--depth", default=None, help="Phase A output directory (not required with --signals-only)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--stride", type=int, default=None,
                    help="frame subsampling (default: read from depth/meta.json, else 1)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N frames (debug)")
    ap.add_argument("--max-interp-gap", type=int, default=5,
                    help="max consecutive frames with missing depth to interpolate (default: 5)")
    ap.add_argument("--no-viz", action="store_false", dest="save_viz",
                    help="skip generating viz/overlay.mp4")
    ap.add_argument("--viz-keypoints", action="store_true",
                    help="draw all 21 joints + skeleton (default: wrist only)")
    ap.add_argument("--overwrite", action="store_true",
                    help="reprocess frames whose .pkl already exists")
    ap.add_argument("--pinch-smooth-sigma", type=float, default=2.0,
                    help="Gaussian smoothing sigma [frames] for pinch_distance_m in signals.json (0 = no smoothing, default: 2.0)")
    ap.add_argument("--signals-only", action="store_true",
                    help="skip hand estimation; regenerate signals.json from existing frames/*.pkl")
    ap.add_argument("--full-signals", action="store_true",
                    help="write schema_version 3 signals.json with cam_t + euler_deg + joints_2d (default: v1 pinch-only)")
    ap.set_defaults(save_viz=True)
    return ap


def main() -> int:
    args = _build_parser().parse_args()
    if args.signals_only:
        run_signals_only(args)
        return 0
    if args.video is None or args.depth is None:
        print("error: --video and --depth are required unless --signals-only is set", file=sys.stderr)
        return 1
    meta = run(args)
    return 0 if not meta["failures"] else 2


if __name__ == "__main__":
    sys.exit(main())
