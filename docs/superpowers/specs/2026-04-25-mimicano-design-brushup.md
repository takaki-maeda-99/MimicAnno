# MimicAno Design Brush-up (2026-04-25)

> Status: **DRAFT — pending Codex full-spec review and user review.**
> This document is intended to **supersede `docs/design.md`** once approved.
> Brush-up summary: locks in phasing, schema, contracts, and the Phase 1 viewer architecture so implementation work can start without re-litigating decisions.

## 0. What changed vs. `docs/design.md`

| Area | Old design.md | This brush-up |
|------|---------------|---------------|
| Phase order | Implicit; UI was Step 6 | Explicit 5-phase plan (B'); read-only viewer is **Phase 1**, edit UI is **Phase 5** |
| Boundary detection | "Step1 signals, Step2 SAM3 refines" | **Single integrated weighted score**; Step1 (signals) and Step2 (object) are sources, not stages |
| `failure_recovery` | One of the labels | **Removed as a phase**; replaced with `failure_flags: list[str]` on segments whose `phase` is the underlying activity |
| Schema | Minimal `SubtaskSegment` | Versioned schema with `episode_id`, `segment_id`, `label_source`, `reviewed`, `reviewer_id`, `label_version`, `config_hash`, `model_versions`, `boundary_source: list[str]`, `failure_flags: list[str]`, `object_track_ids` |
| SAM3 prompt input | Task name only | **Task name + initial frame** (text-only fails on "it" / "the object") |
| SAM3 failure | Unspecified | **Documented degrade path** to robot-state-only with `object_state_unavailable=true` |
| Confidence | `confidence: float` (single) | **Three levels**: `vlm_confidence`, `boundary_confidence`, `overall_confidence` |
| Forbidden transitions | Hard rules | **Phase 1**: hard rules. **Phase 4**: promoted to Viterbi/penalty |
| Viewer | "Phase 6 review UI" all-in-one | **Phase 1** read-only viewer (verify boundary candidates) → **Phase 5** edit UI |
| Output format | Implied parquet | **Sidecar JSON in a "run directory"** with versioned `manifest.json` contract |
| Boundary references | `boundary_source: list[str]` flat | **Per-edge `BoundaryRef`** (`start_boundary` / `end_boundary`) with candidate ID and score; `boundary_confidence = min(start, end)` |
| Schema versioning | Implicit | **Per-artifact independent semver**; `manifest.json` declares `compat` block (§6.6) |
| Reserved phases | Not specified | **`unlabeled` / `unknown`** are reserved phase strings, never in label YAMLs (§8.4) |
| Run dir replacement | Not specified | **POSIX two-rename atomic protocol** (§6.5); Windows acknowledged non-atomic |
| Index update | Not specified | **`runs/index.json` advisory file lock** + atomic write (§4.4) |
| EEF on joint-only robots | Not specified | Adapters return `None` from `eef_pose` / `eef_velocity`; **EEF-based detectors auto-disabled**; FK out of Phase 1 scope (§7.2) |
| Performance target | Single number, includes I/O | **Compute path vs I/O path split**; Phase 1 compute target ≤ 5 s, video copy reported separately (§13) |
| Labels (extended) | Larger list discussed in GPT review | **Defer expansion**; `manipulation.yaml` default of 11 labels remains until real datasets justify more |

---

## 1. Purpose

Offline subtask-annotation pipeline for robot imitation-learning episodes.

Input: a recorded episode (video + parquet of robot state/action + task name).
Output: a versioned, human-reviewable timeline of `SubtaskSegment`s.

Designed as an **independent Python package** (`mimicanno`) that can be invoked standalone (CLI) or embedded into MimicRec.

## 2. Core principles

1. **VLM is for semantics. Boundaries come from robot state and object state.**
2. **Boundary detection and labeling are decoupled.**
3. **Smoothing is a separate stage.**
4. **Human review is assumed; full auto is not a goal.**
5. **Subtask labels are not free-form. The allowed-label list is enforced.**
6. **Heavy models (SAM3, VLM) always run on sub-sampled frames.**
7. **Run artifacts are immutable, self-contained, and versioned.** No silent overwrites of source files.

## 3. Phase plan (B')

```
Phase 1: signals + read-only timeline viewer
Phase 2: provisional VLM labeling (no object_state)
Phase 3: SAM3 + integrated boundary score + relabel (with object_state)
Phase 4: temporal smoothing / Viterbi
Phase 5: edit UI / export / evaluation
```

Each phase produces a runnable, testable artifact. Phase N+1 may *change* (not add) the upstream contract — schema versioning is mandatory.

### Phase 1 deliverables (the focus of this brush-up)

- `mimicanno annotate` CLI that ingests a LeRobot episode and writes a **run directory** under `<repo>/runs/<canonical_name>/` (canonical name defined in §4.1).
- `boundaries.json` with **integrated-score boundary candidates** (signals only).
- `signals.json` for viewer waveform display.
- Skeleton `annotation.json` with one segment per Phase 1 candidate-bracketed clip, `phase="unlabeled"`.
- React/Vite read-only viewer that reads `manifest.json` and renders video + timeline + waveforms + markers.

Phase 1 explicitly does **not** include: VLM labels, SAM3, smoothing, edit affordances, persistence/backend.

### Phase 2

VLM labels each Phase 1 clip using only `task_text` + `keyframe` + `robot_state` summary. `label_source = "vlm_robot_state_only"`, `object_state_unavailable = true`. Phase 2 exists to lock the VLM JSON schema and allowed-label enforcement, not to evaluate VLM intelligence.

### Phase 3

SAM3 enters. Boundary score gains object-state sources. Re-label with `label_source = "vlm_with_object_state"`.

### Phase 4

Smoothing. Min-duration filter, short-identical merge, forbidden-transition penalties, optional Viterbi.

### Phase 5

Edit UI, export to parquet/MimicRec, evaluation harness (`human_edit_time` etc.).

---

## 4. Phase 1 viewer architecture (B-1'')

The Phase 1 viewer is a static React/Vite app reading a self-contained, versioned **run directory** produced by the CLI. **No backend.**

### 4.1 Run directory layout

CLI writes to `<repo>/runs/<canonical_name>/` (NOT under `frontend/public/`), where the **canonical name** is the deterministic key:

```
canonical_name := f"{episode_id}__{config_hash[:8]}"
```

Two runs with different `(episode_id, config_hash)` always have distinct canonical names; re-running with the same `(episode_id, config_hash)` reuses the same canonical name and therefore the same directory (per §6.5). All other paths in this spec — the rename protocol, the index entries, the routing rules — assume this canonical name.

```
<repo>/
  runs/                              # gitignored; CLI output root
    episode_000__abc12345/           # canonical name
      manifest.json
      annotation.json
      boundaries.json
      signals.json
      video.mp4                      # default: copied. Symlink only with --link-video.
    episode_000__def67890/           # different config_hash → distinct directory
      ...
    episode_001__abc12345/
      ...
    index.json                       # run discovery (auto-maintained by CLI)
    index.json.lock                  # advisory file lock (§4.4)
  frontend/
    vite.config.ts                   # mounts ../runs at /runs/* during `pnpm dev`
    src/
      ...
```

`<repo>/runs/` is ignored by git via `.gitignore`. A `runs/.gitkeep` marker keeps the directory present.

**Why not `frontend/public/runs/`** (the obvious alternative): generated artifacts in the source tree → accidental commits, polluted diffs, CI bloat, and the conceptually-wrong implication that runs are app assets. Vite's dev server can serve an external directory cleanly; the cost of doing this right from day one is a 5-line `vite.config.ts` change.

### 4.2 Vite dev-server configuration

`frontend/vite.config.ts` mounts the external `runs/` root at `/runs/*` for the dev server only. Production build (Phase 5) routes `/runs/*` through the backend.

### 4.3 `manifest.json` schema (`schema_version: "0.1.0"`)

```jsonc
{
  "schema_version": "0.1.0",
  "episode_id": "episode_000",
  "task": {
    "text": "pick red block",
    "version": null
  },
  "generated_at": "2026-04-25T12:00:00Z",
  "generator": {
    "name": "mimicanno",
    "cli_version": "0.1.0",
    "pipeline_phase": 1
  },
  "config_hash": "sha256:abc123...",
  "model_versions": {
    "sam3": null,
    "vlm": null
  },
  "pipeline_params": {
    "boundary": {
      "weights": { "gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1 },
      "thresholds": { "gripper_delta": 0.3, "velocity_valley": 0.05 },
      "merge_window_sec": 0.10,
      "score_threshold": 0.30,
      "disabled_sources": []
    }
  },
  "inputs": {
    "video":   { "path": "data/episode_000.mp4",     "sha256": "sha256:..." },
    "parquet": { "path": "data/episode_000.parquet", "sha256": "sha256:..." }
  },
  "time_base": "video_pts_seconds",
  "fps": 30,
  "duration_sec": 42.5,
  "compat": {
    "manifest":   1,
    "annotation": 1,
    "boundaries": 1,
    "signals":    1
  },
  "artifacts": [
    { "role": "video",       "url": "video.mp4",       "content_type": "video/mp4" },
    { "role": "annotation",  "url": "annotation.json", "content_type": "application/json" },
    { "role": "boundaries",  "url": "boundaries.json", "content_type": "application/json" },
    { "role": "signals",     "url": "signals.json",    "content_type": "application/json" }
  ]
}
```

Notes:
- **`artifacts[]` is a typed list with `url` fields.** UI code MUST go through `manifest.artifact("video").url` rather than hard-coding `/runs/<id>/video.mp4`. This makes Phase 5 backend migration a swap-out.
- `time_base` is explicit so future signal sources (object tracks at different rates) can be aligned.
- `config_hash` is `sha256` of canonical JSON of the `AnnotationConfig`. Two runs with different params on the same episode produce different hashes and live in separate directories (or `<episode_id>__<config_hash[:8]>`).

### 4.4 `runs/index.json`

Auto-maintained by the CLI on every successful run:

```jsonc
{
  "schema_version": "0.1.0",
  "runs": [
    {
      "episode_id": "episode_000",
      "config_hash_short": "abc12345",
      "manifest_url": "episode_000__abc12345/manifest.json",
      "task_text": "pick red block",
      "pipeline_phase": 1,
      "generated_at": "2026-04-25T12:00:00Z"
    }
  ]
}
```

**URL resolution rule.** All `manifest_url` and `artifact.url` fields are **relative to the directory containing the file that emitted them**:

- `runs/index.json` → its `manifest_url` resolves against `runs/`. In Phase 1 the viewer fetches `/runs/<manifest_url>` (e.g. `/runs/episode_000__abc12345/manifest.json`).
- `<canonical_name>/manifest.json` → its `artifacts[].url` resolves against `runs/<canonical_name>/`. The viewer fetches `/runs/<canonical_name>/<artifact.url>`.
- In Phase 5, the backend serves the same JSON shapes from `/api/runs/index.json` and `/api/runs/<canonical_name>/manifest.json`. The same relative-resolution rule applies — the viewer picks up `/api/runs/...` automatically because it resolves against the URL it just fetched.

This single rule keeps relative paths in the JSON and leaves URL composition to the consumer's URL-resolver. No hard-coded `/runs/` or `/api/runs/` strings in the viewer.

Viewer routing rules:

| URL | Behavior |
|---|---|
| no params | Fetch `runs/index.json`, render the run list (one row per index entry, newest `generated_at` first), user picks one. |
| `?run=<id>` | Filter index entries by `episode_id == <id>`. **0 matches** → error page "no such run" with a back link to the list. **1 match** → resolve `manifest_url` against the index URL and fetch. **>1 matches** → load the entry with the most recent `generated_at` AND show a non-modal banner "N config variants exist for this episode" with a chooser of `(config_hash_short, generated_at, task_text)`. |
| `?run=<id>&hash=<config_hash_short>` | Look up the exact `(episode_id, config_hash_short)` row. Match → load. No match → error page. |

The viewer never enumerates the `runs/` directory itself; it relies on `index.json`. This keeps the static-vs-backend story symmetric (Phase 5 just swaps `index.json` for `GET /api/runs/index.json` with the same shape).

**Concurrency on update.** The CLI updates `index.json` via:
1. Acquire `runs/index.json.lock` (POSIX `fcntl.flock`, exclusive; on Windows `msvcrt.locking`).
2. Read current `index.json` (or empty if absent).
3. Upsert by `(episode_id, config_hash_short)` key; remove any prior entry with the same key.
4. Atomic write: write to `index.json.tmp.<pid>`, fsync, rename.
5. Release lock.

Phase 1 use is single-CLI / single-developer, but the lock is mandatory because a future "annotate many in parallel" loop is foreseeable. Without it, last-writer-wins silently drops entries — Codex flagged this concretely.

### 4.5 Operation

```bash
# 1) Generate. The CLI computes config_hash and writes to
#    runs/<episode_id>__<config_hash[:8]>/, then upserts runs/index.json.
mimicanno annotate \
  --video   data/episode_000.mp4 \
  --parquet data/episode_000.parquet \
  --task    "pick red block" \
  --robot   aloha

# 2) View
cd frontend && pnpm dev
# browse http://localhost:5173/?run=episode_000
# (the viewer resolves the actual run directory via index.json)
```

Notes:
- `--out` is reserved for advanced override of the run-root path; the default is `<repo>/runs/`. Users SHOULD NOT pass `--out runs/episode_000` directly because the directory name is derived from `(episode_id, config_hash)` to enforce one-run-per-config-hash.
- `?run=<id>` and `?run=<id>&hash=<config_hash_short>` are defined in §4.4. `?run=<id>` alone with multiple config variants picks the most recent and shows a chooser banner.

### 4.6 Video materialization policy

Default: **copy** the source mp4 into the run directory. Reasons:
- Symlinks behave inconsistently across OSes (especially Windows/WSL).
- "Self-contained, shareable run directory" is a stated property; symlinks break it.

Opt-in: `--link-video` (creates relative symlink) for local-dev disk pressure.

### 4.7 Phase 5 migration story

When the backend appears in Phase 5, the contract migrates to HTTP without UI rewrite:

- `manifest.json` shape unchanged; just delivered over HTTP.
- `artifacts[i].url` becomes a backend-issued URL (signed S3, gateway path, etc.).
- `runs/index.json` becomes `GET /api/runs/index.json` (same JSON shape as the static file).
- Viewer code paths are unchanged because they already only touch `manifest.artifact(role).url` and `Manifest`-typed objects.

---

## 5. Boundary detection (Phase 1 contract)

### 5.1 Detector inputs

Signals are extracted from the parquet via a `RobotAdapter` (see §7). Phase 1 needs:

- `gripper`: 1-D scalar in `[0, 1]` (0=closed, 1=open) per frame, length T
- `eef_velocity`: 1-D scalar `|v|` per frame, length T (derived from EEF pose diff)
- `eef_acceleration`: 1-D scalar `|a|` per frame, length T (optional, derived)
- `action_norm`: 1-D scalar `||action_t||` per frame, length T (optional)
- `fps`: float
- `duration_sec`: float

All signals are smoothed (1-D Gaussian, `sigma=fps*0.05` ≈ 50 ms) before detection.

### 5.2 Detectors and per-source raw events

Each detector produces a list of raw events `{frame, time, source, raw_value, source_score ∈ [0,1]}`.

| Detector | source | When it fires | source_score |
|---|---|---|---|
| Gripper transition | `gripper_transition` | `|smoothed_gripper[t] - smoothed_gripper[t-1]|` peak above `gripper_delta_threshold` (0.30) | `clip(peak / 0.5, 0, 1)` |
| EEF velocity valley | `eef_velocity_valley` | smoothed `|v|` local minimum below `velocity_valley_threshold` (0.05 m/s) **and** valley duration ≥ `min_valley_sec` (0.10 s) | `clip(1 - valley_min / threshold, 0, 1)` |
| EEF acceleration peak | `eef_acceleration_peak` | smoothed `|a|` local maximum above `accel_peak_threshold` | `clip(peak / (3 × threshold), 0, 1)` |
| Action norm change | `action_norm_change` | rolling-mean change-point on `||a_t||` (window 0.5 s) above `action_change_threshold` | `clip(delta / threshold, 0, 1)` |

All thresholds and weights are part of `AnnotationConfig` and feed into `config_hash`.

### 5.3 Integrated score and candidate promotion

Raw events within `merge_window_sec` (default 0.10 s) are merged into a **boundary candidate** keyed by the median `time` of merged events.

```
candidate.time   = median(events.time)
candidate.frame  = round(candidate.time * fps)
candidate.sources = [event.source for event in events]
candidate.scores  = { event.source: event.source_score for event in events }
candidate.score   = clip(
    Σ_source (weight[source] × scores[source]),
    0, 1
)
```

Default Phase 1 weights:
- `gripper_transition`: 0.50
- `eef_velocity_valley`: 0.25
- `eef_acceleration_peak`: 0.15
- `action_norm_change`: 0.10

Candidates with `score < score_threshold` (default 0.30) are dropped.

Phase 3 will add `gripper_object_distance_threshold_crossing` and `object_motion_start_stop` to `sources` and rebalance `weights`. The shape is unchanged — Phase 3 does not introduce a new contract.

### 5.4 `boundaries.json` schema

```jsonc
{
  "schema_version": "0.1.0",
  "episode_id": "episode_000",
  "candidates": [
    {
      "id": "b_001",
      "frame": 42,
      "time": 1.4,
      "sources": ["gripper_transition", "eef_velocity_valley"],
      "scores": { "gripper_transition": 0.95, "eef_velocity_valley": 0.62 },
      "score": 0.625
    }
  ]
}
```

The candidate `score` is the integrated weighted score from §5.3. There is no separate `boundary_confidence` field on candidates — segments derive their start/end boundary confidences from candidate `score` (see §6.1).

### 5.5 `signals.json` schema

Per-channel downsampled signals for viewer waveform rendering. Full-rate signals are intermediate and not persisted. Each channel is independently sampled (uniform within a channel) so the viewer can place markers against waveforms by absolute time without guessing alignment.

```jsonc
{
  "schema_version": "0.1.0",
  "episode_id": "episode_000",
  "duration_sec": 42.5,
  "channels": [
    {
      "name": "gripper",
      "unit": "normalized",
      "t0_sec": 0.0,
      "dt_sec": 0.0333,
      "values": [0.0, 0.0, 0.05, ...]
    },
    {
      "name": "eef_velocity",
      "unit": "m/s",
      "t0_sec": 0.0,
      "dt_sec": 0.0333,
      "values": [0.01, 0.02, ...]
    }
  ]
}
```

Per-channel timing rules:
- `t0_sec`: time (relative to video PTS 0) of `values[0]`. Always 0.0 in Phase 1.
- `dt_sec`: uniform inter-sample interval. The viewer plots `values[i]` at time `t0_sec + i * dt_sec`.
- Channels MAY have different `dt_sec`. The viewer must not assume a shared timebase.
- `len(values) * dt_sec` SHOULD equal `duration_sec` ± one sample. Mismatch beyond one sample is a producer bug.
- The default `dt_sec` for Phase 1 is `1.0 / 30.0` (≈30 Hz). Higher-rate channels (e.g., raw gripper at the full episode FPS) MAY be emitted; the viewer downsamples on render.

### 5.6 Phase 1 clip bracketing algorithm

`annotation.json` segments are derived from `boundaries.json` deterministically:

1. Sort candidates by `time` ascending. Stable sort; equal times keep insertion order.
2. Build the cut-time list:
   `cuts = [0.0] + [c.time for c in candidates] + [duration_sec]`
3. Emit one `SubtaskSegment` per adjacent pair `(cuts[i], cuts[i+1])`, half-open in time `[start_time, end_time)`.
   - `start_frame = round(start_time * fps)`
   - `end_frame   = round(end_time   * fps) - 1` (inclusive last frame)
   - `phase = "unlabeled"` (a reserved label, see §8.4).
   - Provenance: `start_boundary` and `end_boundary` populated per §6.1; the implicit start (`time=0.0`) and end (`time=duration_sec`) cuts produce sentinel boundaries with `sources=["episode_start"]` / `["episode_end"]` and `score=1.0`.
4. Empty candidate list → exactly one segment spanning `[0.0, duration_sec)`.
5. Segments shorter than `epsilon_sec = 1.0 / fps` are dropped (sub-frame artifact of merged candidates); a warning is logged.

---

## 6. Schema (final)

### 6.1 `SubtaskSegment`

```python
@dataclass
class BoundaryRef:
    candidate_id: str | None       # None for sentinel boundaries (episode_start/end)
    time: float
    sources: list[str]             # e.g. ["gripper_transition"], or ["episode_start"]
    score: float                   # from boundaries.json candidate score; 1.0 for sentinels


@dataclass
class SubtaskSegment:
    # Identity
    segment_id: str        # e.g. "s_007"
    episode_id: str

    # Span
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float

    # Label
    phase: str             # allowed-labels member, or reserved "unlabeled"/"unknown" (§8.4)
    verb: str | None
    object: str | None
    target: str | None
    failure_flags: list[str]   # e.g. ["failed_grasp"]; empty list = nominal

    # Provenance
    label_source: Literal[
        "signals_only",            # Phase 1 placeholder
        "vlm_robot_state_only",    # Phase 2
        "vlm_with_object_state",   # Phase 3
        "human_edit",              # Phase 5
    ]
    object_state_unavailable: bool
    object_track_ids: list[str]    # see §9.5 for producer contract
    label_version: str             # e.g. "manipulation.v1"

    # Boundaries (per-edge, NOT collapsed to a single number)
    start_boundary: BoundaryRef
    end_boundary: BoundaryRef

    # Confidence
    boundary_confidence: float     # = min(start_boundary.score, end_boundary.score)
    vlm_confidence: float | None   # None until Phase 2
    overall_confidence: float      # f(boundary, vlm) — formula in §6.4

    # Evidence / review
    evidence: str | None
    reviewed: bool
    reviewer_id: str | None
```

`boundary_confidence` is a derived convenience: `min(start_boundary.score, end_boundary.score)`. The viewer and downstream consumers SHOULD prefer the per-edge `start_boundary` / `end_boundary` fields when ranking or filtering segments. The `min` aggregation reflects that a segment is no more confident than its weakest edge.

### 6.2 `AnnotationResult` (serialized to `annotation.json`)

```python
@dataclass
class AnnotationResult:
    schema_version: str
    episode_id: str
    task: TaskInfo
    generated_at: str
    generator: GeneratorInfo
    config_hash: str
    model_versions: dict[str, str | None]
    pipeline_phase: int

    segments: list[SubtaskSegment]

    # Cross-references (relative to manifest)
    boundaries_url: str    # "boundaries.json"
    signals_url: str       # "signals.json"

    notes: str | None
```

### 6.3 `failure_flags` semantics

`failure_recovery` is **not a phase**. A segment whose `phase` is the underlying activity may have `failure_flags` populated:

```python
SubtaskSegment(
    phase="grasp_object",
    failure_flags=["failed_grasp"],
    ...
)
```

Default flag vocabulary is intentionally **empty** at this milestone. It will be expanded after Phase 5 when real failure data informs categories. Until then, `failure_flags` is `[]`.

### 6.4 Confidence aggregation

```
overall_confidence = sqrt(boundary_confidence * vlm_confidence)
                     if vlm_confidence is not None
                     else boundary_confidence
```

Geometric mean penalizes asymmetry (high VLM confidence over a flaky boundary stays moderate). The formula is exposed and configurable.

### 6.5 On-disk format and atomicity

- **JSON sidecar inside the run directory.** Source video and parquet are never modified.
- One run per `(episode_id, config_hash)` pair. Phase 1 supports **POSIX filesystems**; Windows behaves correctly but with weaker atomicity guarantees (see below).
- Re-running with a different config produces a different canonical name (different `config_hash`) and therefore a distinct directory. `index.json` lists both.

**POSIX run-directory replacement (atomic from a reader's perspective):**

Let `name = f"{episode_id}__{config_hash[:8]}"` be the canonical name (§4.1). All paths below use this exact `name`.

1. Write all artifacts to `runs/<name>.tmp.<pid>/`.
2. If `runs/<name>/` already exists (same-config re-run), rename it to `runs/<name>.bak.<pid>/` (atomic).
3. Rename `runs/<name>.tmp.<pid>/` → `runs/<name>/` (atomic).
4. `rm -rf runs/<name>.bak.<pid>/`.

Steps 2 and 3 are each atomic on POSIX. A reader holding a path obtained from `runs/index.json` either sees the old run or the new run at `runs/<name>/`, never a mix. Because the canonical name is fully qualified, two simultaneously-running CLIs targeting different `config_hash`es never collide on the same temp/backup paths.

**Crash recovery / startup scavenger.** Because steps 1, 2, and 4 are not transactional, a CLI crash may leave `runs/<name>.tmp.<pid>/` and/or `runs/<name>.bak.<pid>/` directories on disk. On startup, the CLI scavenges:

- For every directory matching `runs/*.tmp.<pid>/` or `runs/*.bak.<pid>/`, check whether `<pid>` is a live process holding the index lock (§4.4). If not, `rm -rf` it.
- The scavenger runs after acquiring `runs/index.json.lock` so it does not race with another CLI's mid-write state.
- Scavenger actions are logged with the canonical name and reason.

`runs/index.json` is updated only after step 3 succeeds, so a stale `.bak` never causes index drift.

**Windows behavior:** `os.replace` is used for files but **non-empty directory replacement is not atomic** on Windows. A reader could observe a transient state. This is acknowledged and accepted for Phase 1 (single-developer, single-CLI workflows). Phase 5's backend will own this concern.

### 6.6 Schema versioning rule

Each schema carries its own `schema_version` (semver `"MAJOR.MINOR.PATCH"`). Versions are **independent** — bumping `signals.json` does not require bumping `manifest.json` or any other schema.

**Compatibility check:** the viewer (and any consumer) parses each artifact and asserts `consumer_max_major >= artifact_major`. Mismatch → fail loudly with both versions in the error message. MINOR/PATCH differences are ignored at parse time; consumers ignore unknown fields and tolerate missing optional fields within the same MAJOR.

`manifest.json` carries a `compat` block whose scope is **only the in-run artifacts** (the things rooted under this manifest's directory). It declares the MAJOR version that the producer actually emitted for each:

```jsonc
"compat": {
  "manifest":   1,
  "annotation": 1,
  "boundaries": 1,
  "signals":    1
}
```

External schemas — `runs/index.json` (run-root) and label YAMLs (`mimicanno/configs/labels/*.yaml`, package-level) — are **not** in `compat`. They each carry their own `schema_version` and consumers that load them perform an independent MAJOR compare at the point of load. This keeps `compat` from leaking package-level concerns into a run-level contract.

The CLI populates `compat` based on the artifacts it just emitted. The viewer compares each artifact's MAJOR against the corresponding `compat` entry, not its own hardcoded value, so a viewer two versions ahead of an old run can still display it correctly if `compat` matches what that viewer supports.

Parquet export is a Phase 5 concern (`mimicanno export` command).

---

## 7. LeRobot parquet read contract

LeRobot v2/v3 episodes have known column conventions but per-robot variations.

### 7.1 Required and optional columns

| Column | Required | Notes |
|---|---|---|
| `observation.state` | yes | float vector per frame; gripper extraction is robot-specific |
| `action` | yes | float vector per frame |
| `timestamp` | yes-ish | preferred FPS source; falls back to metadata |
| `frame_index` | optional | sanity check |
| `episode_index` | optional | informational |

### 7.2 `RobotAdapter` interface

```python
class RobotAdapter(Protocol):
    name: str

    # Required for Phase 1
    def gripper_signal(self, df: pa.Table) -> np.ndarray: ...   # [T] in [0, 1]

    # Optional. Return None if the robot's parquet does not carry Cartesian EEF.
    def eef_pose(self, df: pa.Table) -> np.ndarray | None: ...   # [T, 7] (xyz + quat) or None
    def eef_velocity(self, df: pa.Table) -> np.ndarray | None: ...  # [T] |v| or None
```

**EEF availability rule (Phase 1):**
- If `eef_pose` and `eef_velocity` both return `None`, Phase 1 drops the EEF-based detectors (`eef_velocity_valley`, `eef_acceleration_peak`). The `gripper_transition` and `action_norm_change` detectors continue to run.
- The dropped sources are recorded in the `manifest.json` field `pipeline_params.boundary.disabled_sources`.
- Forward kinematics from joint angles is **out of scope for Phase 1**. If a user wants EEF-based detectors on a joint-only robot, they pre-compute Cartesian columns in their parquet and use `GenericAdapter` to surface them.

Default adapters shipped with `mimicanno`:

| Adapter | `name` | EEF available? | Notes |
|---|---|---|---|
| `AlohaAdapter` | `aloha` | yes (Cartesian columns present) | gripper at last index of `observation.state` per arm; bimanual via `arm_id` |
| `KochAdapter` | `koch` | no by default | joint-only state; EEF detectors disabled unless user supplies Cartesian columns |
| `SO100Adapter` | `so100` | no by default | as above |
| `GenericAdapter` | `generic` | configurable | column mapping via `--robot-config <yaml>` |

Adapter selection: explicit `--robot <name>` flag is the only path. **No auto-detection in Phase 1** — surprises live too long.

### 7.3 FPS resolution

1. If episode metadata file (`meta/episodes.parquet` or sibling `episodes.jsonl`) carries `fps`, use it.
2. Else compute `fps = 1.0 / median(diff(timestamp))`. Reject if `std(diff) / median(diff) > 0.05`.
3. Else **abort** with explicit error. No silent default.

### 7.4 Gap handling

NaN spans in required signals:
- Span ≤ 0.5 s → linear interpolate, log a warning.
- Span > 0.5 s → abort with frame range in error message.

---

## 8. Allowed-labels configuration

### 8.1 Storage

Bundled label sets live in `mimicanno/configs/labels/<task_type>.yaml`. Default for manipulation tasks (`manipulation.yaml`):

```yaml
schema_version: "0.1.0"
task_type: manipulation
labels:
  - id: idle
    verbs: []
    requires_object: false
  - id: approach_object
    verbs: [approach, reach]
    requires_object: true
  - id: align_gripper
    verbs: [align]
    requires_object: true
  - id: grasp_object
    verbs: [grasp, pick, take]
    requires_object: true
  - id: lift_object
    verbs: [lift]
    requires_object: true
  - id: move_to_target
    verbs: [move, transport, carry]
    requires_object: true
  - id: align_to_target
    verbs: [align]
    requires_object: true
  - id: place_object
    verbs: [place, put]
    requires_object: true
  - id: release_object
    verbs: [release]
    requires_object: true
  - id: retreat
    verbs: [retreat, withdraw]
    requires_object: false
unknown_task_fallback: manipulation
```

Override path: `mimicanno annotate --labels-file path/to/custom.yaml`.

### 8.2 Enforcement

The VLM prompt receives `allowed_labels: list[str]` (just `id`s). VLM output is JSON-validated against the allowed set. Free-form labels are rejected; on rejection, the labeler retries up to 3 times with stricter prompt phrasing. Final fallback: `phase="unknown"` with `vlm_confidence=0.0`.

### 8.3 Unknown task type

If the task name doesn't map to a known type via a (configurable) keyword router, `unknown_task_fallback: manipulation` is used. A `notes` entry is added to `AnnotationResult` recording the fallback.

### 8.4 Reserved phases

Two phase strings are **reserved** and never appear in any label YAML. They bypass allowed-label validation:

| Reserved phase | Meaning | Where it appears |
|---|---|---|
| `unlabeled` | Phase 1 placeholder; the segment exists structurally but no labeler has run yet. | Phase 1 only. Phase 2 must replace every `unlabeled` segment. |
| `unknown` | A labeler ran but failed to produce a valid allowed label after retries. | Phase 2/3 fallback (§8.2) and human-edit fallback. |

Validation:
- A label YAML that defines a label `id` of `unlabeled` or `unknown` is rejected at load time.
- Round-trip readers MUST accept these two phase strings even though they are not in the active label set.
- Filtering helpers (e.g., "show only confidently-labeled segments") SHOULD treat `unlabeled` and `unknown` as low-confidence regardless of the numeric `overall_confidence`.

---

## 9. SAM3 prompt-generation contract (Phase 3)

Phase 3 introduces SAM3 + object-aware boundary sources. The prompt generation is the first new failure point and gets its own contract.

### 9.1 Inputs

```python
class TrackingPlanInput:
    task_text: str
    initial_frame: np.ndarray   # H×W×3, RGB, uint8
    allowed_labels: LabelSet    # informs object/target heuristics
```

The initial frame is required because text-only prompts can't disambiguate "the object" / "it" without visual grounding. Initial frame is taken at frame 0; if frame 0 fails to decode, fall back to the frame at 5% of duration.

### 9.2 Step A: Gemma extracts entities

Gemma is asked for a single JSON object:

```json
{
  "objects": ["red block"],
  "targets": ["bin A"],
  "tools":   ["gripper"]
}
```

Schema-validated. Up to 3 retries on bad JSON; then fall back to `objects=[]`, which triggers degrade (§9.4).

### 9.3 Step B: SAM3 grounding on initial frame

Each prompt is run against the initial frame. The result is an initial bbox + mask per prompt, or empty.

### 9.4 Output and degrade path

```python
@dataclass
class TrackingPlan:
    object_prompts: list[str]
    target_prompts: list[str]
    tool_prompts: list[str]
    initial_detections: dict[str, BBox]   # prompt -> bbox
    failed_prompts: list[str]
```

**Degrade path** if `object_prompts` is empty OR all object prompts produced no initial detection:
- Skip Phase 3's object-state pipeline entirely for this episode.
- Re-run Phase 2 labeling instead.
- Set `object_state_unavailable=true` on all segments.
- Record a `notes` entry: `"sam3_degraded: <reason>"`.

This keeps a single failure mode (no object tracks) from blowing up the whole pipeline.

### 9.5 Object track ID contract

SAM3 propagation across sampled frames yields per-prompt tracks. Each track gets a stable string ID with the form:

```
obj:<role>:<slug>:<index>
```

- `role` ∈ `{object, target, tool}`
- `slug` is the prompt text lower-cased, with non-alphanumerics replaced by `_` and runs of `_` collapsed.
- `index` is the per-(role, slug) occurrence index from SAM3 (0-based).

Examples: `obj:object:red_block:0`, `obj:target:bin_a:0`, `obj:tool:gripper:0`.

The ID is assigned by the tracker wrapper at plan time and is **stable** for the lifetime of the run. If SAM3 loses then re-acquires a track within the same episode, it MUST keep the same ID (the wrapper handles re-association by IoU on the bbox; a track lost beyond a configurable gap becomes a new ID, and that gap is recorded in the run notes).

`SubtaskSegment.object_track_ids` (§6.1) is the set of track IDs whose mask/bbox is non-empty for at least one frame in `[start_frame, end_frame]`. In Phase 1 (no SAM3) this list is always `[]`. In Phase 3 the list is populated and stable across re-runs that produce the same `config_hash`.

Tracks themselves (per-frame bbox/mask, derived signals) are written to a Phase 3-only artifact `tracks.json` whose schema is deferred to the Phase 3 spec; the segment-level `object_track_ids` list is the only Phase 1/2 contact point.

---

## 10. Temporal smoothing (Phase 4)

Phase 4 adds the smoother that the original design.md sketched. Two changes from the original sketch:

1. **Forbidden transitions are penalties, not hard rules.** Phase 1 keeps hard rules as a debugging aid; Phase 4 promotes them into a Viterbi/penalty term so a confidently-labeled segment can override.
2. **`min_segment_duration_sec`** is enforced via merge-with-neighbor (highest-confidence neighbor wins), not deletion.

Default config (overridable via `AnnotationConfig`):

```python
min_segment_duration_sec: float = 0.30
merge_threshold_sec: float = 0.20
forbidden_transitions: list[tuple[str, str]] = [
    ("grasp_object",   "approach_object"),
    ("release_object", "grasp_object"),
    ("lift_object",    "idle"),
]
viterbi_enabled: bool = True   # Phase 4 default
```

---

## 11. Error-handling table

| Failure | Detection | Action |
|---|---|---|
| Video decode error | ffmpeg non-zero exit / decoder exception | Abort with the failing path; no partial run directory |
| Parquet missing required column | schema validation on load | Abort listing the missing column(s) |
| `RobotAdapter.gripper_signal` raises | adapter contract violation | Abort with hint to set `--robot` or `--robot-config` |
| FPS undetermined | metadata absent **and** timestamp variance > 5% | Abort |
| Robot-state NaN spans > 0.5 s | post-load NaN scan | Abort with frame range |
| Robot-state NaN spans ≤ 0.5 s | post-load NaN scan | Linear interpolate, log warning |
| Empty/zero `action` column | column missing or `action_norm == 0` for ≥ 95% of frames | Drop the `action_norm_change` detector; continue. Record in `pipeline_params.boundary.disabled_sources`. Future-emitted candidates simply do not include `action_norm_change` in their `sources`. |
| EEF columns missing on adapter that doesn't expose them | `eef_pose()` and `eef_velocity()` both return `None` | Drop `eef_velocity_valley` and `eef_acceleration_peak`; record in `pipeline_params.boundary.disabled_sources`. Continue. (`gripper_transition` is always available because `gripper_signal()` is mandatory in §7.2, so the pipeline is never starved of detectors.) |
| Stale `*.tmp.<pid>/` or `*.bak.<pid>/` from a prior crash | startup scavenger sees PID is no longer the index-lock holder | `rm -rf` the stale directory; log the run name and reason (§6.5 "Crash recovery"). |
| Initial frame extraction fails (Phase 3) | ffmpeg fails on frame 0 | Retry at 5% of duration; if still fails, abort |
| SAM3 init failure (Phase 3) | constructor exception | Degrade to Phase 2 mode for the whole run |
| SAM3 no detection on initial frame | empty masks | Degrade to Phase 2 mode for the whole run |
| Gemma bad JSON (Phase 2/3) | schema validation fails | Up to 3 retries with stricter prompt; final fallback `phase="unknown"`, `vlm_confidence=0` |
| `runs/<canonical_name>/` already exists | pre-write check | Replace per §6.5 (POSIX atomic via two renames; non-atomic on Windows). Canonical name = `<episode_id>__<config_hash[:8]>`. |
| `runs/index.json` lock contention | another CLI process holds the lock | Wait up to 30 s with exponential backoff; if still held, abort with the holder's PID if discoverable |

Every abort writes a structured error JSON to stderr (`{"error_code": "...", "message": "...", "context": {...}}`) and exits non-zero.

---

## 12. Package structure

```
MimicAno/
  sam3/                           # existing clone (Phase 3+)
  mimicanno/
    __init__.py
    cli.py                        # entry point: mimicanno annotate / view / export
    pipeline.py                   # orchestrator
    boundaries.py                 # §5: detectors + integrated score
    object_tracker.py             # §9: Phase 3 SAM3 wrapper
    clip_features.py              # clip-level summaries for VLM
    vlm_labeler.py                # Gemma JSON labeling
    smoother.py                   # §10: Phase 4 smoothing
    schema.py                     # SubtaskSegment, AnnotationResult, Manifest, ...
    config.py                     # AnnotationConfig + config_hash
    io.py                         # parquet load, RobotAdapter, run-dir IO
    adapters/
      __init__.py
      aloha.py
      koch.py
      so100.py
      generic.py
    configs/
      labels/
        manipulation.yaml
  frontend/                       # Phase 1 viewer (static React/Vite)
    vite.config.ts                # mounts ../runs at /runs/* (dev only)
    src/
      App.tsx
      RunList.tsx                 # consumes runs/index.json
      RunViewer.tsx               # consumes manifest.json
      VideoPlayer.tsx
      Timeline.tsx
      WaveformView.tsx
      BoundaryMarkerLayer.tsx
      lib/
        manifest.ts               # typed Manifest + artifact resolver
  runs/                           # gitignored CLI output root
    .gitkeep
  docs/
    design.md                     # superseded by this brush-up
    superpowers/specs/2026-04-25-mimicano-design-brushup.md
  .gitignore                      # runs/, except .gitkeep
  pyproject.toml
  README.md
```

---

## 13. Performance targets (refined)

Targets are split into **compute path** (CPU work the pipeline must do) and **I/O path** (filesystem cost that scales with episode size). The Phase 1 end-to-end target lives on the compute path; I/O has its own target band because video copy dominates at large sizes.

| Component | Path | Sample rate | Target per 60-s episode |
|---|---|---|---|
| Boundary detection (Phase 1, signals only) | compute | full-rate, numpy | < 1 s |
| Signal smoothing + JSON write (annotation/boundaries/signals) | compute | full-rate | < 1 s |
| Video copy into run directory | I/O | once per run | scales with file size; ≈ 0.5 s per 100 MB on SSD; skipped with `--link-video` |
| Index update with lock | I/O | once per run | < 100 ms |
| SAM3 (Phase 3) | compute | every 10th frame, bbox-interp between | 30–60 s on 1× RTX 4090 |
| Gemma labeling (Phase 2/3) | compute | 1–2 keyframes per clip | 20–40 s on 1× RTX 4090 |
| Smoothing (Phase 4) | compute | full-rate, pure python | < 1 s |
| Viewer cold load | network | static fetch | < 2 s on local net |

**Phase 1 compute-path target (excluding video copy): ≤ 5 s per episode on a typical laptop CPU.**

`mimicanno annotate` MUST log the compute-path total and the video-copy total separately so regressions can be attributed correctly. If `--link-video` is used, the video-copy line is reported as `0 ms (linked)`.

---

## 14. MimicRec integration (Phase 5)

`mimicanno` exposes `annotate_episode(...)` and a typed `AnnotationResult`. MimicRec's Replay page consumes the run directory directly (read `manifest.json`), or invokes a Phase 5 backend.

The backend (Phase 5) wraps the same run-directory contract over HTTP. Canonical endpoints (chosen so the relative-path resolution rule from §4.4 carries over unchanged):

- `GET /api/runs/index.json` — same shape as the static `runs/index.json`.
- `GET /api/runs/<canonical_name>/manifest.json` — same shape as the static manifest.
- `GET /api/runs/<canonical_name>/<artifact>` — serves the artifact bytes.

Editing endpoints are added in Phase 5 and are out of scope here. The viewer code is unchanged because it consumes `Manifest`-typed objects and `artifact(role).url`, both resolved relatively.

---

## 15. Exit criteria

### Phase 1
1. `mimicanno annotate --video X --parquet Y --task "pick red block" --robot aloha` succeeds on at least one real LeRobot episode.
2. `runs/<episode_id>__<config_hash[:8]>/manifest.json` validates against the §4.3 schema.
3. `boundaries.json` contains ≥ 1 candidate when the episode contains a gripper transition.
4. `runs/index.json` is updated under file lock (§4.4); a deliberate concurrent CLI invocation does not lose entries.
5. `cd frontend && pnpm dev` then `?run=<episode_id>` renders video + timeline + waveforms + markers without console errors.
6. Re-running with the same config and same inputs produces a byte-equivalent `manifest.json` (modulo `generated_at`) and reuses the same run directory.
7. On an Aloha episode (Cartesian EEF available) the run uses all four detectors. On a Koch episode (joint-only) the run completes with `pipeline_params.boundary.disabled_sources` listing the EEF-based detectors and `gripper_transition` still firing.
8. Phase 1 viewer correctly aligns boundary markers to waveforms when channels have different `dt_sec` (§5.5).
9. With two runs of the same episode under different configs in `index.json`, `?run=<id>` shows the chooser banner; `?run=<id>&hash=<short>` loads the exact one (§4.4).
10. Crashing the CLI mid-write (after the `.tmp` is created, before the rename) leaves the previous run readable; a subsequent CLI invocation scavenges the stale `.tmp` (§6.5).

### Phase 2
7. VLM labels every Phase 1 clip with one of the allowed labels; rejection retries are observable in logs.
8. `label_source = "vlm_robot_state_only"` on all segments.

### Phase 3
9. SAM3 succeeds on at least one real episode; `object_state_unavailable=false` on the resulting segments.
10. SAM3 failure on a synthetic broken episode triggers the §9.4 degrade path with `object_state_unavailable=true` and a `notes` entry.

### Phase 4
11. Smoothing reduces the segment count vs Phase 3 raw output and never produces a forbidden transition with high overall_confidence.

### Phase 5
12. Edit UI persists changes via backend; export to parquet matches the round-trip schema.

---

## 16. Open items (deferred, not blocking Phase 1)

- Expanded label list (`search_object`, `push_object`, `insert_object`, ...): defer until real datasets justify.
- Failure subcategories (`failed_grasp`, `lost_object`, ...): same.
- Camera-embedding change-point detector: deferred (new model dependency).
- Confidence sub-decomposition (tracking_confidence, smoothing_confidence): add only when needed.
- Backend persistence model (Phase 5): out of scope here.
