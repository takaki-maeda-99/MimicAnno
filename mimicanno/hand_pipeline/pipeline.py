"""Hand pose estimation pipeline combining HaMeR + UniDAC depth.

Phase 2d status: _fuse implemented. estimate_hand (Phase 2e) is a stub.

Environment: HaMeR venv (``/misc/dl00/gayagaya/MimicAnno/hamer/.hamer/bin/python``).
Run any caller (CLI or pytest) from this env with::

    PYTHONPATH=/misc/dl00/gayagaya/MimicAnno:/misc/dl00/gayagaya/MimicAnno/UniDAC \\
        /misc/dl00/gayagaya/MimicAnno/hamer/.hamer/bin/python -m pytest ...

The module inserts ``<MimicAnno>/hamer`` onto ``sys.path`` at import time so
the HaMeR low-level modules (``demo_video``, ``vitpose_model``) are importable
without a separate PYTHONPATH dance, and it cd's into ``hamer/`` during
pipeline construction so the renderer / detector configs that use relative
paths resolve correctly.
"""
from __future__ import annotations

import contextlib
import functools
import math
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # hand_pipeline → mimicanno → MimicAnno
_HAMER_ROOT = _REPO_ROOT / "hamer"
_UNIDAC_ROOT = _REPO_ROOT / "UniDAC"
if _HAMER_ROOT.exists() and str(_HAMER_ROOT) not in sys.path:
    sys.path.insert(0, str(_HAMER_ROOT))
if _UNIDAC_ROOT.exists() and str(_UNIDAC_ROOT) not in sys.path:
    sys.path.insert(0, str(_UNIDAC_ROOT))


# UniDAC Preset A camera parameters. The forward pipeline (api.py:131-139) uses
# cano_sz=[1400,1400], crop_wFoV=150 -> crop_w=1166, crop_h=848; the ERP frame is
# 1400 x 2800. We reproduce these constants here so the back-warp does not need
# to instantiate a UniDACPipeline.
_PRESET_A = {
    "fl_x_ref": 1820.0,
    "fl_y_ref": 1275.0,
    "k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0,
    "crop_wFoV": 150,
    "camera_model": "OPENCV_FISHEYE",
    "cano_sz_h": 1400,
    "cano_sz_w": 1400,
    "fwd_sz_h": 512,
    "fwd_sz_w": 704,
    "ref_w_native": 5312,
}


@dataclass
class HamerRaw:
    """Per-hand raw output from HaMeR (pre-fusion, pseudo-metric scale).

    ``cam_t`` and ``vertices`` live in HaMeR's camera frame, but the metric
    scale is set by HaMeR's heuristic focal length (pinhole assumption), which
    is unreliable for fisheye input. Scale calibration happens in `_fuse`
    (Phase 2d).
    """
    is_right: bool
    betas: np.ndarray         # (10,)            float32
    global_orient: np.ndarray # (3, 3)           float32 rotation matrix
    hand_pose: np.ndarray     # (15, 3, 3)       float32 rotation matrices
    cam_t: np.ndarray         # (3,)             float32 translation, pseudo-metric
    vertices: np.ndarray      # (778, 3)         float32 MANO mesh (x-mirror applied)
    joints_3d: np.ndarray     # (21, 3)          float32 in HaMeR cam frame
    joints_2d: np.ndarray     # (21, 2)          float32 input-image pixels
    bbox: np.ndarray          # (4,)             float32 xyxy input-image pixels


