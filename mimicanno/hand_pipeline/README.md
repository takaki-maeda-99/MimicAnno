# mimicanno/hand_pipeline

MediaPipe Hand Landmarker + UniDAC depth fusion for metric hand pose estimation from fisheye video (GoPro Hero 11 Max Lens Mod, 2704x1520, OPENCV_FISHEYE equidistant model).

The module provides a single top-level function, `estimate_hand()`, that takes a raw fisheye frame and a precomputed UniDAC depth map and returns per-hand metric pose estimates.

See also: [Hand Pipeline section in README.ja.md](../../README.ja.md#hand-pipeline-phase-a--b) for the full pipeline overview in Japanese.

---

## HandEstimate dataclass

```python
@dataclass
class HandEstimate:
    is_right: bool                       # True = right hand
    global_orient: np.ndarray            # (3, 3)     float32  wrist rotation matrix (palm-axis derived)
    joints_3d: np.ndarray                # (21, 3)    float32  joint positions in camera frame [m]
    joints_2d: np.ndarray                # (21, 2)    float32  joint projections in image pixels
    cam_t: np.ndarray                    # (3,)       float32  wrist position in camera frame [m]
    bbox: np.ndarray                     # (4,)       float32  xyxy detection bbox [px]
    wrist_depth_m: Optional[float]       # UniDAC euclid distance at wrist [m]; None if unavailable
    depth_interpolated: bool             # True when wrist_depth_m was gap-filled temporally
    depth_ok: bool                       # True when wrist_depth_m is from UniDAC (not fallback)
    pinch_distance_m: Optional[float]    # |thumb_tip - index_tip| in local frame [m]
```

All 3-D coordinates are in the camera frame (X right, Y down, Z forward).

`cam_t` is the metric translation of the wrist (joint 0). When `wrist_depth_m` is not None it is derived from UniDAC fisheye back-projection; otherwise it falls back to a pseudo-metric estimate.

`pinch_distance_m` is computed in the local frame (camera-translation-independent) and is therefore always valid when a hand is detected, even without depth.

### Hand joint indices

| Index | Joint |
|-------|-------|
| 0 | wrist |
| 4 | thumb tip |
| 8 | index finger tip |
| 12 | middle finger tip |
| 16 | ring finger tip |
| 20 | pinky tip |

---

## estimate_hand() API

```python
from mimicanno.hand_pipeline.pipeline import estimate_hand

estimates = estimate_hand(image, depth)
```

**Arguments**

| Arg | Type | Description |
|-----|------|-------------|
| `image` | `np.ndarray (H, W, 3)` uint8 BGR | Fisheye frame (`cv2.imread` convention) |
| `depth` | `np.ndarray (H_erp, W_erp)` float32 | UniDAC Preset A output — shape `(512, 704)`, euclid distance in metres |
| `refine` | `bool` (default `True`) | Apply UniDAC wrist-depth back-projection. Set `False` for debugging raw landmark output alone. |

**Returns** `list[HandEstimate]` — one entry per detected hand. Empty if no hands found. Hands with no depth coverage are included with `wrist_depth_m=None`.

**Minimal example**

```python
import cv2
import numpy as np
from mimicanno.hand_pipeline.pipeline import estimate_hand

image = cv2.imread("frame.jpg")
depth = np.load("depth/frames/frame_000060.npy")   # (512, 704) float32

for h in estimate_hand(image, depth):
    side = "right" if h.is_right else "left"
    depth_str = f"{h.wrist_depth_m:.3f} m" if h.wrist_depth_m else "no depth"
    print(f"{side}: wrist at {h.cam_t} | depth={depth_str} | pinch={h.pinch_distance_m:.4f} m")
```

**Environment requirement**

Hand estimation runs in the main uv-managed environment:

```bash
uv run python scripts/run_hand_estimation.py ...
```

---

## Key design decisions

### Wrist back-projection instead of scale fusion

Earlier approach (`_fuse`, now deprecated): compute one scale factor per image as `median(UniDAC_z) / median(backend_z)` across all joints of all detected hands, then multiply `cam_t` by that scalar. This fails when the hand occupies a small fraction of the depth map and the image-level median is dominated by background.

Current approach (`_apply_metric_depth`): sample UniDAC euclid depth at the wrist pixel (joint 0) and its 3x3 neighbourhood, take the median, then back-project directly:

```
cam_t = depth_euclid * unit_ray(wrist_pixel)
```

This gives a metric wrist position that is independent of the backend's scale heuristic. Pose parameters from the landmark backend are kept unchanged.

### Euclid distance, not Z-depth

UniDAC outputs ray distance (euclid distance from the camera centre to the surface point), not the Z component of the camera-frame point. The back-projection therefore uses:

```
cam_t = depth * unit_ray
```

not `cam_t.z = depth`. Using Z-depth for a fisheye lens would underestimate the distance for off-centre pixels.

---

## Internal modules

| Symbol | Role |
|--------|------|
| `HandRaw` | Per-hand landmark output before depth correction |
| `_run_mediapipe()` | Runs MediaPipe Hand Landmarker on a single BGR image, returns `list[HandRaw]` |
| `_apply_metric_depth()` | Applies wrist back-projection, returns `list[HandEstimate]` |
| `_back_warp_depth()` | Inverse-projects ERP depth onto the fisheye pixel grid (used by viz scripts) |
| `_sample_depth_at_pixels()` | Fast forward-projection of N pixels into ERP depth without full grid warp |
| `_fuse()` | Deprecated scale-fusion implementation; kept for reference |
