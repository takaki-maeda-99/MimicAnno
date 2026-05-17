# U-A: Dataset processing & visualization UI — master design

Date: 2026-05-17
Author: brainstorming session 2026-05-17 (Opus 4.7)
Parent context: TODO「MimicAnno で新規データをどうやって処理するか / UI 上で完結させたい」

This master spec scopes the whole U-A initiative ("Mode A": already-on-disk LeRobot v3 datasets, no upload). It freezes the **shared HTTP contract** so the 5 sub-projects can be specced and implemented in parallel by separate Claude sessions. **Each sub-project gets its own design doc + implementation plan**; this file is the umbrella.

Mode B (人手動画) is explicitly **out of scope** of this spec — it depends on the Hand pipeline not being complete and is deferred to a separate brainstorming.

## 0. Scope and intent

In scope:

- HTTP API additions to `mimicanno serve` for: dataset catalog, dataset-level annotation summary, annotate-job submission/monitoring, VLM dump fetch, SAM3 mask fetch.
- Frontend additions: dataset catalog page, job monitor page, dataset summary dashboard, RunViewer side panels (VLM, mask overlay), site-wide jobs indicator.
- Job runner that wraps existing `scripts/batch_annotate_4B.py` / `mimicanno annotate` via subprocess.
- Single-machine, single-GPU-queue scheduling (sequential annotate jobs).
- Path-based dataset registration (server scans `data/*/`); **no client-side upload**.

Non-goals:

- Browser-side upload of video / parquet files. Datasets must already be on the server filesystem.
- Mode B (human-hand-only video pipeline). Separate spec.
- Multi-machine / cluster scheduling.
- Authentication / multi-user (single-user dev tool assumed).
- Re-architecting `mimicanno annotate` itself; we wrap it.
- Modifying existing GET / PATCH routes; we add new ones beside them.
- New annotation schema fields; we visualize what exists.

## 1. Architecture overview

```
   Server (mimicanno serve, extended)               Browser
   ───────────────────────────────────              ───────────────────────────
   data/<dataset>/  ──┐                             /datasets        (U-A1 F)
                      ├─▶  GET /api/datasets        /datasets/<name> (U-A2 F)
   runs/<rs>/<can>/ ──┘     /api/datasets/{}        /jobs            (U-A1 F)
                            /api/datasets/{}/summary /runs?run=<can>  (existing
                                                                       + U-A3 F
                                                                       + U-A4 F)
   .mimicanno-jobs/<id>.json ▶ GET /api/jobs                          Header
                                /api/jobs/{id}                        (U-A5 F)
                                /api/jobs/{id}/stream  (SSE)
                                POST /api/jobs

   subprocess.Popen (scripts/batch_annotate_4B.py) ◀──┐
       │                                              │
       └─ stdout/stderr → .mimicanno-jobs/<id>.log    │
                          ┌───────────────────────────┘
                          │
   runs/<rs>/<can>/_vlm_dumps/*.jsonl ──▶ GET /api/runs/{canonical}/vlm_dumps    (U-A3)
   runs/<rs>/<can>/tracks.json (+masks) ──▶ GET /api/runs/{canonical}/masks?...   (U-A4)
```

Job submission and progress are the only stateful additions. Catalog, summary, vlm_dumps, and masks are pure read-side over existing filesystem artifacts.

## 2. Shared HTTP contract (frozen by this spec)

All endpoints are versioned under `/api/`. Sub-projects MUST implement / consume these exact shapes. Field-level additions are allowed (additive change) but not removals or renames without revising this spec.

### 2.1 Datasets

```
GET /api/datasets
→ 200 application/json
[
  {
    "name": "SO101",                              // dir name under data/
    "path": "data/SO101",                         // repo-relative
    "ep_count": 33,                               // episodes on disk
    "annotated_ep_count": 17,                     // episodes with ≥1 run in runs/
    "robot_hint": "so101",                        // inferred from data/{}/meta or null
    "task_text_hint": "Put the tape into the bottle",  // from meta/tasks.parquet, or null
    "videos_root": "videos/chunk-000/observation.images.front",  // for catalog UI
    "last_modified": "2026-05-17T10:00:00Z"       // max mtime under data/<name>/meta/
  },
  ...
]
```