@dataclass
class HandEstimate:
    """Per-hand metric output after UniDAC depth-based position correction.

    All 3-D arrays are in HaMeR's camera frame.  ``cam_t`` is set by
    back-projecting the wrist pixel through the fisheye camera model using the
    UniDAC euclid-distance depth at that pixel (``wrist_depth_m``).  When
    depth is unavailable ``cam_t`` falls back to HaMeR's pseudo-metric value
    and ``wrist_depth_m`` is ``None``.
    """
    is_right: bool
    betas: np.ndarray         # (10,)            float32
    global_orient: np.ndarray # (3, 3)           float32 rotation matrix
    hand_pose: np.ndarray     # (15, 3, 3)       float32 rotation matrices
    cam_t: np.ndarray         # (3,)             float32 metric (or pseudo-metric) translation
    vertices: np.ndarray      # (778, 3)         float32 MANO mesh in cam frame
    joints_3d: np.ndarray     # (21, 3)          float32 in cam frame
    joints_2d: np.ndarray     # (21, 2)          float32 input-image pixels (pinhole approx)
    bbox: np.ndarray          # (4,)             float32 xyxy input-image pixels
    # --- depth fusion fields (all have defaults so existing call sites still work) ---
    wrist_depth_m: Optional[float] = None  # UniDAC euclid depth at wrist [m]; None if unavailable
    depth_interpolated: bool = False       # True when wrist_depth_m was filled by interpolation
    pinch_distance_m: Optional[float] = None  # |joints_local[4] - joints_local[8]| [m]; cam_t-independent
    # --- deprecated: retained for backward-compatibility, always None / 0 ---
    scale_factor: Optional[float] = None  # formerly _fuse() scale; now always None
    n_valid_samples: int = 0              # formerly _fuse() sample count; now always 0


@contextlib.contextmanager
def _cwd(path: Path):
    prev = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(prev)


@functools.lru_cache(maxsize=1)
def _get_hamer_pipeline():
    """Build the HaMeR pipeline dict once per process."""
    from demo_video import build_pipeline  # type: ignore
    with _cwd(_HAMER_ROOT):
        return build_pipeline(body_detector="regnety")


