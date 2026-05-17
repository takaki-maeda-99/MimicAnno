# U-A1: Catalog + Job Kick — sub-project design

Date: 2026-05-17
Author: U-A1 sub-Claude
Parent spec: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (master, frozen §2)

## 1. Scope

### In scope
- `GET /api/datasets` — dataset catalog (master §2.1)
- `GET /api/datasets/{name}` — per-dataset episode list with per-ep run metadata (master §2.1)
- `POST /api/jobs` — submit annotate job (master §2.3)
- `GET /api/jobs[?status=...]` — list jobs (master §2.3)
- `GET /api/jobs/{id}` — single job detail (master §2.3)
- `GET /api/jobs/{id}/stream` — SSE live progress (master §2.3)
- `GET /api/jobs/{id}/log` — full log download (master §2.3)
- `DELETE /api/jobs/{id}` — cancel/delete job (master §2.3)
- CORS: add `POST` and `DELETE` to `allow_methods` in `mimicanno/server/app.py`
- Progress marker: emit `[mimicanno-job-progress] ep=<idx> finished=<k>/<total>` in `scripts/batch_annotate_4B.py` and `mimicanno annotate`
- Frontend pages: `/datasets` (list + per-dataset episode table + Annotate modal), `/jobs` (list + live log tail)
- Server startup: reclassify `running` jobs with dead PID as `failed` (server_restart)
- `--jobs-dir` CLI flag for `mimicanno serve`

### Out of scope
- dataset-level summary dashboard (U-A2)
- VLM panel (U-A3), mask overlay (U-A4)
- header progress badge (U-A5)
- multi-machine/cluster scheduling
- browser upload

## 2. Architecture

### 2.1 New Python modules

**`mimicanno/server/catalog.py`** — dataset catalog scanner
- `scan_datasets(data_root: Path, runs_root: Path) -> list[DatasetInfo]`
- `get_dataset_detail(name: str, data_root: Path, runs_root: Path) -> DatasetDetail`
- Reads `data/{name}/meta/info.json` for ep_count, fps, video_path template
- Reads `data/{name}/meta/tasks.parquet` for task_text_hint (first task, or null)
- Scans `runs/` for run-sets (uses same logic as `runs_repo.list_run_sets`): dirs with `index.json` = run-set; bare canonical dirs at root = `__legacy__`
- `annotated_ep_count` = union of distinct episode_idx across all run-sets

**`mimicanno/server/job_store.py`** — job record dataclass + file persistence
- `JobRecord` dataclass: job_id, status, dataset, episode_indices, run_set, variant, gpu_index, robot_config, pipeline_config, started_at, finished_at, progress_pct, current_episode_idx, run_canonicals, error, pid, proc_start_time, log_url
- `JobStore(jobs_dir: Path)` — read/write `<id>.json`, list jobs, filter by status
- Atomic writes via tmp-rename pattern

**`mimicanno/server/job_runner.py`** — subprocess wrapper + per-GPU FIFO
- `JobQueue` — per-GPU asyncio.Queue; assign GPU with shortest queue on null gpu_index
- `start_runner(jobs_dir, data_root, runs_root, repo_root)` — background asyncio task
- Spawns `subprocess.Popen` for each job; tails `.log`; parses progress markers; writes `.json` updates
- On job completion (subprocess exit 0 → done, non-0 → failed): final `.json` update
- `cancel_job(job_id)` — SIGTERM the process, update status to `cancelled`

**`mimicanno/server/catalog_routes.py`** — FastAPI routes for datasets + jobs
- `make_catalog_router(data_root, runs_root, jobs_dir, job_queue)` → `APIRouter`
- All routes in §2.1 and §2.3 registered here
- SSE via `StreamingResponse` with `text/event-stream`

### 2.2 Modifications to existing files

- `mimicanno/server/app.py`:
  - Add `POST`, `DELETE` to `allow_methods`
  - Accept `jobs_dir: Path | None` kwarg, pass to `make_catalog_router`
  - `create_app` starts job runner task on startup (use `app.on_event("startup")`)