```
GET /api/datasets/{name}
→ 200 application/json
{
  "name": "SO101",
  "path": "data/SO101",
  "episodes": [
    {
      "idx": 0,
      "video_path": "videos/chunk-000/observation.images.front/episode_000000.mp4",
      "parquet_path": "data/chunk-000/episode_000000.parquet",
      "frame_count": 151,
      "fps": 15.0,
      "runs": [
        { "canonical": "episode_000000__e35061106394",
          "run_hash": "sha256:e3506110...",
          "run_set": "so101_phase4_v5",
          "pipeline_phase": "phase4",
          "generated_at": "2026-05-16T..." },
        ...
      ]
    },
    ...
  ]
}
```

`episodes[i].runs` is empty when an ep hasn't been annotated.

### 2.2 Dataset summary (U-A2)

```
GET /api/datasets/{name}/summary?run_set=<rs>      // run_set optional, defaults to most recent
→ 200 application/json
{
  "run_set": "so101_phase4_v5",
  "ep_count": 33,
  "annotated_ep_count": 17,
  "label_distribution": { "approach_object": 42, "grasp": 17, ... },
  "segment_count_stats": { "mean": 4.5, "min": 2, "max": 9 },
  "reviewed_rate": 0.18,
  "per_episode": [
    { "idx": 0, "canonical": "...", "segment_count": 5, "reviewed_count": 5, "label_diversity": 4 },
    ...
  ]
}
```

### 2.3 Jobs (U-A1)

```
POST /api/jobs
  body: {
    "kind": "annotate",
    "dataset": "SO101",
    "episode_indices": [0, 1, 2],          // null/missing = all in dataset
    "robot_config": "configs/robot/so101.yaml",   // path repo-relative
    "pipeline_config": "configs/pipeline/phase4_v5.yaml",
    "run_set": "so101_phase4_v5_2026-05-17",       // output directory under runs/
    "gpu_index": 0,                                 // optional, for future multi-GPU
    "variant": "4B"                                 // "4B" | "26B"; MVP only honors "4B"
  }
→ 202 application/json
{ "job_id": "j_20260517_140523_a1b2", "status": "queued" }
```

```
GET /api/jobs
→ 200 application/json
[
  { "job_id": "j_...", "status": "running", "dataset": "SO101",
    "started_at": "...", "progress_pct": 35, "current_episode_idx": 3 },
  { "job_id": "j_...", "status": "done", "dataset": "SO101",
    "finished_at": "...", "run_canonicals": ["episode_000000__...", ...] },
  ...
]
```

`status` is one of: `queued | running | done | failed | cancelled`. `progress_pct` is computed as `(finished_ep_count / len(episode_indices)) * 100`, rounded to integer; absent (`null`) until at least one episode completes.

```
GET /api/jobs/{job_id}
→ 200 application/json
{
  "job_id": "...",
  "status": "running",
  "dataset": "SO101",
  "episode_indices": [0, 1, 2],
  "run_set": "so101_phase4_v5_2026-05-17",
  "variant": "4B",
  "started_at": "...",
  "progress_pct": 35,
  "current_episode_idx": 1,
  "log_tail": ["last 200 lines of stdout..."],
  "log_url": "/api/jobs/{job_id}/log",        // full log download
  "run_canonicals": [...],                     // updated as eps finish
  "error": null                                // populated on failed
}
```

```
GET /api/jobs/{job_id}/stream            (SSE)
event: progress
data: {"progress_pct": 36, "current_episode_idx": 1}

event: log
data: {"line": "[Phase 1] ep 1 boundaries=4"}

event: done | failed
data: {"final_status": "done", "run_canonicals": [...]}
```

```
GET /api/jobs/{job_id}/log
→ 200 text/plain  (full subprocess stdout/stderr)
```

```
DELETE /api/jobs/{job_id}
→ 204     // cancels if running; deletes record if done. SIGTERM the subprocess.
```

