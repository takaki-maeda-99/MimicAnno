"""Phase 5 A — read-only routes (spec §3.3).

Two route families + /healthz:

- ``GET /api/runs/index.json`` → static-index pass-through (bytes)
- ``GET /api/runs/{name}/{artifact}`` → manifest is bytes (so we can compute
  the ETag); other artifacts stream via FileResponse to keep memory flat
  for 10 MB+ tracks.json (spec §4.1 #20).
- ``GET /healthz`` → liveness for uvicorn ``--reload`` and future E
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from mimicanno.server.errors import MimicAnnoHTTPError
from mimicanno.server.runs_repo import RunsRepository

_LOG = logging.getLogger("mimicanno.server")


def make_router(runs_root: Path) -> APIRouter:
    """Build a router bound to a specific runs root."""
    repo = RunsRepository(runs_root)
    resolved_root = repo.root

    def get_repo() -> RunsRepository:
        return repo

    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "runs_root": str(resolved_root)}

    @router.api_route("/api/runs/index.json", methods=["GET", "HEAD"])
    def get_index(r: RunsRepository = Depends(get_repo)) -> Response:
        return Response(content=r.read_index(), media_type="application/json")

    @router.api_route("/api/runs/{name}/{artifact}", methods=["GET", "HEAD"])
    def get_artifact(
        name: str,
        artifact: str,
        r: RunsRepository = Depends(get_repo),
    ) -> Response:
        path, body = r.open_artifact(name, artifact)
        headers: dict[str, str] = {"Cache-Control": "no-cache"}

        if artifact == "manifest.json":
            # body is guaranteed non-None here (open_artifact contract).
            assert body is not None
            # Parse for ETag. Failure (truncated JSON) raises and is caught
            # by the global Exception handler → 500 without stack leak.
            parsed = cast(dict[str, Any], json.loads(body))
            run_hash = parsed.get("run_hash")
            if isinstance(run_hash, str):
                headers["ETag"] = f'"{run_hash}"'
            return Response(
                content=body, headers=headers, media_type="application/json",
            )

        # Non-manifest: FileResponse streams.
        return FileResponse(
            path=path, headers=headers, media_type="application/json",
        )

    return router