def _run_hamer(image: np.ndarray, *, rescale_factor: float = 2.0,
               batch_size: int = 8) -> Optional[List[HamerRaw]]:
    """Run HaMeR on a single image and return per-hand raw outputs.

    Args:
        image: ``(H, W, 3)`` uint8 BGR (``cv2.imread`` convention).
        rescale_factor: HaMeR's ViTDet bbox expansion factor.
        batch_size: forwarded to the inner DataLoader.

    Returns:
        A list of ``HamerRaw`` (one per detected hand). Empty list if HaMeR
        detected no hands. The function does not currently surface a
        distinguishable "pipeline failed" state separately from "no hands";
        future callers can wrap exceptions.
    """
    import torch
    from torch.utils.data import DataLoader

    from demo_video import detect_hand_bboxes               # type: ignore
    from hamer.datasets.vitdet_dataset import ViTDetDataset
    from hamer.utils import recursive_to
    from hamer.utils.renderer import cam_crop_to_full

    if image.dtype != np.uint8:
        raise ValueError(f"image must be uint8, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"image must be HxWx3 BGR, got shape {image.shape}")

    pipe = _get_hamer_pipeline()
    model = pipe["model"]
    model_cfg = pipe["model_cfg"]
    device = pipe["device"]

    with _cwd(_HAMER_ROOT):
        bboxes, right = detect_hand_bboxes(image, pipe["detector"], pipe["cpm"])
    if bboxes is None or len(bboxes) == 0:
        return []

    H, W = image.shape[:2]
    img_max = float(max(H, W))
    scaled_focal_length = (
        model_cfg.EXTRA.FOCAL_LENGTH / model_cfg.MODEL.IMAGE_SIZE * img_max
    )

    with _cwd(_HAMER_ROOT):
        dataset = ViTDetDataset(model_cfg, image, bboxes, right,
                                rescale_factor=rescale_factor)
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False,
                            num_workers=0)

        results: List[HamerRaw] = []
        bbox_idx = 0
        for batch in loader:
            batch = recursive_to(batch, device)
            with torch.no_grad():
                out = model(batch)

            multiplier = (2 * batch["right"] - 1)
            pred_cam = out["pred_cam"].clone()
            pred_cam[:, 1] = multiplier * pred_cam[:, 1]
            box_center = batch["box_center"].float()
            box_size = batch["box_size"].float()
            img_size_t = batch["img_size"].float()
            cam_t_full = cam_crop_to_full(
                pred_cam, box_center, box_size, img_size_t, scaled_focal_length,
            ).detach().cpu().numpy()

            joints = out["pred_keypoints_3d"].detach().cpu().numpy()
            verts = out["pred_vertices"].detach().cpu().numpy()
            mano_go = out["pred_mano_params"]["global_orient"].detach().cpu().numpy()
            mano_hp = out["pred_mano_params"]["hand_pose"].detach().cpu().numpy()
            mano_bt = out["pred_mano_params"]["betas"].detach().cpu().numpy()

            n_in_batch = batch["img"].shape[0]
            for n in range(n_in_batch):
                is_right_n = bool(batch["right"][n].cpu().numpy().item())
                sign = 2.0 * float(is_right_n) - 1.0

                v = verts[n].astype(np.float32, copy=True)
                v[:, 0] = sign * v[:, 0]

                j3 = joints[n].astype(np.float32, copy=True)
                j3[:, 0] = sign * j3[:, 0]
                cam_t = cam_t_full[n].astype(np.float32)
                j3_cam = j3 + cam_t[None, :]

                fl = float(scaled_focal_length.item()
                           if hasattr(scaled_focal_length, "item")
                           else scaled_focal_length)
                iw = float(img_size_t[n, 0].item())
                ih = float(img_size_t[n, 1].item())
                Z = j3_cam[:, 2]
                safe_Z = np.where(Z > 1e-6, Z, 1.0)
                u = fl * j3_cam[:, 0] / safe_Z + iw / 2.0
                vv = fl * j3_cam[:, 1] / safe_Z + ih / 2.0
                j2 = np.stack([u, vv], axis=-1).astype(np.float32)
                j2[Z <= 1e-6] = np.float32("nan")

                # Squeeze MANO global_orient from (1,3,3) -> (3,3).
                go = mano_go[n].astype(np.float32)
                if go.ndim == 3 and go.shape[0] == 1:
                    go = go[0]

                results.append(HamerRaw(
                    is_right=is_right_n,
                    betas=mano_bt[n].astype(np.float32),
                    global_orient=go,
                    hand_pose=mano_hp[n].astype(np.float32),
                    cam_t=cam_t,
                    vertices=v,
                    joints_3d=j3_cam.astype(np.float32),
                    joints_2d=j2,
                    bbox=np.asarray(bboxes[bbox_idx], dtype=np.float32),
                ))
                bbox_idx += 1

    return results


# ---------------------------------------------------------------------------
# ERP -> input camera back-warp (Phase 2c).

def _preset_a_cam_params(W: int, H: int) -> dict:
    """Build the UniDAC cam_params dict for Preset A at input resolution (W, H)."""
    s = W / _PRESET_A["ref_w_native"]
    return {
        # dataset name must be one that triggers the fisheye-lookup branch of
        # erp_patch_to_cam_fast ('kitti360' | 'scannetpp' | 'zipnerf'); we
        # provide the lookup table ourselves below.
        "dataset": "scannetpp",
        "fl_x": float(_PRESET_A["fl_x_ref"] * s),
        "fl_y": float(_PRESET_A["fl_y_ref"] * s),
        "fx":   float(_PRESET_A["fl_x_ref"] * s),
        "fy":   float(_PRESET_A["fl_y_ref"] * s),
        "cx":   float(W / 2.0),
        "cy":   float(H / 2.0),
        "k1": 0.0, "k2": 0.0, "k3": 0.0, "k4": 0.0,
        "camera_model": "OPENCV_FISHEYE",
    }


