"""Phase 5 A — FastAPI app factory (spec §3.2).

Wires the router (routes.py) + exception handlers (errors.py) + optional
CORS middleware. ``cors_origins`` is honoured strictly: empty list means
no middleware, no wildcard.

U-A1: also wires the catalog + jobs router (catalog_routes.py) and starts
the job runner background task on startup. CORS allow_methods includes POST
and DELETE for the /api/jobs endpoints.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mimicanno.server.catalog_routes import make_catalog_router
from mimicanno.server.errors import install_handlers
from mimicanno.server.hands_routes import make_hands_router
from mimicanno.server.job_runner import JobQueue, JobRunner, reclassify_stale_running_jobs
from mimicanno.server.job_store import JobStore
from mimicanno.server.labelset import LabelSetCache
from mimicanno.server.routes import make_router


def create_app(
    *,
    runs_root: Path,
    cors_origins: list[str],
    reviewer: str | None = None,
    labelset: LabelSetCache | None = None,
    hands_root: Path | None = None,
    repo_root: Path | None = None,
    jobs_dir: Path | None = None,
    data_root: Path | None = None,
    num_gpus: int = 1,
) -> FastAPI:
    """Phase 5 A app factory + Phase 5 B r1 reviewer wiring (T7).

    ``reviewer`` is forwarded to the router so the PATCH route can stamp it
    into edited segments. ``hands_root`` enables the /api/hands/ routes;
    ``repo_root`` (defaults to Path.cwd()) is used to resolve video_source
    paths in meta.json.

    U-A1 additions:
    ``jobs_dir`` — directory for job records (default: runs_root.parent / ".mimicanno-jobs").
    ``data_root`` — root of datasets (default: repo_root / "data").
    ``num_gpus`` — number of GPU queues to create.
    """
    if labelset is None:
        labelset = LabelSetCache.from_path()
    if repo_root is None:
        repo_root = Path.cwd()
    if jobs_dir is None:
        jobs_dir = runs_root.parent / ".mimicanno-jobs"
    if data_root is None:
        data_root = repo_root / "data"

    app = FastAPI(title="mimicanno persistence", openapi_url=None)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            # U-A1: POST and DELETE added for /api/jobs
            allow_methods=["GET", "HEAD", "PATCH", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    install_handlers(app)

    # U-A1: Build job infrastructure
    store = JobStore(jobs_dir)
    job_queue = JobQueue(num_gpus=num_gpus)
    runner = JobRunner(store=store, queue=job_queue, repo_root=repo_root)

    # U-A1: Include catalog router BEFORE the existing catch-all
    app.include_router(
        make_catalog_router(data_root, runs_root, store, job_queue, runner)
    )
    app.include_router(make_router(runs_root, labelset, reviewer))
    app.include_router(make_hands_router(hands_root, repo_root))

    # U-A1: On startup, reclassify stale running jobs + start GPU workers
    @app.on_event("startup")
    async def startup_event() -> None:
        reclassify_stale_running_jobs(store)
        await runner.start_workers()

    return app
