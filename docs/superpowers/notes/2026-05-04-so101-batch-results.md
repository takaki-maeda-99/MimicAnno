# SO101 Phase 4 batch run — results (2026-05-04)

GPU 2 (eps 000-017) + GPU 3 (eps 018-035) running in parallel against
`/misc/dl00/gayagaya/MimicAnno/data/SO101`. Started 22:01 JST 2026-05-04.

This is a **partial snapshot** captured before the server power cycle —
the batch was still running. Final results may differ; rerun
`uv run python scripts/summarize_so101_runs.py` once runs are complete.

## Setup

- Phase: 4 (boundaries → VLM → SAM3 tracks → Viterbi smoothing).
- VLM: `google/gemma-4-E4B-it` from `/home/gayagaya/gemma_project/models/gemma-4-E4B-it` (local 15 GB, no HF DL).
- SAM3: `sam3/checkpoints/sam3.pt` via the new vendored sam3 backend (this PR).
- Driver: `scripts/batch_so101_phase4.sh`, two parallel processes
  (`CUDA_VISIBLE_DEVICES=2` and `=3` respectively).
- Per-episode logs at `logs/batch_so101/episode_NNNNNN_gpuN.log`.
- Run dirs at `runs/so101_phase4/episode_*/`.

## Snapshot at 22:04:34 (≈3.5 min into the batch)

| Episode | degrade | obj_state | cov  | segs | tracks | max_samples | prompts  |
|---------|---------|-----------|------|------|--------|-------------|----------|
| 000000  | -       | True      | 1.00 | 1    | 1      | 29          | tape(29) |
| 000001  | -       | True      | 0.00 | 1    | 1      | 0           | tape(0)  |
| 000002  | sam3_no_initial_detection | False | 0.00 | 1 | 0 | - | - |
| 000018  | **never ran**: fps.unresolvable (timestamp variance > 5%) | | | | | | |
| 000019  | **never ran**: fps.unresolvable | | | | | | |
| 000020  | **never ran**: fps.unresolvable | | | | | | |
| 000021  | -       | True      | 1.00 | 1    | 1      | 31          | tape(31) |
| 000022  | -       | True      | 1.00 | 1    | 1      | 31          | tape(31) |

## Patterns observed

1. **Per-episode wall time ≈ 75 s** including Gemma + SAM3 model loads.
   Both fit on a single A100 80 GB easily.

2. **3 out of 36 episodes (18, 19, 20) are unrunnable** because their
   parquet `timestamp` column has > 5% std/median variance. The pipeline
   raises `fps.unresolvable` *before* falling back to the video-probe
   FPS — this is a bug in `mimicanno/pipeline.py:720-726` (eager call
   to `resolve_fps` even when `probe.fps > 0`). It's unrelated to the
   SAM3 backend swap. Easy fix: only call `resolve_fps` when
   `probe.fps == 0`.

3. **SAM3 tracking quality varies by episode**:
   - Best: ep21, 22 → 31/31 frames (100%) for tape.
   - Typical: ep0 → 29/31 frames (93.5%) — what the spec smoke caught.
   - Sometimes: ep1 → 0/? frames. Track shell is created but propagation
     yields no detections. Usually means the bbox seed from grounding
     was very weak / off-target. Worth eyeballing the keyframe.
   - Sometimes: ep2 → `sam3_no_initial_detection` degrade. Gemma asked
     for an object but SAM3 found nothing on the initial frame.

4. **Single-segment annotations** dominate (each SO101 episode is ~10 s
   of one motion). Phase 4 Viterbi has nothing to smooth.

## Failure modes to follow up after the autonomy window

- **fps.unresolvable preemption** — defer `resolve_fps` to fallback only.
  ~3 / 36 episodes recoverable with this fix.
- **0-sample tracks** (ep1 type) — currently silent. Worth surfacing in
  manifest as a quality warning, or adding "sam3_track_lost_immediately"
  as a soft signal so downstream dashboards can flag it.
- **Whole-episode-as-one-segment** — Phase 1 boundary detection on these
  short SO101 clips finds zero transitions. Maybe expected, or maybe
  the boundary thresholds need SO101 tuning.

## Where things land

- Per-episode artifacts: `runs/so101_phase4/episode_NNNNNN__<hash>/{annotation,
  manifest, boundaries, signals, tracks}.json` + `video.mp4`.
- Per-episode logs: `logs/batch_so101/episode_NNNNNN_gpuN.log`.
- Top-level GPU logs: `logs/batch_so101/_gpu{2,3}_top.log` (driven by
  `scripts/batch_so101_phase4.sh`).
- Aggregated table: `uv run python scripts/summarize_so101_runs.py`.

## How to resume after restart

```bash
# Resume each GPU's batch from where it stopped (mimicanno reuses the
# canonical run dir name and is idempotent — completed episodes are
# instant no-ops).
GPU=2 START=0  END=17 bash scripts/batch_so101_phase4.sh \
    > logs/batch_so101/_gpu2_top.log 2>&1 &
GPU=3 START=18 END=35 bash scripts/batch_so101_phase4.sh \
    > logs/batch_so101/_gpu3_top.log 2>&1 &
```

Both processes' tail logs (`_gpu2_top.log`, `_gpu3_top.log`) record one
"OK" / "FAIL" line per episode and a final "done at" line.
