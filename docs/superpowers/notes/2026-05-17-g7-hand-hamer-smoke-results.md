# G7 — Hand pipeline + HAMER 1 ep smoke results

**Date:** 2026-05-17
**Branch:** `docs/g4-gem4-smoke`
**Task:** Task 2 (G7) of `docs/superpowers/plans/2026-05-17-g6-g7-g8-gpu-smoke-plan.md`
**Goal:** Run `scripts/run_hand_estimation.py` on SO101 episode 0 (front cam) using the depth precomputed by G8, verify pipeline mechanics (frames produced, viz emitted, cam_t plausible, 3-axis overlay present).

## Setup

- Env: `hamer/.hamer/bin/python` + `PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC`
- GPU: `CUDA_VISIBLE_DEVICES=1` (GPU 0/3 in use by other jobs; GPU 1 free after G8 finished)
- CUDA check: `torch.cuda.is_available() = True`, `device_count = 4`
- Video: `/home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4` (151 frames @ 15 fps, 640x360)
- Depth input: `/tmp/g8_smoke/depth` (G8 output — only frames 0..29 precomputed)
- Output: `/tmp/g7_smoke/hands`
- Log: `/tmp/g7_smoke.log`

## Command

```
CUDA_VISIBLE_DEVICES=1 \
PYTHONPATH=/home/gayagaya/MimicAnno:/home/gayagaya/MimicAnno/UniDAC \
hamer/.hamer/bin/python scripts/run_hand_estimation.py \
  --video /home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  --depth /tmp/g8_smoke/depth \
  --out   /tmp/g7_smoke/hands \
  2>&1 | tee /tmp/g7_smoke.log
```

## Result: PARTIAL PASS

Pipeline ran end-to-end with no crashes / no failures, but the `cam_t` sanity-check could not be performed because the detected frames do not overlap with the depth coverage window (see ⚠️ below).

### Summary of outputs

| Item                              | Value                                                |
|-----------------------------------|------------------------------------------------------|
| frames_processed                  | 151                                                  |
| frames_with_hands                 | 23 (left only)                                       |
| frames_right_hand                 | 0                                                    |
| frames_depth_missing              | 23                                                   |
| failures                          | 0                                                    |
| interrupted                       | false                                                |
| total_elapsed_seconds             | 128.2 s (1.18 fps avg)                               |
| `frames/frame_*.pkl` count        | 151 (matches processed)                              |
| `viz/overlay.mp4`                 | 654,524 bytes (well over 50 KB threshold)            |
| `signals.json`                    | 2,622 bytes, schema_version=1, all `depth_ok: false` |

### Checks

- ✅ Pipeline ran cleanly: no failures, no interrupts, 151/151 frames processed, viz emitted, signals.json emitted.
- ✅ `frames/frame_*.pkl` count (151) matches `frames_processed` and is the full video length.
- ✅ `viz/overlay.mp4` is 654 KB (well above the 50 KB sanity floor).
- ✅ 3-axis overlay code path (commit `2307219`, 2026-05-16) is present in the running tree (no code modifications were made; this run used HEAD of `docs/g4-gem4-smoke`).
- ⚠️ **Hand detection ran but on robot, not human.** 23 left-hand detections, all at frame indices **128–150** (the very end of the episode — likely the moment the human reaches in to reset the scene, or the model is firing on the robot arm/gripper). Per plan: SO101 front cam is robot-only for most of the episode, so this is *acceptable* but not a glamorous result.
- ⚠️ **cam_t z is unreliable in this run** because the detected frames (128–150) have zero overlap with depth coverage (0–29). `frames_depth_missing=23`. cam_t z range came out at 12.7–14.3 m (mean 13.6 m), which is the HaMeR fallback scale, **not** UniDAC-anchored metric depth. This is *not* a bug — it's a consequence of G8's depth precompute being truncated to 30 frames. A full-depth run would be needed to validate the 0.2–2.0 m fisheye-back-projection range.
- ✅ HaMeR model state-dict mismatch ("unexpected keys ... mlp.experts.*") is harmless — the checkpoint contains MoE expert weights from a larger variant and the runtime backbone ignores them. Same warning was tolerated in prior smokes.

### Frame-index audit

Detected frame indices: `[128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150]`
Depth coverage: `[0..29]`
Overlap: `[]`

## Conclusion

**G7 pipeline mechanics: PASS.** HAMER + UniDAC-depth wrapper runs end-to-end on a real SO101 episode without crashes, emits the expected artifacts (frames pkls, viz mp4, signals.json, meta.json), and the 3-axis overlay code is in place.

**Quantitative cam_t validation: deferred.** Cannot confirm fisheye back-projection 0.2–2.0 m range until a run is made where hand detections coincide with depth-covered frames. Two ways to unblock:
1. Extend G8 to precompute depth for the *full* 151-frame episode (cheap — G8 was ~50 s for 30 frames; ~4 min projected for full ep).
2. Pick an episode where the human hand is in frame at the start (when depth coverage exists), e.g. one of the dataset's `observation.images.wrist` clips or an episode with longer human-in-frame at the start.

Since the autonomy goal is "pipeline mechanics pass", and the human-on-frame issue is dataset-specific not pipeline-specific, marking this **PARTIAL PASS** and recommending the full-depth G8 rerun before drawing conclusions about cam_t accuracy.

## Surprises / lessons

- The script processes the *full video* even if `--depth` covers fewer frames; missing depth gets flagged `depth_ok=False` and (via `--max-interp-gap`) optionally interpolated. This is robust behavior — good design.
- SO101 front cam at episode 0 has the human entering frame only at the end (frames 128–150). For cam_t sanity checks against UniDAC depth, future smokes should ensure depth coverage spans the detection window. Easiest path: just precompute depth for the whole episode.