def _build_fisheye_grid2ray(W: int, H: int, cam: dict,
                            theta_max: float = math.pi / 2) -> np.ndarray:
    """Per-pixel unit ray for an OpenCV equidistant fisheye (k1..k4 == 0).

    Returns array (H, W, 4): [..., 0..2] = ray (X, Y, Z) on the unit sphere in
    camera frame, [..., 3] = 1.0 if the pixel is invalid (back hemisphere, i.e.
    theta > theta_max), else 0.0. erp_patch_to_cam_fast consumes this via the
    'scannetpp' lookup branch.
    """
    fx, fy = cam["fx"], cam["fy"]
    cx, cy = cam["cx"], cam["cy"]
    u = np.arange(W, dtype=np.float32)
    v = np.arange(H, dtype=np.float32)
    uu, vv = np.meshgrid(u, v)  # (H, W)
    xn = (uu - cx) / fx
    yn = (vv - cy) / fy
    # Equidistant: theta_d = theta (k=0), and theta = sqrt(xn^2 + yn^2).
    theta = np.sqrt(xn * xn + yn * yn)
    eps = 1e-9
    sin_th = np.sin(theta)
    cos_th = np.cos(theta)
    rx = sin_th * xn / np.maximum(theta, eps)
    ry = sin_th * yn / np.maximum(theta, eps)
    rz = cos_th
    # At theta == 0 (centre pixel) the formula above gives 0/eps = 0; force +Z.
    centre = theta < eps
    rx[centre] = 0.0; ry[centre] = 0.0; rz[centre] = 1.0
    isnan = (theta > theta_max).astype(np.float32)
    grid = np.stack([rx, ry, rz, isnan], axis=-1).astype(np.float32)
    return grid


def _back_warp_depth(
    depth_erp: np.ndarray,
    image_shape: Tuple[int, int],
    *,
    preset: str = "A",
    device: Optional[str] = None,
) -> np.ndarray:
    """Inverse-project a UniDAC ERP-space depth map onto the input image grid.

    Args:
        depth_erp: ``(H_erp, W_erp)`` float32 metric depth produced by
            ``UniDACPipeline.predict_frame`` (e.g. ``(512, 704)`` for Preset A).
        image_shape: ``(H, W)`` of the source camera frame UniDAC consumed.
        preset: UniDAC preset name. Only ``"A"`` is supported.

    Returns:
        ``(H, W)`` float32 metric depth in the input image's pixel grid.
        Pixels that fall outside the ERP patch (or were marked invalid by the
        fisheye projection) are ``NaN``.
    """
    if preset != "A":
        raise NotImplementedError(f"preset {preset!r} not supported in Phase 2c")
    import cv2
    import torch
    from unidac.utils.erp_geometry import erp_patch_to_cam_fast  # type: ignore

    H, W = image_shape
    cam_params = _preset_a_cam_params(W, H)

    # Reproduce the forward-projection geometry from api.py::predict_frame.
    cano_w = _PRESET_A["cano_sz_w"]  # ERP cano half-width
    crop_w = int(cano_w * _PRESET_A["crop_wFoV"] / 180)                 # 1166
    crop_h = int(crop_w * _PRESET_A["fwd_sz_h"] / _PRESET_A["fwd_sz_w"])  # 848
    erp_h = cano_w               # 1400
    erp_w = cano_w * 2           # 2800

    if depth_erp.ndim != 2:
        raise ValueError(f"depth_erp must be 2D, got shape {depth_erp.shape}")
    # resize_for_input in the forward pass downsamples the (crop_h, crop_w)
    # patch to fwd_sz=(512,704). We undo that here with a bilinear upscale so
    # the lat/long span computed inside erp_patch_to_cam_fast lines up with the
    # ERP frame size we pass.
    depth_patch = cv2.resize(depth_erp.astype(np.float32), (crop_w, crop_h),
                              interpolation=cv2.INTER_LINEAR)
    mask_patch = ((depth_patch > 0) & np.isfinite(depth_patch)).astype(np.float32)

    dev = torch.device(device) if device else (
        torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    )
    img_dummy = np.zeros((3, crop_h, crop_w), dtype=np.float32)
    depth_t = torch.from_numpy(depth_patch[None]).float().to(dev)   # (1, H, W)
    mask_t = torch.from_numpy(mask_patch[None]).float().to(dev)     # (1, H, W)
    img_t = torch.from_numpy(img_dummy).float().to(dev)             # (3, H, W)

    # Cache grid2ray: recomputing a (H,W,4) float32 array every frame is wasteful
    # since it only depends on (image_shape, preset) which is constant per video.
    _cache_key = (image_shape, preset)
    if _cache_key not in _back_warp_depth._grid2ray_cache:
        _back_warp_depth._grid2ray_cache[_cache_key] = _build_fisheye_grid2ray(W, H, cam_params)
    fisheye_grid2ray = _back_warp_depth._grid2ray_cache[_cache_key]

    _img_out, depth_out, mask_valid_out, mask_active = erp_patch_to_cam_fast(
        img_t, depth_t, mask_t,
        0, 0,                                       # theta, phi
        H, W,                                       # out_h, out_w
        erp_h, erp_w,
        cam_params,
        fisheye_grid2ray=fisheye_grid2ray,
    )

    depth_np = depth_out[0, 0].cpu().numpy().astype(np.float32)
    valid = ((mask_active[0].cpu().numpy() > 0.5)
             & (mask_valid_out[0, 0].cpu().numpy() > 0.5))
    depth_np[~valid] = np.nan
    return depth_np