### 2.4 VLM dumps (U-A3)

```
GET /api/runs/{canonical}/vlm_dumps?run_set=<rs>
→ 200 application/json
{
  "canonical": "episode_000000__...",
  "calls": [
    { "call_id": "call_0001",
      "phase": "approach_object",
      "segment_id": 0,
      "prompt": "Describe the action ...",
      "raw_output": "{\"verb\": \"approach\", ...}",
      "parsed": { "verb": "approach", "object": "tape_roll", ... },
      "failed": false,
      "ms": 1240,
      "model_variant": "4B" },
    ...
  ]
}
```

Reads `runs/<rs>/<canonical>/_vlm_dumps/*.jsonl`. Missing dir → empty `calls`.

### 2.5 SAM3 masks (U-A4)

```
GET /api/runs/{canonical}/masks?frame=<N>&run_set=<rs>
→ 200 image/png         (RGBA, alpha = mask presence × per-track color)
→ 404 if no tracks.json
→ 204 if frame has no tracked objects
```

```
GET /api/runs/{canonical}/masks/meta?run_set=<rs>
→ 200 application/json
{ "frame_count": 151,
  "tracks": [{ "track_id": "t0", "label": "tape_roll", "color": "#ff8800",
               "first_frame": 12, "last_frame": 140 }] }
```

Implementation detail (U-A4 decides): on-the-fly rasterization from `tracks.json` polygons / RLE, or pre-bake to a sidecar PNG dir at annotate time. The contract is the same either way.

## 3. Sub-projects

Each sub-project below is a separate scope. The first row of each lists who depends on what — anyone whose `Depends on` is "contract only" can start as soon as this master spec is committed.

### 3.1 U-A1. Catalog + Job kick

- **Depends on:** existing `mimicanno serve` (GET routes), existing `scripts/batch_annotate_4B.py`.
- **Owns:** §2.1 (`datasets`), §2.3 (`jobs`), front-end pages `/datasets` and `/jobs`.
- **In scope:**
  - Backend job runner — subprocess wrapper, persistence under `.mimicanno-jobs/<id>.json` + `.log`, single-GPU queue, SSE stream.
  - Front-end: dataset list page, per-dataset episode table with per-ep run status, "Annotate" modal (pick robot config + pipeline config + run_set + ep subset) → POST /api/jobs, jobs page with live tail.
- **Out of scope (other sub-projects):**
  - dataset-level statistics dashboard → U-A2
  - VLM panel / mask overlay → U-A3 / U-A4
  - header badge → U-A5
- **Size:** medium-large (≈ 1 Claude session for spec + plan + impl).
- **Suggested sequencing:** ship the backend first so U-A2/3/4/5 can mock or hit it for parallel work.

### 3.2 U-A2. Dataset summary

- **Depends on:** §2.1 catalog contract, §2.2 summary contract (both frozen here).
- **Owns:** `/api/datasets/{name}/summary` backend; `/datasets/{name}` page dashboard tab.
- **In scope:**
  - Aggregate `annotation.json` per ep across the chosen run_set → label distribution, segment count stats, reviewed rate, per-ep mini-summary.
  - Frontend: bar chart of label distribution, table of per-ep stats, run_set selector.
- **Out of scope:** anything writing back (read-only).
- **Size:** small-medium. Can start once U-A1 backend stabilizes the §2.1 catalog shape.

### 3.3 U-A3. VLM dumps viewer

- **Depends on:** §2.4 (independent of jobs / catalog).
- **Owns:** `/api/runs/{canonical}/vlm_dumps` backend; RunViewer right side-panel "VLM" tab.
- **In scope:**
  - Read `_vlm_dumps/*.jsonl`, return as JSON.
  - Frontend tab inside RunViewer that lists calls, highlights the one matching the currently selected segment, shows prompt + raw + parsed.
- **Out of scope:** editing the dumps, re-running the planner. Read-only.
- **Size:** small. Fully parallel with U-A1.

### 3.4 U-A4. SAM3 mask overlay

