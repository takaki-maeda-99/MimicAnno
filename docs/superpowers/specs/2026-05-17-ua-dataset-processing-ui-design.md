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
   runs/<rs>/<can>/_vlm_dumps/*.jsonl ──▶ GET /api/runs/{canonical}/vlm_dumps.json     (U-A3)
   runs/<rs>/<can>/tracks.json (+masks) ──▶ GET /api/runs/{canonical}/masks/{frame}.png (U-A4)
```

Job submission and progress are the only stateful additions. Catalog, summary, vlm_dumps, and masks are pure read-side over existing filesystem artifacts.

## 2. Shared HTTP contract (frozen by this spec)

All endpoints are versioned under `/api/`. Sub-projects MUST implement / consume these exact shapes. Field-level additions are allowed (additive change) but not removals or renames without revising this spec.

### 2.0 Run-set scoping (applies to §2.1, §2.2, §2.4, §2.5)

`runs/` today contains a mix of run-set subdirectories (each holds its own `index.json` and multiple `<canonical>/` dirs) and bare `<canonical>/` directories at the top level (legacy single-mode runs). The contract handles this as follows:

- A **run-set** is any direct subdirectory of the runs root that contains an `index.json`. Anything else at the top level is treated as a legacy bare canonical and bucketed under the synthetic run_set name `__legacy__`.
- "**Most recent run_set**" (used as default in §2.2): the run-set whose `index.json` has the latest mtime. `__legacy__` is eligible.
- `annotated_ep_count` in §2.1 = number of distinct `episode_idx` values that have **at least one** run across **all** run-sets combined (union).
- Routes that operate on a single `<canonical>` (§2.4, §2.5) **require** `run_set` because canonical names are not unique across run-sets (e.g., `episode_000000__abcd1234` may exist in `so101_phase4_v5` and `so101_phase4_v4`).
- `run_set=__legacy__` selects bare canonical dirs at the top level.

### 2.0.1 CORS

U-A1 adds `POST` and `DELETE` to the `cors_origins` allow-list (currently `GET, HEAD, PATCH, OPTIONS`). Without this, browsers reject preflight on `/api/jobs`. This change is part of U-A1's scope and not optional.

### 2.1 Datasets

```
GET /api/datasets
→ 200 application/json
[
  {
    "name": "SO101",                              // dir name under data/
    "path": "data/SO101",                         // repo-relative
    "ep_count": 33,                               // episodes on disk
    "annotated_ep_count": 17,                     // see §2.0: union across all run-sets
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

Path is suffixed with `.json` to disambiguate from the existing catch-all `GET /api/runs/{name}/{artifact}` route at `mimicanno/server/routes.py:568` (which would otherwise match first and return 404 from `RunsRepository.open_artifact`). U-A3 backend MUST register this route **before** the catch-all in the router.

```
GET /api/runs/{canonical}/vlm_dumps.json?run_set=<rs>      // run_set REQUIRED (see §2.0)
→ 200 application/json
{
  "canonical": "episode_000000__...",
  "run_set": "so101_phase4_v5",
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
→ 400 if run_set query param is missing
→ 404 if (run_set, canonical) does not resolve to a run dir
```

Reads `runs/<rs>/<canonical>/_vlm_dumps/*.jsonl`. Missing dir (`_vlm_dumps/` not present, but run dir is) → empty `calls`.

### 2.5 SAM3 masks (U-A4)

Paths use file-suffixed shapes for the same reason as §2.4 (catch-all disambiguation). U-A4 backend registers these **before** the catch-all.

```
GET /api/runs/{canonical}/masks/{frame}.png?run_set=<rs>   // run_set REQUIRED
→ 200 image/png         (RGBA, alpha = mask presence × per-track color)
→ 400 if run_set query param is missing or frame is not a non-negative int
→ 404 if (run_set, canonical) does not resolve, or no tracks.json
→ 204 if frame is in range but has no tracked objects
```

```
GET /api/runs/{canonical}/masks/meta.json?run_set=<rs>     // run_set REQUIRED
→ 200 application/json
{ "canonical": "episode_000000__...",
  "run_set": "so101_phase4_v5",
  "frame_count": 151,
  "tracks": [{ "track_id": "t0", "label": "tape_roll", "color": "#ff8800",
               "first_frame": 12, "last_frame": 140 }] }
→ 400 if run_set query param is missing
→ 404 if (run_set, canonical) does not resolve to a run dir
```

Implementation detail (U-A4 decides): on-the-fly rasterization from `tracks.json` polygons / RLE, or pre-bake to a sidecar PNG dir at annotate time. The contract is the same either way. If pre-bake is chosen, the sidecar location is `runs/<rs>/<canonical>/_masks/<frame>.png` and U-A4 amends the annotate pipeline to write it.

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

- **GPU queue:** **per-GPU FIFO**. Each visible CUDA device has its own queue; jobs with the same `gpu_index` serialize, jobs with different `gpu_index` run concurrently. `gpu_index` omitted/null in POST body → server assigns the GPU with the shortest queue (ties → lowest index). Single-GPU hosts degenerate to a single global queue. Rationale: dl40 has multiple GPUs and we already run `gem4` chains on GPU 1 while doing other work on GPU 3.
- **Job state directory:** `.mimicanno-jobs/` lives at the **sibling** of `runs_root` (i.e., `runs_root.parent / ".mimicanno-jobs"`). Overridable via `mimicanno serve --jobs-dir <path>`. Created on demand. Contents: `<job_id>.json` (metadata) + `<job_id>.log` (full stdout/stderr).
- **Job persistence across server restart:** `.mimicanno-jobs/<id>.json` is the source of truth. On startup, jobs in `running` status whose recorded `pid` no longer exists (or whose `proc_start_time` does not match `/proc/<pid>/stat` field 22) are reclassified `failed` with `error: {"reason": "server_restart"}`.
- **Progress signal:** `progress_pct` is computed from a stable stdout marker that U-A1 introduces into `scripts/batch_annotate_4B.py` (and `mimicanno annotate`): one line per finished episode prefixed `[mimicanno-job-progress] ep=<idx> finished=<k>/<total>`. The job runner tails the log, parses these lines, and updates `.mimicanno-jobs/<id>.json`. No new schema on disk; only a stdout convention. SSE `progress` events fire when the parsed value changes.
- **SSE semantics:** server emits a `keepalive` comment line (`:keepalive\n\n`) every 15 s. Clients are expected to reconnect on drop with a fresh request; `Last-Event-ID` is **not** honored (events are not persistent — the latest job state is always retrievable via `GET /api/jobs/{id}`). Stream ends on the first `done` or `failed` event.
- **Re-annotate guard:** `POST /api/jobs` rejects (409 Conflict) when the target `(run_set, canonical)` already exists on disk and the existing manifest's `run_hash` would match. To re-annotate, the user picks a different `run_set`. This prevents races with PATCH writers on the existing run.
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