- `mimicanno/cli.py`:
  - `serve` command: add `--jobs-dir` option
  - `annotate` command: emit `[mimicanno-job-progress]` progress marker line after successful ep annotation

- `scripts/batch_annotate_4B.py`:
  - After `annotate_episode_phase4(req)` succeeds, print `[mimicanno-job-progress] ep=<i> finished=<k>/<total>`

### 2.3 Frontend

**`frontend/src/pages/DatasetsPage.tsx`** — new page
- Table: name, ep_count, annotated_ep_count, robot_hint, task_text_hint, last_modified
- Click row → expand to episode table (idx, video_path, runs[] with status badges)
- "Annotate" button → opens AnnotateModal

**`frontend/src/pages/DatasetsPage.tsx`** (inline modal component `AnnotateModal`)
- Form fields: run_set (text), robot_config (text), pipeline_config (text), episode_indices (text, comma-separated or "all"), gpu_index (number or auto), variant (select: 4B)
- Submit → POST /api/jobs → success: navigate to /jobs or show "job queued" toast

**`frontend/src/pages/JobsPage.tsx`** — new page
- List of jobs from GET /api/jobs; auto-refresh every 5s or use SSE per selected job
- Click job → detail panel with log tail (SSE /api/jobs/{id}/stream)
- Cancel button → DELETE /api/jobs/{id}

**Router registration**: add routes in `frontend/src/App.tsx` or equivalent router file.

### 2.4 Job ID format

`j_{YYYYMMDD}_{HHMMSS}_{4hex}` — e.g., `j_20260517_140523_a1b2`

### 2.5 On-disk layout

```
runs_root.parent/.mimicanno-jobs/
  j_20260517_140523_a1b2.json
  j_20260517_140523_a1b2.log
```

Overridable via `--jobs-dir <path>` on `mimicanno serve`.

### 2.6 Progress marker protocol

`scripts/batch_annotate_4B.py` emits to stdout after each episode:
```
[mimicanno-job-progress] ep=<episode_index> finished=<k>/<total>
```

`mimicanno annotate` (single-ep) emits at the end:
```
[mimicanno-job-progress] ep=<episode_index> finished=1/1
```

Job runner tails the `.log` file line-by-line (non-blocking read loop in asyncio), parses these, updates `.json`.

### 2.7 Server restart reclassification

On `create_app()` startup event:
- Load all `<id>.json` from jobs_dir
- For each with `status == "running"`:
  - Read `pid` and `proc_start_time` from record
  - Check `/proc/<pid>/stat` field 22 (start_time); if mismatch or no file → `status = "failed"`, `error = {"reason": "server_restart"}`
  - Write updated record

### 2.8 Re-annotate guard (409)

`POST /api/jobs` checks: for each episode_index in request, compute `canonical = episode_{idx:06d}__<run_hash_short>` pattern and check if the target `run_set` dir already contains a run for that episode. If so and `run_hash` matches an existing run, return 409 Conflict.

Simpler implementation: scan `runs/{run_set}/index.json` (if it exists) and check if any existing `episode_id` in the index covers the requested episodes. Return 409 if the run_set already has annotated episodes that overlap with the request.

## 3. Test strategy

### Backend tests (`tests/server/test_catalog*.py`, `tests/server/test_jobs*.py`)

**B1 — GET /api/datasets (8 tests)**
- Empty data_root → empty list
- One dataset, no runs → annotated_ep_count=0
- One dataset, one run-set with runs → correct annotated_ep_count
- Multiple run-sets → union counting
- `__legacy__` handling (bare canonical at runs root)
- robot_hint extracted from info.json.robot_type
- task_text_hint from tasks.parquet (mocked with fixture parquet)
- last_modified from meta/ dir mtime

**B2 — GET /api/datasets/{name} (5 tests)**
- Dataset not found → 404
- Dataset with no runs → episodes[].runs=[]
- Dataset with runs across multiple run-sets → correct runs[] per episode
- episode video_path and parquet_path from info.json template
- frame_count and fps from info.json

