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
   runs/<rs>/_vlm_dumps/<episode_id>/{_planner/call_NNN, s_NNN/attempt_M}/ ──▶
                                          GET /api/runs/{canonical}/vlm_dumps.json     (U-A3)
   runs/<rs>/<can>/_masks/<frame>.png ──▶ GET /api/runs/{canonical}/masks/{frame}.png (U-A4)
   (_masks/ is a pre-baked sidecar written at annotate time; rev3 §3.4)
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
GET /api/jobs[?status=<queued|running|done|failed|cancelled>]
   // status filter optional, may repeat (?status=queued&status=running). Used by U-A5.
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

### 2.4 VLM dumps (U-A3) — rev3 (corrected to match on-disk reality)

FastAPI's `{artifact}` in the catch-all `GET /api/runs/{name}/{artifact}` (at `mimicanno/server/routes.py` — grep `\"/api/runs/{name}/{artifact}\"` since line numbers drift) matches *any* string including `vlm_dumps.json`. The `.json` / `.png` suffix is for human readability; **disambiguation is purely by router registration order**. U-A3 backend MUST register this route **before** the catch-all.

**On-disk reality (NOT `*.jsonl` files — rev2 was wrong):**

```
runs/<rs>/_vlm_dumps/<episode_id>/
├── _planner/
│   └── call_NNN/                          # planner = one call per episode that proposes objects/targets
│       ├── prompt.txt
│       ├── response.txt                   # JSON: {"objects":[...],"targets":[...],"tools":[...]}
│       └── frame.png                      # single keyframe used as visual context
└── s_NNN/                                 # labeler = one segment, N=ordinal (0-based, ints zero-padded)
    └── attempt_M/                         # M >= 1, retries when last attempt rejected
        ├── prompt.txt
        ├── request.json                   # rich context: task_text, allowed_labels, segment_id, robot_state_summary, last_reject_reason, ...
        ├── response.txt                   # JSON: {"phase","verb","object","target","vlm_confidence","evidence"}
        └── keyframe_NN.png                # one to multiple keyframes (NN = 00..03 typical)
```

**Important: dumps are keyed by `episode_id`, NOT canonical hash dir.** Multiple canonical runs of the same episode (e.g., re-annotates with different config_hash) within one run_set share the same `_vlm_dumps/<episode_id>/` tree, and **the latest annotate overwrites earlier dumps**. Backend resolves canonical → episode_id via that canonical's `manifest.json` (`episode_id` field).

```
GET /api/runs/{canonical}/vlm_dumps.json?run_set=<rs>      // run_set REQUIRED (see §2.0)
→ 200 application/json
{
  "canonical": "episode_000000__...",
  "run_set": "so101_phase4_v5",
  "episode_id": "episode_000000",
  "calls": [
    { "kind": "planner",
      "call_id": "call_001",
      "attempt": 1,
      "prompt": "...",                     // prompt.txt contents
      "raw_output": "{\"objects\":[...],\"targets\":[...],\"tools\":[...]}",  // response.txt contents
      "parsed": { "objects": [...], "targets": [...], "tools": [...] },       // parsed if JSON valid, else null
      "failed": false,                     // planner never has multi-attempt; always false
      "frame_url": "/runs/<rs>/_vlm_dumps/<episode_id>/_planner/call_001/frame.png" },
    { "kind": "labeler",
      "call_id": "s_000__attempt_1",       // composite of segment ordinal + attempt
      "segment_ordinal": 0,                // int derived from "s_NNN" dir name (0-based); maps to annotation.segments[ordinal]
      "attempt": 1,
      "prompt": "...",
      "request_json": { ... },             // request.json contents (parsed)
      "raw_output": "{\"phase\":\"approach_object\",\"verb\":\"approach\",...}",
      "parsed": { "phase": "approach_object", "verb": "approach", "object": "tape_roll", "vlm_confidence": 0.87, "evidence": "..." },
      "failed": false,                     // true iff there exists a later attempt_M+1 dir for same s_NNN
      "keyframe_urls": ["/runs/<rs>/_vlm_dumps/<episode_id>/s_000/attempt_1/keyframe_00.png",
                        "/runs/<rs>/_vlm_dumps/<episode_id>/s_000/attempt_1/keyframe_01.png"] },
    ...
  ]
}
→ 400 if run_set query param is missing
→ 404 if (run_set, canonical) does not resolve to a run dir
→ 200 with empty `calls` if `_vlm_dumps/<episode_id>/` is absent (run was annotated without VLM dump capture)
```