_back_warp_depth._grid2ray_cache = {}


def _sample_depth_at_pixels(
    depth_erp: np.ndarray,
    pixels: np.ndarray,
    image_shape: Tuple[int, int],
    *,
    preset: str = "A",
) -> np.ndarray:
    """Sample UniDAC depth at specific fisheye-image pixels.

    Forward-projects each input pixel through Preset A's equidistant fisheye
    (k1..k4 = 0) and gnomonic patch transform, then bilinearly samples the
    ERP depth. Orders of magnitude cheaper than ``_back_warp_depth`` when only
    a few hundred query pixels are needed (e.g. MANO vertices / joints).

    Args:
        depth_erp: ``(H_erp, W_erp)`` float32 metric depth from UniDAC, e.g.
            ``(512, 704)`` for Preset A.
        pixels: ``(N, 2)`` array of ``[u, v]`` floating-point pixel positions
            in the fisheye input image. Subpixel coordinates are honoured.
        image_shape: ``(H, W)`` of the source camera frame.
        preset: only ``"A"`` is supported.

    Returns:
        ``(N,)`` float32 depth in metres. ``NaN`` for pixels in the back
        hemisphere, outside the ERP patch's 150° crop, or where the sampled
        depth is zero.
    """
    if preset != "A":
        raise NotImplementedError(f"preset {preset!r} not supported")
    import cv2

    H, W = image_shape
    cam = _preset_a_cam_params(W, H)
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]

    pix = np.asarray(pixels, dtype=np.float64)
    if pix.ndim != 2 or pix.shape[1] != 2:
        raise ValueError(f"pixels must be (N, 2), got shape {pix.shape}")
    u = pix[:, 0]
    v = pix[:, 1]

    # 1) Inverse fisheye (equidistant, k=0): pixel -> unit ray in camera frame.
    xn = (u - cx) / fx
    yn = (v - cy) / fy
    theta = np.sqrt(xn * xn + yn * yn)
    eps = 1e-12
    safe = np.maximum(theta, eps)
    sin_t = np.sin(theta)
    rx = sin_t * xn / safe
    ry = sin_t * yn / safe
    rz = np.cos(theta)
    centre = theta < eps
    rx[centre] = 0.0; ry[centre] = 0.0; rz[centre] = 1.0

    # 2) Unit ray -> (latitude, longitude) for the patch tangent at theta=phi=0.
    lat = np.arcsin(np.clip(ry, -1.0, 1.0))
    lon = np.arctan2(rx, rz)

    # 3) (lat, lon) -> normalized patch coords in [-1, 1].
    cano_w = _PRESET_A["cano_sz_w"]
    crop_w = int(cano_w * _PRESET_A["crop_wFoV"] / 180)
    crop_h = int(crop_w * _PRESET_A["fwd_sz_h"] / _PRESET_A["fwd_sz_w"])
    erp_h = cano_w
    erp_w = cano_w * 2
    lat_span = crop_h / erp_h * math.pi
    long_span = crop_w / erp_w * 2.0 * math.pi
    nx = lon / long_span * 2.0
    ny = lat / lat_span * 2.0

    valid = (
        (theta < math.pi / 2.0)
        & (np.abs(nx) < 1.0) & (np.abs(ny) < 1.0)
        & np.isfinite(theta)
    )

    # 4) Normalized patch coords -> fwd_sz pixel coords (the depth_erp grid).
    He, We = depth_erp.shape
    fwd_u = (nx + 1.0) * 0.5 * (We - 1)
    fwd_v = (ny + 1.0) * 0.5 * (He - 1)

    # 5) Bilinear sample via cv2.remap (treat the N-point array as 1xN).
    map_x = np.where(valid, fwd_u, 0.0).astype(np.float32).reshape(1, -1)
    map_y = np.where(valid, fwd_v, 0.0).astype(np.float32).reshape(1, -1)
    sampled = cv2.remap(
        depth_erp.astype(np.float32), map_x, map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0.0,
    ).reshape(-1)

    out = sampled.astype(np.float32)
    out[~valid] = np.nan
    out[out == 0.0] = np.nan
    return out


