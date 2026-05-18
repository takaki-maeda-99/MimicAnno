"""Hand pose estimation pipeline (MediaPipe HandLandmarker + UniDAC depth).

Pipeline overview:
  1. ``_run_mediapipe`` runs MediaPipe Tasks API ``HandLandmarker`` on a BGR
     uint8 frame and returns per-hand :class:`HandRaw` (2D pixel landmarks,
     wrist-centred 3D world landmarks in metres, handedness).
  2. ``_apply_metric_depth`` samples the precomputed UniDAC ERP depth at the
     wrist pixel (with 3x3 neighbourhood median), back-projects through the
     fisheye camera model to produce a metric ``cam_t``, and pairs it with the
     palm-axis-derived rotation from ``_palm_frame``.
  3. ``estimate_hand`` is the top-level API that wires the two together; when
     ``depth`` is ``None`` it falls back to ``_passthrough_estimate`` (cam_t=0).

Runtime environments (see ``mimicanno/hand_pipeline/__init__.py``):
  * MediaPipe path (``_run_mediapipe``, ``estimate_hand`` without depth):
    ``mediapipe`` + ``opencv-python`` + ``numpy`` — installs cleanly into the
    MimicAnno uv venv.
  * UniDAC path (``_apply_metric_depth`` with real depth, ``_back_warp_depth``,
    ``_sample_depth_at_pixels``): also needs ``torch`` + the ``unidac`` package
    on ``PYTHONPATH``. Run those tests under ``conda activate unidac``.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np


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
class HandEstimate:
    """Per-hand metric output after UniDAC depth-based wrist back-projection."""
    is_right: bool
    joints_2d: np.ndarray         # (21, 2) pixel coords
    joints_3d: np.ndarray         # (21, 3) cam frame, metres
    cam_t: np.ndarray             # (3,)    cam frame, metres
    global_orient: np.ndarray     # (3, 3)  palm-axis-derived
    bbox: np.ndarray              # (4,)    xyxy pixels
    wrist_depth_m: Optional[float] = None
    depth_interpolated: bool = False
    pinch_distance_m: Optional[float] = None


# ---------------------------------------------------------------------------
# ERP -> input camera back-warp.

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
        raise NotImplementedError(f"preset {preset!r} not supported")
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
    a few hundred query pixels are needed (e.g. wrist + neighbours).

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
# Palm-axis wrist rotation.

def _palm_frame(joints_local: np.ndarray, is_right: bool) -> np.ndarray:
    """Derive a 3x3 wrist rotation from MediaPipe world landmarks.

    Column convention: R = [side | normal | forward], a proper rotation.
    """
    wrist  = joints_local[0]
    index  = joints_local[5]
    middle = joints_local[9]
    pinky  = joints_local[17]
    forward_raw = middle - wrist
    cross_raw   = np.cross(index - wrist, pinky - wrist)
    if (np.linalg.norm(cross_raw) < 1e-6
            or np.linalg.norm(forward_raw) < 1e-6):
        return np.eye(3, dtype=np.float32)
    normal = cross_raw / np.linalg.norm(cross_raw)
    if not is_right:
        normal = -normal
    forward = forward_raw / np.linalg.norm(forward_raw)
    side = np.cross(normal, forward)
    side_norm = np.linalg.norm(side)
    if side_norm < 1e-6:
        return np.eye(3, dtype=np.float32)
    side = side / side_norm
    forward = np.cross(side, normal)
    return np.stack([side, normal, forward], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# Wrist-pixel depth back-projection.

def _apply_metric_depth(
    raws: List["HandRaw"],
    depth_erp: np.ndarray,
    image_shape: Tuple[int, int],
) -> List[HandEstimate]:
    """Replace pseudo-metric cam_t with UniDAC metric depth at the wrist.

    For each detected hand:
    1. Sample UniDAC ERP depth at the wrist pixel (landmark 0) and its 8
       neighbours; take the median of finite positive values.
    2. Back-project (u, v, depth) through the equidistant fisheye model to get
       a metric cam_t.  UniDAC outputs euclid (ray) distance, so
       ``cam_t = depth * unit_ray``.
    3. Combine with the palm-axis rotation to express joints in the camera
       frame: ``joints_cam = joints_local @ R^T + cam_t``.

    When depth is unavailable (all 9 samples are NaN/0), cam_t falls back to
    zero and ``wrist_depth_m`` is ``None``.
    """
    if not raws:
        return []

    H, W = image_shape
    cam = _preset_a_cam_params(W, H)
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]

    # 3x3 neighbourhood offsets for robust wrist depth sampling.
    _offsets = np.array(
        [[du, dv] for du in (-1, 0, 1) for dv in (-1, 0, 1)],
        dtype=np.float32,
    )

    results: List[HandEstimate] = []
    for raw in raws:
        wrist_uv = raw.joints_2d[0]  # landmark 0 = wrist
        if np.any(np.isnan(wrist_uv)):
            wrist_depth: Optional[float] = None
        else:
            pts = wrist_uv[None, :] + _offsets          # (9, 2)
            samples = _sample_depth_at_pixels(depth_erp, pts, image_shape)
            finite_pos = samples[np.isfinite(samples) & (samples > 0)]
            wrist_depth = float(np.median(finite_pos)) if finite_pos.size > 0 else None

        interpolated = False
        if wrist_depth is not None:
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
            cam_t = np.array(
                [rx * wrist_depth, ry * wrist_depth, rz * wrist_depth],
                dtype=np.float32,
            )
        else:
            cam_t = np.zeros(3, dtype=np.float32)

        R = _palm_frame(raw.joints_local, raw.is_right)
        joints_cam = (raw.joints_local @ R.T) + cam_t
        pinch = float(np.linalg.norm(raw.joints_local[4] - raw.joints_local[8]))
        results.append(HandEstimate(
            is_right=raw.is_right,
            joints_2d=raw.joints_2d,
            joints_3d=joints_cam.astype(np.float32),
            cam_t=cam_t.astype(np.float32),
            global_orient=R,
            bbox=raw.bbox,
            wrist_depth_m=wrist_depth,
            depth_interpolated=interpolated,
            pinch_distance_m=pinch,
        ))

    return results


# ---------------------------------------------------------------------------
# Top-level API.

def _passthrough_estimate(raw: "HandRaw") -> HandEstimate:
    """Wrap a HandRaw as a HandEstimate with no depth correction."""
    R = _palm_frame(raw.joints_local, raw.is_right)
    joints_cam = raw.joints_local @ R.T  # cam_t = 0
    pinch = float(np.linalg.norm(raw.joints_local[4] - raw.joints_local[8]))
    return HandEstimate(
        is_right=raw.is_right,
        joints_2d=raw.joints_2d,
        joints_3d=joints_cam.astype(np.float32),
        cam_t=np.zeros(3, dtype=np.float32),
        global_orient=R,
        bbox=raw.bbox,
        wrist_depth_m=None,
        depth_interpolated=False,
        pinch_distance_m=pinch,
    )


_DEFAULT_TS_COUNTER = [0]


def estimate_hand(
    image: np.ndarray,
    depth: np.ndarray | None = None,
    *,
    return_intermediate: bool = False,
    timestamp_ms: int | None = None,
) -> list[HandEstimate] | tuple[list[HandEstimate], list["HandRaw"]]:
    """Top-level API: BGR uint8 image (+ optional UniDAC depth) -> metric hands.

    Args:
        image: ``(H, W, 3)`` uint8 BGR frame (``cv2.imread`` convention).
        depth: optional ``(H_erp, W_erp)`` float32 UniDAC depth in metres
            (Preset A: ``(512, 704)``). When ``None`` the returned
            :class:`HandEstimate` carries ``cam_t = 0`` and ``wrist_depth_m =
            None`` (palm-axis rotation is still produced).
        return_intermediate: if ``True`` return ``(estimates, raws)``;
            otherwise return only the ``list[HandEstimate]``.
        timestamp_ms: monotonically-increasing video timestamp passed to
            MediaPipe VIDEO mode. ``None`` (the default) uses an internal
            auto-incrementing counter so single-frame ad-hoc calls work
            without the caller managing timestamps. Production runners
            (Pass 1 in ``scripts/run_hand_estimation.py``) should pass an
            explicit ``int(frame_idx * 1000 / fps)`` for true temporal
            consistency.

    Returns:
        ``list[HandEstimate]`` (empty if no hands detected), or
        ``(list[HandEstimate], list[HandRaw])`` when
        ``return_intermediate=True``.
    """
    if timestamp_ms is None:
        _DEFAULT_TS_COUNTER[0] += 100
        timestamp_ms = _DEFAULT_TS_COUNTER[0]
    raws = _run_mediapipe(image, timestamp_ms=int(timestamp_ms))
    if not raws:
        estimates: list[HandEstimate] = []
    elif depth is not None:
        estimates = _apply_metric_depth(raws, depth, image.shape[:2])
    else:
        estimates = [_passthrough_estimate(r) for r in raws]
    if return_intermediate:
        return estimates, raws
    return estimates


# ---------------------------------------------------------------------------
# MediaPipe Tasks API backend
# ---------------------------------------------------------------------------

@dataclass
class HandRaw:
    """Per-hand raw output from MediaPipe HandLandmarker (pre-depth-fusion)."""
    is_right: bool
    joints_2d: np.ndarray      # (21, 2) float32 pixel coords
    joints_local: np.ndarray   # (21, 3) float32 metres, wrist-centred
    bbox: np.ndarray           # (4,)    float32 xyxy
    score: float               # MediaPipe handedness confidence


_MP_LANDMARKER = None

# Environment variable that lets production / air-gapped deployments point at
# a pre-fetched .task asset. See scripts/setup_envs.sh --weights and README
# (Axis B → Offline / air-gapped deployment).
_MP_HAND_LANDMARKER_ENV = "MIMICANNO_HAND_LANDMARKER_PATH"

# URL pinned to the /1/ revision (was /latest/). MediaPipe Solutions is in
# Preview and Google can rotate /latest/ without notice; pinning to an
# explicit revision freezes the model bytes for reproducibility.
_MP_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

# Acceptable size window for the float16 hand_landmarker.task asset (bytes).
# The current released file is ~7.6 MB; allow some headroom for future versions.
_MP_MODEL_SIZE_MIN = 5 * 1024 * 1024
_MP_MODEL_SIZE_MAX = 20 * 1024 * 1024


def _resolve_model_path() -> Path:
    """Resolve the MediaPipe HandLandmarker .task asset, downloading if needed.

    Resolution order:

    1. Environment variable ``MIMICANNO_HAND_LANDMARKER_PATH`` — if set, must
       point at an existing file. Intended for production / air-gapped
       deployments that pre-fetch the model with
       ``scripts/setup_envs.sh --weights``.
    2. User cache ``~/.cache/mimicanno/hand_landmarker.task`` — if present
       AND size-verified.
    3. Network download from the pinned URL into the user cache, with atomic
       write + flock + size verify (see ``_download_and_cache_model``).

    Raises ``FileNotFoundError`` if the env-var path is set but does not
    exist; raises ``RuntimeError`` (from the download path) if network
    fetch fails or the bytes are unexpected.
    """
    env = os.environ.get(_MP_HAND_LANDMARKER_ENV)
    if env:
        p = Path(env)
        if not p.is_file():
            raise FileNotFoundError(
                f"{_MP_HAND_LANDMARKER_ENV} points to a non-existent file: {p}"
            )
        return p
    return _download_and_cache_model()


def _download_and_cache_model() -> Path:
    """Locate or atomically download the MediaPipe HandLandmarker .task asset.

    Cached at ``~/.cache/mimicanno/hand_landmarker.task``. The download is:
    - **atomic**: writes to ``<asset>.tmp.<pid>`` first, then ``os.replace`` to
      the final name. A killed process never leaves a partially written
      ``.task`` file in place.
    - **size-verified**: an asset whose size falls outside
      [``_MP_MODEL_SIZE_MIN``, ``_MP_MODEL_SIZE_MAX``] bytes is treated as
      corrupted and re-downloaded (with the bad file removed first).
    - **concurrent-safe**: a sibling ``<asset>.lock`` file is ``fcntl.flock``-ed
      for the duration of the download/verify, so pytest-xdist workers or
      multiple processes contend safely.

    Subsequent calls hit the cache. First-run download is ~10 MB.
    """
    import fcntl
    import urllib.request

    cache_dir = Path.home() / ".cache" / "mimicanno"
    cache_dir.mkdir(parents=True, exist_ok=True)
    asset = cache_dir / "hand_landmarker.task"
    lock_path = cache_dir / "hand_landmarker.task.lock"

    def _size_ok(p: Path) -> bool:
        try:
            n = p.stat().st_size
        except OSError:
            return False
        return _MP_MODEL_SIZE_MIN <= n <= _MP_MODEL_SIZE_MAX

    # Fast path: cached and well-sized.
    if asset.exists() and _size_ok(asset):
        return asset

    # Slow path under exclusive lock.
    with open(lock_path, "w") as lock_fp:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
        # Re-check after acquiring the lock: another process may have just
        # finished downloading.
        if asset.exists() and _size_ok(asset):
            return asset

        # Clear a corrupt or wrong-sized file before retrying.
        if asset.exists():
            asset.unlink()

        tmp_path = cache_dir / f"hand_landmarker.task.tmp.{os.getpid()}"
        try:
            try:
                urllib.request.urlretrieve(_MP_MODEL_URL, tmp_path)
            except Exception as exc:
                raise RuntimeError(
                    f"MediaPipe model download failed from {_MP_MODEL_URL}: "
                    f"{exc!r}.\n"
                    f"\n"
                    f"Resolution order used by _resolve_model_path:\n"
                    f"  1. {_MP_HAND_LANDMARKER_ENV} env var (if set)\n"
                    f"  2. ~/.cache/mimicanno/hand_landmarker.task (if present)\n"
                    f"  3. download from the pinned URL (this step just failed)\n"
                    f"\n"
                    f"If you are in an air-gapped environment, pre-fetch the "
                    f"file on a host with network access via "
                    f"scripts/setup_envs.sh --weights and set the environment "
                    f"variable {_MP_HAND_LANDMARKER_ENV} to its path; that "
                    f"short-circuits both the cache lookup and the URL "
                    f"download. See the README (Axis B → Offline / air-gapped "
                    f"deployment) for details. MediaPipe Solutions is in "
                    f"Preview, so model URLs may change; see "
                    f"https://ai.google.dev/edge/mediapipe/legal/tos."
                ) from exc
            if not _size_ok(tmp_path):
                size = tmp_path.stat().st_size
                raise RuntimeError(
                    f"Downloaded hand_landmarker.task has unexpected size "
                    f"({size} bytes); expected "
                    f"{_MP_MODEL_SIZE_MIN}..{_MP_MODEL_SIZE_MAX}. "
                    f"URL: {_MP_MODEL_URL}"
                )
            os.replace(tmp_path, asset)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    return asset


_DELEGATE_ENV = "MIMICANNO_MEDIAPIPE_DELEGATE"


def _resolve_delegate():
    """Return the MediaPipe BaseOptions.Delegate honouring the env override.

    Default is GPU; set ``MIMICANNO_MEDIAPIPE_DELEGATE=CPU`` to fall back
    (intended for OpenGL-less hosts and the WSL/macOS hand-pipeline-on-CPU
    development path). The value comparison is case-insensitive.
    """
    from mediapipe.tasks.python.core.base_options import BaseOptions

    raw = os.environ.get(_DELEGATE_ENV, "GPU").upper()
    if raw == "CPU":
        return BaseOptions.Delegate.CPU
    return BaseOptions.Delegate.GPU


def _get_mediapipe_hands():
    """Lazy MediaPipe HandLandmarker (single-process, VIDEO mode).

    VIDEO mode requires monotonically-increasing ``timestamp_ms`` values
    on every ``detect_for_video`` call against this instance. The pipeline
    iterates the input video sequentially (Pass 1 in
    ``scripts/run_hand_estimation.py``), so monotonicity is naturally
    satisfied; tests that exercise multiple frames must use ascending
    timestamps too. See the conftest fixture
    ``_reset_mediapipe_landmarker_per_test`` for the per-test reset trick.
    """
    global _MP_LANDMARKER
    if _MP_LANDMARKER is None:
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
            VisionTaskRunningMode,
        )
        from mediapipe.tasks.python.vision.hand_landmarker import (
            HandLandmarker,
            HandLandmarkerOptions,
        )
        options = HandLandmarkerOptions(
            base_options=BaseOptions(
                model_asset_path=str(_resolve_model_path()),
                delegate=_resolve_delegate(),
            ),
            running_mode=VisionTaskRunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        _MP_LANDMARKER = HandLandmarker.create_from_options(options)
    return _MP_LANDMARKER


def _run_mediapipe(image: np.ndarray, timestamp_ms: int) -> list[HandRaw]:
    """Run MediaPipe HandLandmarker on a single BGR uint8 image (VIDEO mode).

    Uses the MediaPipe Tasks API (``HandLandmarker``) in VIDEO running
    mode. VIDEO mode adds temporal context across frames — the model's
    per-frame palm detector skips re-running when an existing track is
    confident enough — and stabilises the handedness classifier across
    short flips (motion blur, momentary occlusion). The legacy
    ``mediapipe.solutions.hands.Hands`` module was removed in mediapipe
    0.10.x and is not available.

    Args:
        image: (H, W, 3) uint8 BGR (cv2.imread convention).
        timestamp_ms: monotonically-increasing presentation timestamp in
            milliseconds. MediaPipe rejects out-of-order timestamps for
            the same detector instance. Typical production value:
            ``int(round(frame_idx * 1000.0 / fps))``. Tests get a fresh
            detector per case (see ``_reset_mediapipe_landmarker_per_test``)
            so any non-negative monotonic sequence works in isolation.

    Returns:
        One HandRaw per detected hand, empty list if nothing detected.

    Raises:
        ValueError: image dtype not uint8 or shape not (H, W, 3).
    """
    if image.dtype != np.uint8:
        raise ValueError(f"image must be uint8, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"image must be HxWx3 BGR, got shape {image.shape}")

    import cv2 as _cv2
    import mediapipe as mp
    rgb = _cv2.cvtColor(image, _cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    H, W = image.shape[:2]

    result = _get_mediapipe_hands().detect_for_video(mp_image, int(timestamp_ms))
    if not result.hand_landmarks:
        return []

    raws: list[HandRaw] = []
    n = len(result.hand_landmarks)
    for i in range(n):
        lm = result.hand_landmarks[i]
        wl = result.hand_world_landmarks[i]
        hd = result.handedness[i][0]  # top category

        joints_2d = np.array(
            [[p.x * W, p.y * H] for p in lm], dtype=np.float32
        )
        joints_local = np.array(
            [[p.x, p.y, p.z] for p in wl], dtype=np.float32
        )
        xs, ys = joints_2d[:, 0], joints_2d[:, 1]
        bbox = np.array([xs.min(), ys.min(), xs.max(), ys.max()],
                        dtype=np.float32)
        raws.append(HandRaw(
            is_right=(hd.category_name == "Right"),
            joints_2d=joints_2d,
            joints_local=joints_local,
            bbox=bbox,
            score=float(hd.score),
        ))
    return raws