**Field derivation notes:**

- `segment_ordinal = int(s_NNN_dir_name.split("_")[1])` (zero-padded ints). Maps to `annotation.segments[ordinal]` order — this is the in-memory order at planner time, NOT the same as `segment_id` after later smoother / human edits (which can reorder via splits/merges). Frontend MUST cross-reference by matching the segment's `phase`/`verb`/timing rather than relying on `segment_ordinal == segment_id` blindly.
- `failed` for labeler: `True` iff a later `attempt_(M+1)/` exists for the same `s_NNN`. Backend sorts attempts numerically and sets `failed=True` on all but the highest-numbered.
- `request_json` for labeler is the parsed `request.json` content. Optional (omit on planner kind).
- Removed from rev2: `ms`, `model_variant`, `phase` (as top-level field), `segment_id` (as raw int). `parsed.phase` and `parsed.verb` for labeler calls expose the same info.

Backend reader walks `runs/<rs>/_vlm_dumps/<episode_id>/`. Reads each `prompt.txt`/`response.txt`/`request.json` (best-effort: malformed JSON → `parsed: null`, missing file → empty string). Sorts planner calls by `call_id` numeric, then labeler entries by `(segment_ordinal, attempt)`.

### 2.5 SAM3 masks (U-A4) — rev3 (pre-bake confirmed; 204 semantics unified)

Same situation as §2.4: catch-all matches anything, so U-A4 backend MUST register these routes **before** the catch-all. The `.png` / `.json` suffixes are for human readability only.

**On-disk reality:** `tracks.json.samples[]` contains only `{bbox, frame, score, time_sec}` — **no RLE / polygon**. Per-frame masks DO exist in code (`mimicanno/object_tracker/propagator.py` populates `MaskCache.by_frame` during annotate) but are transient and discarded after `vlm_overlay` consumption. Rev3 mandates **pre-baking**: U-A4 amends the annotate pipeline to persist the masks as a sidecar PNG dir (see §3.4).

**Sidecar location:** `runs/<rs>/<canonical>/_masks/<frame>.png` (per-canonical, NOT shared like `_vlm_dumps/`).

```
GET /api/runs/{canonical}/masks/{frame}.png?run_set=<rs>   // run_set REQUIRED
→ 200 image/png         (RGBA, alpha = mask presence × per-track color)
→ 400 if run_set query param is missing or frame is not a non-negative int
→ 404 if (run_set, canonical) does not resolve to a run dir
→ 204 if (a) run dir has no `_masks/` sidecar (pre-rev3 / non-pre-baked run), OR
            (b) frame is in range but has no tracked objects in that frame.
            (i.e., 204 always means "valid query but no overlay content"; 404 only for path-resolution errors.)
```

```
GET /api/runs/{canonical}/masks/meta.json?run_set=<rs>     // run_set REQUIRED
→ 200 application/json
{ "canonical": "episode_000000__...",
  "run_set": "so101_phase4_v5",
  "frame_count": 151,                       // 0 if `_masks/` absent (legacy run)
  "tracks": [{ "track_id": "t0", "label": "tape_roll", "color": "#ff8800",
               "first_frame": 12, "last_frame": 140 }] }   // [] if `_masks/` absent
→ 400 if run_set query param is missing
→ 404 if (run_set, canonical) does not resolve to a run dir
                                          // NOTE: legacy runs without `_masks/` return 200 with empty fields
                                          // (consistent with §2.4 empty-`calls` behavior). Frontend can branch on
                                          // `frame_count == 0` to disable the overlay control.
```