# ---------------------------------------------------------------------------
# Phase B: wrist-pixel depth back-projection.

def _apply_metric_depth(
    hamer_raws: List[HamerRaw],
    depth_erp: np.ndarray,
    image_shape: Tuple[int, int],
) -> List[HandEstimate]:
    """Replace HaMeR's pseudo-metric cam_t with UniDAC metric depth at the wrist.

    For each detected hand:
    1. Sample UniDAC ERP depth at the wrist pixel (MANO joint 0) and its 8
       neighbours; take the median of finite positive values.
    2. Back-project (u, v, depth) through the equidistant fisheye model to get
       a metric cam_t.  UniDAC outputs euclid (ray) distance, so
       ``cam_t = depth * unit_ray``.
    3. Shift joints_3d and vertices by the cam_t delta.

    When depth is unavailable (all 9 samples are NaN/0), cam_t is left
    unchanged and ``wrist_depth_m`` is ``None``.
    """
    if not hamer_raws:
        return []

    H, W = image_shape
    cam = _preset_a_cam_params(W, H)
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]

    # 3×3 neighbourhood offsets for robust wrist depth sampling.
    _offsets = np.array(
        [[du, dv] for du in (-1, 0, 1) for dv in (-1, 0, 1)],
        dtype=np.float32,
    )

    results: List[HandEstimate] = []
    for raw in hamer_raws:
        wrist_uv = raw.joints_2d[0]  # MANO joint 0 = wrist (pinhole approx.)
        if np.any(np.isnan(wrist_uv)):
            depth_val: Optional[float] = None
        else:
            pts = wrist_uv[None, :] + _offsets          # (9, 2)
            samples = _sample_depth_at_pixels(depth_erp, pts, image_shape)
            finite_pos = samples[np.isfinite(samples) & (samples > 0)]
            depth_val = float(np.median(finite_pos)) if finite_pos.size > 0 else None

        if depth_val is not None:
            u, v = float(wrist_uv[0]), float(wrist_uv[1])
            xn = (u - cx) / fx
            yn = (v - cy) / fy
            theta = math.sqrt(xn * xn + yn * yn)
            if theta < 1e-9:
                rx, ry, rz = 0.0, 0.0, 1.0
            else:
                sin_t = math.sin(theta)
                rx = sin_t * xn / theta
                ry = sin_t * yn / theta
                rz = math.cos(theta)
            new_cam_t = np.array(
                [rx * depth_val, ry * depth_val, rz * depth_val], dtype=np.float32
            )
            offset = new_cam_t - raw.cam_t
            new_joints_3d = (raw.joints_3d + offset[None, :]).astype(np.float32)
            new_vertices = (raw.vertices + new_cam_t[None, :]).astype(np.float32)
        else:
            new_cam_t = raw.cam_t.copy()
            new_joints_3d = raw.joints_3d.copy()
            new_vertices = (raw.vertices + raw.cam_t[None, :]).astype(np.float32)

        # Pinch distance is cam_t-independent: compute from joints_local (= raw.joints_3d - raw.cam_t).
        joints_local = raw.joints_3d - raw.cam_t[None, :]
        pinch = float(np.linalg.norm(joints_local[4] - joints_local[8]))

        results.append(HandEstimate(
            is_right=raw.is_right,
            betas=raw.betas.copy(),
            global_orient=raw.global_orient.copy(),
            hand_pose=raw.hand_pose.copy(),
            cam_t=new_cam_t,
            vertices=new_vertices,
            joints_3d=new_joints_3d,
            joints_2d=raw.joints_2d.copy(),
            bbox=raw.bbox.copy(),
            wrist_depth_m=depth_val,
            pinch_distance_m=pinch,
        ))

    return results


