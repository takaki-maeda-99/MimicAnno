"""U-A1 — FastAPI routes for dataset catalog + job management (spec §2.1, §2.3).

Route registration order matters: these routes are all under /api/datasets and
/api/jobs, so there is no collision with the existing catch-all
GET /api/runs/{name}/{artifact}.

Include this router BEFORE the existing router in app.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from mimicanno.server.catalog import get_dataset_detail, scan_datasets
from mimicanno.server.errors import MimicAnnoHTTPError
from mimicanno.server.job_runner import JobQueue, JobRunner, SSE_KEEPALIVE_SEC
from mimicanno.server.job_store import JobError, JobRecord, JobStore

_LOG = logging.getLogger("mimicanno.server")

# Job ID format: j_YYYYMMDD_HHMMSS_4hex
_JOB_ID_RE = re.compile(r"^j_\d{8}_\d{6}_[a-f0-9]{4}$")

_VALID_STATUSES = frozenset({"queued", "running", "done", "failed", "cancelled"})
_VALID_VARIANTS = frozenset({"4B", "26B"})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_job_id() -> str:
    now = datetime.now(tz=timezone.utc)
    rnd = os.urandom(2).hex()
    return f"j_{now.strftime('%Y%m%d_%H%M%S')}_{rnd}"


def _job_summary(rec: JobRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "job_id": rec.job_id,
        "status": rec.status,
        "dataset": rec.dataset,
        "progress_pct": rec.progress_pct,
        "current_episode_idx": rec.current_episode_idx,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
        "run_canonicals": rec.run_canonicals,
    }
    return d


def _job_detail(rec: JobRecord, store: JobStore) -> dict[str, Any]:
    log_tail = store.read_log_tail(rec.job_id)
    d: dict[str, Any] = {
        "job_id": rec.job_id,
        "status": rec.status,
        "kind": rec.kind,
        "dataset": rec.dataset,
        "episode_indices": rec.episode_indices,
        "run_set": rec.run_set,
        "variant": rec.variant,
        "gpu_index": rec.gpu_index,
        "robot_config": rec.robot_config,
        "pipeline_config": rec.pipeline_config,
        "queued_at": rec.queued_at,
        "started_at": rec.started_at,
        "finished_at": rec.finished_at,
        "progress_pct": rec.progress_pct,
        "current_episode_idx": rec.current_episode_idx,
        "run_canonicals": rec.run_canonicals,
        "log_tail": log_tail,
        "log_url": f"/api/jobs/{rec.job_id}/log",
        "error": asdict(rec.error) if rec.error is not None else None,
    }
    return d


def _check_409_conflict(
    run_set: str, episode_indices: list[int], runs_root: Path
) -> bool:
    """Return True if the run_set already has runs for any of the requested episodes."""
    rs_dir = runs_root / run_set
    if not rs_dir.is_dir():
        return False
    index_path = rs_dir / "index.json"
    if not index_path.exists():
        return False
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    existing_ep_ids = {row.get("episode_id", "") for row in data.get("runs", [])}
    requested_ep_ids = {f"episode_{idx:06d}" for idx in episode_indices}
    return bool(existing_ep_ids & requested_ep_ids)


def make_catalog_router(
    data_root: Path,
    runs_root: Path,
    store: JobStore,
    queue: JobQueue,
    runner: JobRunner,
) -> APIRouter:
    """Build the catalog + jobs router."""
    router = APIRouter()

    # -----------------------------------------------------------------------
    # GET /api/datasets
    # -----------------------------------------------------------------------

    @router.get("/api/datasets")
    def list_datasets() -> Response:
        datasets = scan_datasets(data_root, runs_root)
        body: list[dict[str, Any]] = []
        for ds in datasets:
            body.append({
                "name": ds.name,
                "path": ds.path,
                "ep_count": ds.ep_count,
                "annotated_ep_count": ds.annotated_ep_count,
                "robot_hint": ds.robot_hint,
                "task_text_hint": ds.task_text_hint,
                "videos_root": ds.videos_root,
                "last_modified": ds.last_modified,
            })
        return Response(
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
        )

    # -----------------------------------------------------------------------
    # GET /api/datasets/{name}
    # -----------------------------------------------------------------------

    @router.get("/api/datasets/{name}")
    def get_dataset(name: str) -> Response:
        detail = get_dataset_detail(name, data_root, runs_root)
        if detail is None:
            raise MimicAnnoHTTPError(
                status=404, code="dataset_not_found",
                message=f"dataset {name!r} not found under {data_root}",
            )
        episodes_out: list[dict[str, Any]] = []
        for ep in detail.episodes:
            episodes_out.append({
                "idx": ep.idx,
                "video_path": ep.video_path,
                "parquet_path": ep.parquet_path,
                "frame_count": ep.frame_count,
                "fps": ep.fps,
                "runs": [
                    {
                        "canonical": r.canonical,
                        "run_hash": r.run_hash,
                        "run_set": r.run_set,
                        "pipeline_phase": r.pipeline_phase,
                        "generated_at": r.generated_at,
                    }
                    for r in ep.runs
                ],
            })
        body = {
            "name": detail.name,
            "path": detail.path,
            "episodes": episodes_out,
        }
        return Response(
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
        )

    # -----------------------------------------------------------------------
    # POST /api/jobs
    # -----------------------------------------------------------------------

    @router.post("/api/jobs", status_code=202)
    async def post_job(request: Request) -> Response:
        ct = (
            request.headers.get("content-type", "")
            .split(";")[0].strip().lower()
        )
        if ct != "application/json":
            raise MimicAnnoHTTPError(
                status=415, code="unsupported_media",
                message="Content-Type must be application/json",
            )

        raw = await request.body()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message=f"body must be valid JSON: {exc.msg}",
            )

        if not isinstance(body, dict):
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="body must be a JSON object",
            )

        # Required fields
        kind = body.get("kind", "annotate")
        dataset = body.get("dataset")
        run_set = body.get("run_set")
        robot_config = body.get("robot_config")
        pipeline_config = body.get("pipeline_config")
        episode_indices_raw = body.get("episode_indices")  # null/missing = all
        gpu_index_raw = body.get("gpu_index")  # null/missing = auto
        variant = body.get("variant", "4B")

        if not isinstance(dataset, str) or not dataset:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="'dataset' is required (non-empty string)",
            )
        if not isinstance(run_set, str) or not run_set:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="'run_set' is required (non-empty string)",
            )
        if not isinstance(robot_config, str) or not robot_config:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="'robot_config' is required (non-empty string)",
            )
        if not isinstance(pipeline_config, str) or not pipeline_config:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="'pipeline_config' is required (non-empty string)",
            )
        if variant not in _VALID_VARIANTS:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message=f"'variant' must be one of {sorted(_VALID_VARIANTS)}",
            )

        # Validate dataset exists
        dataset_dir = data_root / dataset
        if not dataset_dir.is_dir():
            raise MimicAnnoHTTPError(
                status=400, code="dataset_not_found",
                message=f"dataset {dataset!r} not found under {data_root}",
            )

        # Validate robot_config file exists
        rc_path = Path(robot_config)
        if not rc_path.is_absolute():
            rc_path = data_root.parent / robot_config  # repo-relative
        if not rc_path.exists():
            raise MimicAnnoHTTPError(
                status=400, code="robot_config_not_found",
                message=f"robot_config {robot_config!r} not found",
            )

        # Resolve episode indices
        if episode_indices_raw is None:
            # All episodes
            info_path = dataset_dir / "meta" / "info.json"
            try:
                info = json.loads(info_path.read_text()) if info_path.exists() else {}
                ep_count = info.get("total_episodes", 0)
            except Exception:
                ep_count = 0
            episode_indices = list(range(ep_count))
        else:
            if not isinstance(episode_indices_raw, list) or not all(
                isinstance(x, int) for x in episode_indices_raw
            ):
                raise MimicAnnoHTTPError(
                    status=400, code="invalid_body",
                    message="'episode_indices' must be a list of integers or null",
                )
            episode_indices = episode_indices_raw

        # GPU assignment
        if gpu_index_raw is not None and not isinstance(gpu_index_raw, int):
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="'gpu_index' must be an integer or null",
            )
        gpu_index = queue.assign_gpu(gpu_index_raw)

        # 409 conflict check
        if _check_409_conflict(run_set, episode_indices, runs_root):
            raise MimicAnnoHTTPError(
                status=409, code="run_set_conflict",
                message=(
                    f"run_set {run_set!r} already contains runs for the requested episodes. "
                    "Choose a different run_set name."
                ),
            )

        # Create job record
        job_id = _make_job_id()
        record = JobRecord(
            job_id=job_id,
            status="queued",
            kind=kind,
            dataset=dataset,
            episode_indices=episode_indices,
            run_set=run_set,
            variant=variant,
            gpu_index=gpu_index,
            robot_config=robot_config,
            pipeline_config=pipeline_config,
            queued_at=_now_iso(),
        )
        store.save(record)
        queue.enqueue(gpu_index, job_id)

        _LOG.info("enqueued job %s for dataset %s on GPU %d", job_id, dataset, gpu_index)

        return Response(
            content=json.dumps({"job_id": job_id, "status": "queued"}).encode(),
            media_type="application/json",
            status_code=202,
        )

    # -----------------------------------------------------------------------
    # GET /api/jobs
    # -----------------------------------------------------------------------

    @router.get("/api/jobs")
    def list_jobs(
        status: list[str] = Query(default=[]),
    ) -> Response:
        status_filter = list(status) if status else None
        records = store.list_all(status_filter=status_filter)
        body = [_job_summary(r) for r in records]
        return Response(
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
        )

    # -----------------------------------------------------------------------
    # GET /api/jobs/{job_id}
    # -----------------------------------------------------------------------

    @router.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> Response:
        rec = store.load(job_id)
        if rec is None:
            raise MimicAnnoHTTPError(
                status=404, code="job_not_found",
                message=f"job {job_id!r} not found",
            )
        return Response(
            content=json.dumps(_job_detail(rec, store), ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
        )

    # -----------------------------------------------------------------------
    # GET /api/jobs/{job_id}/stream  (SSE)
    # -----------------------------------------------------------------------

    @router.get("/api/jobs/{job_id}/stream")
    async def stream_job(job_id: str) -> StreamingResponse:
        rec = store.load(job_id)
        if rec is None:
            raise MimicAnnoHTTPError(
                status=404, code="job_not_found",
                message=f"job {job_id!r} not found",
            )

        async def _event_generator() -> Any:
            # If job is already terminal, send final event immediately.
            if rec.status in ("done", "failed", "cancelled"):
                data = json.dumps({
                    "final_status": rec.status,
                    "run_canonicals": rec.run_canonicals,
                })
                yield f"event: {rec.status}\ndata: {data}\n\n"
                return

            # Subscribe to live SSE events
            sub_q = runner.subscribe_sse(job_id)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(
                            sub_q.get(), timeout=SSE_KEEPALIVE_SEC
                        )
                    except asyncio.TimeoutError:
                        yield ":keepalive\n\n"
                        continue

                    if event is None:
                        # End of stream sentinel
                        break

                    etype = event.get("type", "")
                    if etype == "progress":
                        data = json.dumps({
                            "progress_pct": event.get("progress_pct"),
                            "current_episode_idx": event.get("current_episode_idx"),
                        })
                        yield f"event: progress\ndata: {data}\n\n"
                    elif etype == "log":
                        data = json.dumps({"line": event.get("line", "")})
                        yield f"event: log\ndata: {data}\n\n"
                    elif etype in ("done", "failed"):
                        data = json.dumps({
                            "final_status": event.get("final_status"),
                            "run_canonicals": event.get("run_canonicals", []),
                        })
                        yield f"event: {etype}\ndata: {data}\n\n"
                        break
            finally:
                runner.unsubscribe_sse(job_id, sub_q)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # -----------------------------------------------------------------------
    # GET /api/jobs/{job_id}/log
    # -----------------------------------------------------------------------

    @router.get("/api/jobs/{job_id}/log")
    def get_job_log(job_id: str) -> Response:
        rec = store.load(job_id)
        if rec is None:
            raise MimicAnnoHTTPError(
                status=404, code="job_not_found",
                message=f"job {job_id!r} not found",
            )
        log_text = store.read_log_full(job_id)
        return Response(
            content=log_text.encode("utf-8", errors="replace"),
            media_type="text/plain; charset=utf-8",
        )

    # -----------------------------------------------------------------------
    # DELETE /api/jobs/{job_id}
    # -----------------------------------------------------------------------

    @router.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: str) -> Response:
        rec = store.load(job_id)
        if rec is None:
            raise MimicAnnoHTTPError(
                status=404, code="job_not_found",
                message=f"job {job_id!r} not found",
            )
        if rec.status == "running":
            await runner.cancel_job(job_id)
        else:
            store.delete(job_id)
        return Response(status_code=204)

    return router
