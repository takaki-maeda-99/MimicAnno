# vlm-mask-overlay manual smoke run command (Task 10)

Spec §9.3 cases (mask shape / pairwise overlap <1% / prompt centroid >10px)
live in `tests/test_phase3_real_sam3_smoke.py` alongside the existing Phase 3
real-Gemma smoke. They are env-gated (skip in CI) so they don't require GPU /
weights for the regular suite.

## Run command (SO101 ep0)

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  MIMICANNO_RUN_SAM3_SMOKE=1 \
  MIMICANNO_SAM3_CHECKPOINT=/home/gayagaya/MimicAnno/sam3/checkpoints/sam3.pt \
  MIMICANNO_REAL_VIDEO=/home/gayagaya/MimicAnno/data/SO101/videos/chunk-000/observation.images.front/episode_000000.mp4 \
  MIMICANNO_REAL_PARQUET=/home/gayagaya/MimicAnno/data/SO101/data/chunk-000/episode_000000.parquet \
  uv run pytest tests/test_phase3_real_sam3_smoke.py \
    -k "mask_shape or overlap or centroid" \
    -v -s
```

The full Phase 3 case (`test_phase3_real_sam3_on_lerobot_ep0`) is **not**
included in `-k` here because it loads Gemma weights and runs the whole
CLI pipeline. Run it separately when the Gemma 4 weights are present.

## Result on 2026-05-06 (SO101 ep0)

Prompts: default `tape,robot arm` (override via
`MIMICANNO_OVERLAY_SMOKE_PROMPTS`).

- **mask shape**: PASS. Every cached mask matches `(image_size_px,
  image_size_px) = (256, 256)` and `dtype.kind == "b"`. ≥1 non-empty
  mask per episode.
- **pairwise overlap**: PASS. `max_ratio=0.000000`,
  `frames_with_overlap=0` — well under the 1% spec threshold (§9.3 case
  2). Tightening to `<0.1%` would still hold; revisit per spec §12.1
  after the Task 12 batch run logs land.
- **centroid distance**: PASS. `max prompt-centroid distance = 114.01px`
  in (256, 256) frame — well over the 10px threshold (§9.3 case 3).

## Prompt-tuning notes

`bottle` and `robot gripper` (the spec §9.3 worked-example prompts) do
not ground on SO101 ep0 frame 0; the smoke fixture skips the multi-prompt
checks gracefully when only one prompt grounds. The module-scoped
fixture re-uses one SAM3 load across all three smokes, so the manual
run is dominated by the single ~12s load + ~25s propagation.