**Backfill**: existing runs (annotated before rev3) lack `_masks/`. The contract gracefully returns 204 / empty-meta for those. A backfill CLI is a follow-up TODO (see §5).

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
- **Owns:** `/api/runs/{canonical}/vlm_dumps.json` backend; RunViewer right side-panel "VLM" tab.
- **In scope:**
  - Walk `runs/<rs>/_vlm_dumps/<episode_id>/` tree (resolving canonical → episode_id via the canonical's `manifest.json`), parse each `_planner/call_NNN/` and `s_NNN/attempt_M/` directory per §2.4, return the assembled `calls[]`. Static `.png` file paths under `_vlm_dumps/` are served by the existing run-artifact route or a sibling static handler — U-A3 chooses (no new HTTP surface beyond §2.4).
  - Frontend tab inside RunViewer that lists calls, highlights the labeler call whose parsed phase/verb matches the currently selected segment (NOT by raw `segment_ordinal`; see §2.4 derivation note), shows prompt + raw + parsed + keyframe thumbnails.
- **Out of scope:** editing the dumps, re-running the planner. Read-only. Image serving may be deferred to a follow-up if the existing static route doesn't cover `_vlm_dumps/*.png`.
- **Size:** small-medium. Fully parallel with U-A1.

### 3.4 U-A4. SAM3 mask overlay — rev3 (pre-bake confirmed)

- **Depends on:** §2.5 (independent).
- **Owns:** `/api/runs/{canonical}/masks/{frame}.png` + `/masks/meta.json` backend; canvas overlay component inside `VideoPlayer.tsx` (child slot only).
- **In scope (mandatory):**
  - **Annotate-pipeline amendment**: persist `MaskCache.by_frame` (populated in `mimicanno/object_tracker/propagator.py`, currently transient and consumed by `mimicanno/pipeline.py:881-998` `vlm_labeler` overlay) as `<canonical>/_masks/<frame>.png` (RGBA, alpha = mask presence × per-track palette color). Write site: post-mask_cache collection, pre-Stage 3 return. **Writes MUST go through the existing atomic-publish flow in `mimicanno/publish.py`** (write into temp scratch, then move into the published rundir) — never stream PNGs into the live dir.
  - Backend route reads `_masks/<frame>.png` directly (no on-the-fly rasterization).
  - `meta.json` derived from `tracks.json` (track ids + labels + first_frame/last_frame) plus enumeration of `_masks/*.png` for `frame_count`.
  - Frontend: track-color legend, per-track toggle, alpha control. Canvas overlay child of `VideoPlayer.tsx`.
- **Out of scope:** editing masks. On-the-fly rasterization (rev2 alternative dropped). Backfill of legacy runs (separate follow-up; see §5).
- **Size:** medium. The pipeline amendment is the bulk of the work; legacy runs return 204 / empty-meta (§2.5) so frontend degrades gracefully.

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
- **Schema (rev3):** `_masks/<frame>.png` sidecar is the only new on-disk artifact (added by U-A4 to the annotate pipeline; no annotation.json / manifest.json field added). `_vlm_dumps/` layout is unchanged — rev3 only corrects the spec's description to match what the planner has been writing all along.
- **Legacy-run backfill (follow-up TODO, not blocking U-A4):** a `mimicanno backfill-masks <run>` CLI to retroactively populate `_masks/` for runs annotated before rev3. Without it, the mask overlay silently degrades to 204 / empty-meta on pre-rev3 runs (graceful per §2.5). Track this as `U-A4-followup-backfill` in the project TODO; the U-A4 sub-Claude does NOT need to ship it.

## 6. Exit criteria (overall U-A initiative)

1. From `/datasets` a user can pick a dataset, click "Annotate", select robot+pipeline+ep subset, submit, and watch the job complete in `/jobs`.
2. After the job finishes, the resulting runs show up under `/runs` immediately.
3. From RunViewer the user sees the VLM panel (U-A3) and the SAM3 mask overlay (U-A4) for the current ep. (Mechanism: VLM panel fetches on segment selection change; mask overlay fetches per frame on time cursor change. Legacy pre-rev3 runs degrade gracefully — VLM empty `calls` if `_vlm_dumps/` absent, mask 204 / empty-meta if `_masks/` absent.)
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