**B3 — JobRecord + JobStore (5 tests)**
- Write + read round-trip
- list_jobs with no filter
- list_jobs with status filter
- Atomic write (tmp-rename) doesn't leave corrupt file on read
- Log file: write lines, read_log_tail returns last 200

**B4 — POST /api/jobs (7 tests)**
- Valid body → 202, job_id returned, record written to disk
- episode_indices=null → all episodes
- gpu_index null → assigns GPU 0 (shortest queue)
- 409 when run_set already has overlapping runs
- 400 when dataset not found
- 400 when robot_config path doesn't exist
- Body validation: missing required fields → 422

**B5 — Job runner subprocess + FIFO (5 tests with mocked Popen)**
- Job transitions queued → running → done
- Progress marker parsing updates progress_pct
- Failed subprocess exit → status=failed
- Two jobs on same GPU serialize (second waits for first)
- Cancel (SIGTERM) → status=cancelled

**B6 — Progress marker emission (3 tests)**
- batch_annotate_4B.py emits marker on success (grep test with subprocess mock)
- batch_annotate_4B.py does NOT emit on failure
- `mimicanno annotate` CLI integration: check stdout line present

**B7 — GET /api/jobs, /api/jobs/{id}, /api/jobs/{id}/log, DELETE (7 tests)**
- GET /api/jobs returns all jobs
- GET /api/jobs?status=running filters correctly
- GET /api/jobs/{id} returns full detail with log_tail
- GET /api/jobs/{id}/log returns text/plain
- GET /api/jobs/{id} 404 for unknown id
- DELETE /api/jobs/{id} running job → cancelled
- DELETE /api/jobs/{id} done job → 204 record deleted

**B8 — SSE /api/jobs/{id}/stream (3 tests)**
- Closed job → sends done event + closes
- Keepalive comment emitted at configured interval
- Unknown job_id → 404

**B9 — Server restart reclassification (2 tests)**
- running job with dead PID → reclassified failed with server_restart reason
- running job with live PID matching proc_start_time → unchanged

**B10 — CORS allow_methods (2 tests)**
- OPTIONS preflight for POST /api/jobs returns Allow: POST
- OPTIONS preflight for DELETE /api/jobs/{id} returns Allow: DELETE

### Frontend tests (`frontend/src/pages/*.test.tsx`)

**F1 — DatasetsPage list (5 tests)**
- Renders dataset list from mocked GET /api/datasets
- Shows ep_count and annotated_ep_count per row
- Loading state while fetching
- Click row → fetches GET /api/datasets/{name}, shows episode table
- Error state on fetch failure

**F2 — AnnotateModal (4 tests)**
- Form renders with correct fields
- Submit fires POST /api/jobs with correct body
- 409 response shows user-friendly error
- Success redirects/shows toast

**F3 — JobsPage (4 tests)**
- Renders job list from mocked GET /api/jobs
- Status badge colors correct
- Click job → fetches job detail
- Cancel button fires DELETE /api/jobs/{id}

## 4. Exit criteria

1. `GET /api/datasets` lists all datasets under `data/` with correct annotated_ep_count.
2. `POST /api/jobs` submits a job and it transitions queued → running → done, with progress_pct updating.
3. `GET /api/jobs/{id}/stream` SSE client receives progress events and a terminal done/failed event.
4. `/datasets` and `/jobs` frontend pages are reachable and render data.
5. No regression in existing `GET /PATCH` routes (existing 237 tests all pass).
6. mypy --strict clean on `mimicanno/`.

## 5. Open questions / risks

- `tasks.parquet` may not be present in all datasets; fall back to null gracefully.
- `info.json` `robot_type` field may be "unknown" or missing; map to null.
- SSE in FastAPI with asyncio: keepalive timing may require careful loop design.
- `batch_annotate_4B.py` is a standalone script (not a module) with hardcoded paths; the job runner will invoke it as a subprocess, not import it.
- Frontend: vitest jsdom has known limitations with SSE; EventSource may need to be mocked.
- The `data/` tree on disk has real datasets but tests use tmp fixtures with synthetic data.
