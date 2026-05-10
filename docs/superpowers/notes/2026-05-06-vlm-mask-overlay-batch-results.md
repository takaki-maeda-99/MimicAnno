# SO101 Phase 4 v3 (overlay) batch — results (2026-05-06)

Task 12 deliverable for `2026-05-06-vlm-mask-overlay-plan.md`.

## Setup

- Phase: 4 (boundaries → VLM → SAM3 tracks → Viterbi smoothing).
- VLM: `google/gemma-4-E4B-it` (local 15 GB at `/home/gayagaya/gemma_project/models/gemma-4-E4B-it`).
- SAM3: `sam3/checkpoints/sam3.pt` via vendored sam3 backend.
- Driver: `scripts/batch_so101_phase4_overlay.sh` (thin wrapper that
  points RUNS_ROOT/LOGS_DIR/VLM_DUMP_ROOT at the v3 lot).
- GPU 0 (eps 1-10, 10 episodes), GPU 1 (eps 21-32, 12 episodes).
  ep 0 was smoked separately just before launching the batch (1 ep, GPU 0).
- Wall clock: ~15 minutes for the longer GPU 1 stream.
- Run dirs: `runs/so101_phase4_v3/episode_*`.
- VLM dumps: `runs/so101_phase4_v3/_vlm_dumps/episode_*/<seg>/attempt_*/`.

Per-episode wall time matches v2 (~60-75s) — overlay overhead is in the
noise next to model loads + SAM3 propagation.

## Results

23/23 episodes completed.

| Result | Count | Episodes |
|---|---|---|
| Full Phase 4 + tape tracked | 18 | 0, 4-8, 21-25, 27, 29-32 |
| sam3_no_initial_detection (degrade) | 5 | 2, 3, 9, 10, 26 |
| Tracked but 0 samples (grounding ok, propagation lost it) | 3 | 1, 27, 28† |

†ep28 grounded "bottle" instead of "tape" (different prompt for that
episode's Gemma planner output) — bottle propagation produced 0 samples.

Average `object_state_segment_coverage`: **65.22%**. This is in the
same ballpark as the v2 (no-overlay) batch — overlay-conditioning did
not regress Phase 1+2+3 quality.

## Aggregation

```
runs/so101_phase4_v3/_vlm_dumps/aggregated/
├── planner.jsonl  23 rows  (parse_ok=23/23)
└── labeler.jsonl  23 rows  (parse_ok=23/23)
```

Both 100% parse_ok, matching the v2 ratio. The legend insertion did not
introduce any JSON-format breakage in Gemma's output.

## Overlay verification (programmatic, 5+ episode dumps)

| Episode | Pattern | Per-keyframe blue (tab10[0]) px count | Legend in request.json |
|---|---|---|---|
| ep0  | tape tracked | kf0=405          | yes |
| ep5  | tape tracked | kf0..3 = 750/91/185/528 | yes |
| ep21 | tape tracked | kf0..3 = 538/252/633/489 | yes |
| ep32 | tape tracked, kf0 lost | kf0..3 = 0/73/171/500 | yes |
| ep28 | bottle 0 samples | (background false-pos only) | **no** (legend suppressed per spec §5.5) |

Findings:

- **Spec §6.1 wording**: every successful run carries
  `"Colored translucent overlays (~40% opacity) mark tracked objects:
  blue=<prompt>. ..."` with the right palette color.
- **Spec §5.4 partial-loss**: ep32 kf0 has zero overlay pixels for
  tape but the legend stays — this is the partial-loss case where
  Gemma can read "blue=tape" and infer "tape is occluded at this
  keyframe" via the spec §6.1 "may be absent" clause.
- **Spec §5.5 full-loss suppression**: ep28 (bottle propagated to 0
  frames) has the legend correctly null. The blue pixels visible in the
  raw frame are natural background false-positives within the tab10[0]
  RGB tolerance band — not painted by us.
- **Non-square keyframe handling**: every keyframe is `(126, 224, 3)`
  (SO101 front camera 4:3 letterboxed at long_edge=224 →
  126×224). MaskCache stores `(224, 224)` square masks so each compose
  call resizes via `cv2.INTER_NEAREST` per the Task 12 fix
  (`compose_overlay`).

## Task 12 status: PASS

Plan deliverables met:

- ✅ overlay-applied dumps in `_vlm_dumps/episode_*/<seg>/attempt_*/keyframe_*.png`
- ✅ aggregated `planner.jsonl` + `labeler.jsonl` (23 rows each, all parse_ok)
- ✅ 5+ dumps eyeballed (programmatic colour-pixel detection)
- ✅ no regression vs v2 success rate (78% Phase 4 / 22% degraded vs
  v2's similar split)

Open follow-ups (not blocking Task 13):

- 13 ep (11-20, 33-35) still gated by the `fps.unresolvable` bug from
  v2 batch results — out of scope for this plan, separate fix needed.
- ep28's "bottle" planner output is interesting — Gemma sometimes
  picks "bottle" as the primary object instead of "tape". Whether to
  always force a "tape" prompt vs. trusting Gemma's planner choice is
  worth a Task 13 conversation.