# ---------------------------------------------------------------------------
# Phase 2d: depth-based scale fusion (deprecated — kept for reference).

_SCALE_WARN_LO = 0.01
_SCALE_WARN_HI = 1.0


def _fuse(
    hamer_raws: List[HamerRaw],
    depth_erp: np.ndarray,
    image_shape: Tuple[int, int],
) -> List[HandEstimate]:
    """[DEPRECATED] Fuse HaMeR raw hand estimates with UniDAC metric depth.

    Replaced by ``_apply_metric_depth``. Kept for reference and legacy tests.

    Computes a single image-level scale factor as::

        scale = median(unidac_z_valid) / median(hamer_z_valid)

    where the medians pool the depth samples and HaMeR z-values from *all*
    21 joints of *all* detected hands in the image. This one scale is then
    applied only to ``cam_t``; MANO shape and pose are not altered.

    Args:
        hamer_raws: list of ``HamerRaw`` for all hands in one image.
        depth_erp: ``(H_erp, W_erp)`` float32 UniDAC depth (Preset A: 512×704).
        image_shape: ``(H, W)`` of the source camera frame.

    Returns:
        List of ``HandEstimate`` in the same order as ``hamer_raws``, each with
        metric-corrected ``cam_t``, ``vertices``, and ``joints_3d``.
        Returns an empty list if ``hamer_raws`` is empty or if all depth
        samples are NaN (with a ``UserWarning`` in the latter case).
    """
    if not hamer_raws:
        return []

    # Forward-project all 21 joints of every hand into UniDAC depth.
    all_j2d = np.concatenate([r.joints_2d for r in hamer_raws], axis=0)  # (N*21, 2)
    all_j3d = np.concatenate([r.joints_3d for r in hamer_raws], axis=0)  # (N*21, 3)

    unidac_z = _sample_depth_at_pixels(depth_erp, all_j2d, image_shape)  # (N*21,)
    hamer_z = all_j3d[:, 2]                                               # (N*21,)

    valid = np.isfinite(unidac_z) & np.isfinite(hamer_z) & (hamer_z > 1e-6)
    if not valid.any():
        warnings.warn(
            "_fuse: all depth samples are NaN; cannot compute scale. "
            "Returning empty list.",
            UserWarning, stacklevel=2,
        )
        return []

    scale = float(np.median(unidac_z[valid]) / np.median(hamer_z[valid]))

    if not (_SCALE_WARN_LO <= scale <= _SCALE_WARN_HI):
        warnings.warn(
            f"_fuse: scale_factor={scale:.5f} is outside the expected range "
            f"[{_SCALE_WARN_LO}, {_SCALE_WARN_HI}]. Check depth units.",
            UserWarning, stacklevel=2,
        )

    results: List[HandEstimate] = []
    for raw in hamer_raws:
        new_cam_t = (raw.cam_t * np.float32(scale)).astype(np.float32)

        # vertices are in MANO local frame (not offset by cam_t); place in cam frame.
        new_vertices = (raw.vertices + new_cam_t[None, :]).astype(np.float32)

        # joints_3d = joints_local + raw.cam_t; apply new translation instead.
        joints_local = raw.joints_3d - raw.cam_t[None, :]
        new_joints_3d = (joints_local + new_cam_t[None, :]).astype(np.float32)

        results.append(HandEstimate(
            is_right=raw.is_right,
            betas=raw.betas.copy(),
            global_orient=raw.global_orient.copy(),
            hand_pose=raw.hand_pose.copy(),
            cam_t=new_cam_t,
            vertices=new_vertices,
            joints_3d=new_joints_3d,
            joints_2d=raw.joints_2d.copy(),
            bbox=raw.bbox.copy(),
            scale_factor=scale,
            n_valid_samples=int(valid.sum()),
        ))

    return results


