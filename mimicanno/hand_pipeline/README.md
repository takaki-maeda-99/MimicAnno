# mimicanno/hand_pipeline

HaMeR + UniDAC depth fusion for metric hand pose estimation from fisheye video (GoPro Hero 11 Max Lens Mod, 2704x1520, OPENCV_FISHEYE equidistant model).

The module provides a single top-level function, `estimate_hand()`, that takes a raw fisheye frame and a precomputed UniDAC depth map and returns per-hand metric pose estimates.

See also: [Hand Pipeline section in README.ja.md](../../README.ja.md#hand-pipeline-phase-a--b) for the full pipeline overview in Japanese.

---

## HandEstimate dataclass

```python
@dataclass
class HandEstimate:
    is_right: bool                       # True = right hand
    betas: np.ndarray                    # (10,)      float32  MANO shape params
    global_orient: np.ndarray            # (3, 3)     float32  wrist rotation matrix
    hand_pose: np.ndarray                # (15, 3, 3) float32  finger joint rotation matrices
    cam_t: np.ndarray                    # (3,)       float32  wrist position in camera frame [m]
    vertices: np.ndarray                 # (778, 3)   float32  MANO mesh in camera frame [m]
    joints_3d: np.ndarray                # (21, 3)    float32  joint positions in camera frame [m]
    joints_2d: np.ndarray                # (21, 2)    float32  joint projections in image pixels (pinhole approx.)
    bbox: np.ndarray                     # (4,)       float32  xyxy detection bbox [px]
    wrist_depth_m: Optional[float]       # UniDAC euclid distance at wrist [m]; None if unavailable
    depth_interpolated: bool             # True when wrist_depth_m was gap-filled temporally
    pinch_distance_m: Optional[float]    # |thumb_tip - index_tip| in MANO local frame [m]
    scale_factor: Optional[float]        # deprecated; always None
    n_valid_samples: int                 # deprecated; always 0
```

All 3-D coordinates are in HaMeR's camera frame (X right, Y down, Z forward).

`cam_t` is the metric translation of the wrist (MANO joint 0). When `wrist_depth_m` is not None it is derived from UniDAC; otherwise it falls back to HaMeR's pseudo-metric estimate.

`pinch_distance_m` is computed in MANO local frame (camera-translation-independent) and is therefore always valid when a hand is detected, even without depth.

### MANO joint indices

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
| `refine` | `bool` (default `True`) | Apply UniDAC wrist-depth back-projection. Set `False` for debugging HaMeR output alone. |
| `return_intermediate` | `bool` (default `False`) | If `True`, return `(list[HandEstimate], list[HamerRaw])` |

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

Must run under the HaMeR venv with PYTHONPATH set to the repo and UniDAC roots:

```bash
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
    hamer/.hamer/bin/python your_script.py
```

---

## Key design decisions

### Wrist back-projection instead of scale fusion

Earlier approach (`_fuse`, now deprecated): compute one scale factor per image as `median(UniDAC_z) / median(HaMeR_z)` across all joints of all detected hands, then multiply `cam_t` by that scalar. This fails when the hand occupies a small fraction of the depth map and the image-level median is dominated by background.

Current approach (`_apply_metric_depth`): sample UniDAC euclid depth at the wrist pixel (MANO joint 0) and its 3x3 neighbourhood, take the median, then back-project directly:

```
cam_t = depth_euclid * unit_ray(wrist_pixel)
```

This gives a metric wrist position that is independent of HaMeR's scale heuristic. Shape and pose parameters from HaMeR are kept unchanged.

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
| `HamerRaw` | Per-hand HaMeR output before depth correction |
| `_run_hamer()` | Runs HaMeR on a single BGR image, returns `list[HamerRaw]` |
| `_apply_metric_depth()` | Applies wrist back-projection, returns `list[HandEstimate]` |
| `_back_warp_depth()` | Inverse-projects ERP depth onto the fisheye pixel grid (used by viz scripts) |
| `_sample_depth_at_pixels()` | Fast forward-projection of N pixels into ERP depth without full grid warp |
| `_fuse()` | Deprecated scale-fusion implementation; kept for reference |