- **Depends on:** §2.5 (independent).
- **Owns:** `/api/runs/{canonical}/masks` (+ `/masks/meta`) backend; canvas overlay component inside VideoPlayer.
- **In scope:**
  - Decide and implement: rasterize-on-the-fly OR pre-bake at annotate-time. The contract returns PNGs either way; if pre-bake is chosen, also amend the annotate pipeline to write the sidecar.
  - Frontend: track-color legend, per-track toggle, alpha control.
- **Out of scope:** editing masks. Read-only.
- **Size:** medium (rasterization design judgment required). Fully parallel with U-A1.

### 3.5 U-A5. Site-wide progress indicator

- **Depends on:** §2.3 jobs API (U-A1 backend must exist).
- **Owns:** small header component polling `GET /api/jobs?status=running`, "N running" badge linking to `/jobs`.
- **In scope:** the badge and click-through.
- **Out of scope:** richer notifications, error toast (deferred).
- **Size:** small. Comes after U-A1.

## 4. Parallel execution plan

```
Phase 1 (one Claude session, this repo):
   U-A1 — backend contract impl + catalog/jobs UI

Phase 2 (up to 3 Claudes in parallel; each uses its own branch):
   U-A2 — summary           (depends on U-A1 backend datasets shape)
   U-A3 — VLM dumps panel   (independent — start any time)
   U-A4 — mask overlay      (independent — start any time)

Phase 3 (one Claude):
   U-A5 — header badge
```

U-A3 and U-A4 can technically start before U-A1 finishes (they only depend on the contract frozen here), but they'll have nothing to plug into in the running UI until U-A1's frontend lands. Recommended pacing is "U-A1 backend → kick off U-A2/3/4 in parallel → U-A1 frontend lands → U-A5".

## 5. Common concerns

- **GPU queue:** single FIFO. `gpu_index` honored if multiple visible GPUs exist; otherwise ignored. New jobs while one runs go to `queued`.
- **Job persistence across server restart:** `.mimicanno-jobs/<id>.json` is the source of truth; on startup, jobs in `running` status whose subprocess PID no longer exists are reclassified `failed` with reason `"server_restart"`.
- **Log size:** subprocess output is appended to `.mimicanno-jobs/<id>.log`. `log_tail` returns last 200 lines; full log via `/log` route.
- **Test strategy:** backend uses existing `tests/server/conftest.py::tmp_runs_root_loadable` + new tmp `data/` fixtures. Frontend follows D r2 timing-test pattern (vitest + jsdom workarounds where needed).
- **Schema:** none of §2.1–§2.5 introduces new on-disk schema fields. If U-A4 chooses pre-bake, sidecar directory `_masks/` is documented at sub-project time.

## 6. Exit criteria (overall U-A initiative)

1. From `/datasets` a user can pick a dataset, click "Annotate", select robot+pipeline+ep subset, submit, and watch the job complete in `/jobs`.
2. After the job finishes, the resulting runs show up under `/runs` immediately.
3. From RunViewer the user sees the VLM panel (U-A3) and the SAM3 mask overlay (U-A4) for the current ep without manual page reload.
4. `/datasets/<name>` shows the dataset summary dashboard (U-A2).
5. The header badge (U-A5) reflects running-job count at most a few seconds out of date.
6. No regression in existing GET / PATCH routes or RunViewer behavior.

## 7. Out of scope (re-emphasized)

- Mode B (人手動画) — separate brainstorming.
- Upload from browser.
- Multi-user / auth.
- Cluster / multi-machine scheduling.
- Editing of VLM dumps or masks.
- Re-architecting the existing annotate pipeline.

## 8. Per-sub-project spec template

Each sub-project Claude should write its own spec at:
`docs/superpowers/specs/2026-05-XX-ua-<id>-design.md`
referencing this master file as parent, with sections at minimum:

- Scope (in/out, copy & narrow from §3.X above)
- Architecture (concrete file paths, classes, components)
- Test strategy
- Exit criteria (sub-project level, must imply progress toward §6)
- Open questions / risks