# ---------------------------------------------------------------------------
# Phase 2e: top-level API.

def _passthrough_estimate(raw: HamerRaw) -> HandEstimate:
    """Wrap a HamerRaw as a HandEstimate with no depth correction (refine=False)."""
    joints_local = raw.joints_3d - raw.cam_t[None, :]
    pinch = float(np.linalg.norm(joints_local[4] - joints_local[8]))
    return HandEstimate(
        is_right=raw.is_right,
        betas=raw.betas.copy(),
        global_orient=raw.global_orient.copy(),
        hand_pose=raw.hand_pose.copy(),
        cam_t=raw.cam_t.copy(),
        vertices=(raw.vertices + raw.cam_t[None, :]).astype(np.float32),
        joints_3d=raw.joints_3d.copy(),
        joints_2d=raw.joints_2d.copy(),
        bbox=raw.bbox.copy(),
        wrist_depth_m=None,
        pinch_distance_m=pinch,
    )


def estimate_hand(
    image: np.ndarray,
    depth: np.ndarray,
    *,
    refine: bool = True,
    return_intermediate: bool = False,
):
    """Top-level API: fisheye RGB + precomputed UniDAC depth → metric hand poses.

    Args:
        image: ``(H, W, 3)`` uint8 BGR frame (``cv2.imread`` convention).
        depth: ``(H_erp, W_erp)`` float32 UniDAC depth in metres, as produced
            by ``scripts/precompute_depth.py`` (Preset A: ``(512, 704)``).
        refine: if ``True`` (default) apply UniDAC wrist-depth back-projection
            via ``_apply_metric_depth``.  If ``False`` return pseudo-metric
            HaMeR output (``wrist_depth_m=None``, useful for debugging).
        return_intermediate: if ``True`` return a ``(estimates, hamer_raws)``
            tuple; otherwise return only the ``list[HandEstimate]``.

    Returns:
        ``list[HandEstimate]`` (empty only if no hands detected; hands with
        unavailable depth are included with ``wrist_depth_m=None``), or
        ``(list[HandEstimate], list[HamerRaw])`` when
        ``return_intermediate=True``.
    """
    hamer_raws = _run_hamer(image)

    if not hamer_raws:
        estimates: List[HandEstimate] = []
    elif refine:
        estimates = _apply_metric_depth(hamer_raws, depth, image.shape[:2])
    else:
        estimates = [_passthrough_estimate(r) for r in hamer_raws]

    if return_intermediate:
        return estimates, hamer_raws
    return estimates
