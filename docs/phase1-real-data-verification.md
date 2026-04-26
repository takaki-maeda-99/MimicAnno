# Phase 1 real-data verification (2026-04-26)

End-to-end verification of the Phase 1 pipeline against a real LeRobot v3.0 episode.
Plan 1's "Done" claim was based on synthetic 150-frame fixtures only; this run is
the first time the full CLI was driven against a recorded episode.

## Setup

| Item | Value |
|---|---|
| Dataset | `lerobot/svla_so100_pickplace` (HF Hub cache) |
| Episode | 0 (454 frames, 15.13 s, 30 fps) |
| Task text | "Pick up the cube and place it in the box." |
| Robot adapter | `so100` (gripper at last index of `observation.state`) |
| Extractor | `tools/extract_lerobot_episode.py` (chunk → per-episode parquet+mp4) |
| Output | `runs/episode_000__473884a1bb5e/` (run_hash short = `473884a1bb5e`) |

Invocation:

```
python -m mimicanno.cli annotate \
  --video <episode_000.mp4> \
  --parquet <episode_000.parquet> \
  --task "Pick up the cube and place it in the box." \
  --robot so100 \
  --runs-root <runs root> \
  --link-video
```

(Must be run with the project's `.venv/bin/python` — see Finding 2.)

## ✅ What worked

- LeRobot v3.0 chunked parquet+mp4 ingestion via the extractor + `so100` adapter.
- Smoothing → 4 detectors → integrated score → bracketing → publish transaction.
- All four artifacts (`manifest.json`, `annotation.json`, `boundaries.json`, `signals.json`)
  written to a new `<episode_id>__<run_hash[:12]>/` directory.
- `runs/index.json` upserted with the run entry; `manifest_url` resolves correctly.
- `--link-video` produced a symlink instead of a copy as designed.
- `run_hash` / `config_hash` / `input_hash` derivation matches spec §4.1.

## ⚠ Findings

### Finding 1 — Default `gripper_delta=0.30` is mis-tuned for real trajectories

The svla cube-pickup episode contains an obvious gripper close (frames ~95–105) and
open (frames ~265–325). Both are clearly visible in the smoothed gripper signal
(0.345 → 1.0 → 0.41). But the per-frame |Δgripper| **never exceeds 0.16** because
the transition is spread over ~10 frames and further attenuated by the Gaussian
smoothing applied in `signals.py`.

The `detect_gripper_transition` default threshold is `0.30`, so on this episode the
detector returns **zero events** and `boundaries.json` ends up with
`candidates: []`.

Lowering the threshold programmatically:

| `delta_threshold` | events |
|---|---|
| 0.30 (default) | 0 |
| 0.15 | 1 (frame 101 — the actual close) |
| 0.10 | 4 (close + open spread across 3 over-split frames) |
| 0.05 | 4 (no further sensitivity gain) |

`0.15` is the sweet spot for this episode. The synthetic fixtures used during
Phase 1 development are step-function gripper signals (Δ ≈ 1.0 in a single frame),
which is why threshold `0.30` passed the tests but fails on real data.

**Action items:**
- Revisit default thresholds against a few more real episodes before declaring
  Phase 1 numerically tuned (the plumbing is fine; the calibration is not).
- The CLI does not expose detector thresholds — only `--score-threshold`
  (post-aggregation) and `--merge-window-sec`. `BoundaryConfig.thresholds` is read
  by `pipeline.py` but there's no path from the CLI to populate it. Add either a
  `--boundary-config <yaml>` flag or per-detector flags so users can override
  without editing code.

### Finding 2 — `pyproject.toml` requires Python ≥3.11, but the system default is 3.10

`mimicanno/publish.py` uses `datetime.UTC` (added in 3.11). On Python 3.10 the CLI
crashes immediately with `module 'datetime' has no attribute 'UTC'`. The project
venv (`.venv/bin/python` = 3.11.14) works, but invoking via the system `python`
silently picks up 3.10 and fails. There is no startup-time Python version guard.

**Action items (low priority):**
- Either add a runtime check at CLI entry (`sys.version_info >= (3, 11)`) with a
  friendly message, or replace `datetime.UTC` with `datetime.timezone.utc` so the
  code runs on 3.10 too. The latter has no downside.

### Finding 3 — Real LeRobot v3.0 datasets exist in two state layouts (informational only)

`io_parquet.REQUIRED_COLUMNS` requires a flat `observation.state` column (a
list-of-floats per row). The svla_so100 dataset uses this layout, so it works.
However other recordings (e.g. the local `MimicRec/datasets/SO101/`) use
dot-namespaced columns (`observation.state.joint_pos`, `observation.state.gripper_pos`,
…) and are rejected by the loader.

Per the user, the recording side (MimicRec) will conform to the flat layout going
forward, so this is **not an issue to fix in MimicAnno** — recorded as context
only, in case a future dataset trips on it.

## Reproducing

```
mkdir -p /tmp/mimicanno-real-verify/svla_ep0
python tools/extract_lerobot_episode.py \
  ~/.cache/huggingface/hub/datasets--lerobot--svla_so100_pickplace/snapshots/<sha>/ \
  0 /tmp/mimicanno-real-verify/svla_ep0 \
  --video-key observation.images.top

.venv/bin/python -m mimicanno.cli annotate \
  --video   /tmp/mimicanno-real-verify/svla_ep0/episode_000.mp4 \
  --parquet /tmp/mimicanno-real-verify/svla_ep0/episode_000.parquet \
  --task   "Pick up the cube and place it in the box." \
  --robot   so100 \
  --runs-root /tmp/mimicanno-real-verify/runs \
  --link-video
```

Expect: success exit, run dir + index entry created, `boundaries.json.candidates == []`
under default thresholds (Finding 1).
