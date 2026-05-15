"""Phase 5 A — read-only routes (spec §3.3).

Two route families + /healthz:

- ``GET /api/runs/index.json`` → static-index pass-through (bytes)
- ``GET /api/runs/{name}/{artifact}`` → manifest is bytes (so we can compute
  the ETag); other artifacts stream via FileResponse to keep memory flat
  for 10 MB+ tracks.json (spec §4.1 #20).
- ``GET /healthz`` → liveness for uvicorn ``--reload`` and future E
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response

from mimicanno.server.edit_repo import (
    EtagMismatch,
    InvalidLabel,
    InvalidSegment,
    RunNotFound,
    apply_edit,
)
from mimicanno.server.errors import MimicAnnoHTTPError
from mimicanno.server.labelset import LabelSetCache
from mimicanno.server.runs_repo import RunsRepository

_LOG = logging.getLogger("mimicanno.server")


def make_router(
    runs_root: Path,
    labelset: LabelSetCache,
    reviewer: str | None = None,
) -> APIRouter:
    """Build a router bound to a specific runs root + labelset.

    ``reviewer`` is captured in closure for the T8 PATCH route to use
    when stamping edits. Read endpoints don't reference it.
    """
    repo = RunsRepository(runs_root)
    resolved_root = repo.root

    def get_repo() -> RunsRepository:
        return repo

    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "runs_root": str(resolved_root)}

    @router.get("/api/labelset")
    def get_labelset() -> Response:
        body = labelset.to_response_dict()
        return Response(
            content=json.dumps(body).encode("utf-8"),
            media_type="application/json",
            headers={
                "ETag": f'"{labelset.ls.sha256}"',
                "Cache-Control": "public, max-age=300",
            },
        )

    @router.api_route("/api/runs/index.json", methods=["GET", "HEAD"])
    def get_index(r: RunsRepository = Depends(get_repo)) -> Response:
        return Response(content=r.read_index(), media_type="application/json")

    @router.api_route(
        "/api/runs/{name}/segments/{segment_id}",
        methods=["PATCH"],
    )
    async def patch_segment(
        name: str,
        segment_id: str,
        request: Request,
    ) -> Response:
        # Step 1: Content-Type (415). RFC 7231 case-insensitive.
        ct = (
            request.headers.get("content-type", "")
            .split(";")[0]
            .strip()
            .lower()
        )
        if ct != "application/json":
            raise MimicAnnoHTTPError(
                status=415, code="unsupported_media",
                message="Content-Type must be application/json",
            )

        # Step 2: If-Match (428). RFC 7232 quote-strip; weak tags
        # (W/"...") fall through to 412 on strict compare.
        if_match = request.headers.get("if-match", "")
        if not if_match:
            raise MimicAnnoHTTPError(
                status=428, code="etag_required",
                message="If-Match header is required",
            )
        if (
            len(if_match) >= 2
            and if_match[0] == '"'
            and if_match[-1] == '"'
        ):
            if_match = if_match[1:-1]

        # Step 3: Body parse + shape (400 invalid_body).
        raw_body = await request.body()
        try:
            body = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError as exc:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message=f"body must be valid JSON: {exc.msg}",
            )
        if (
            not isinstance(body, dict)
            or set(body.keys()) != {"phase"}
            or not isinstance(body.get("phase"), str)
        ):
            raise MimicAnnoHTTPError(
                status=400, code="invalid_body",
                message="body must be exactly {'phase': '<label_id>'}",
            )

        # Step 4: edit_repo.apply_edit + EditError → HTTP mapping.
        # T11: dispatch the blocking write to a threadpool worker so the
        # event loop stays responsive (otherwise PATCH would block
        # /healthz and other endpoints) AND so two concurrent PATCHes
        # race for the file_lock instead of being serialised at the
        # event-loop level.
        try:
            new_manifest = await asyncio.to_thread(
                apply_edit,
                runs_root=runs_root,
                name=name,
                segment_id=segment_id,
                new_phase=body["phase"],
                if_match=if_match,
                reviewer=reviewer,
                labelset=labelset.ls,
            )
        except RunNotFound:
            raise MimicAnnoHTTPError(
                status=404, code="run_not_found",
                message=f"run not found: {name!r}",
            )
        except EtagMismatch:
            raise MimicAnnoHTTPError(
                status=412, code="etag_mismatch",
                message="If-Match does not equal current manifest.run_hash",
            )
        except InvalidLabel:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_label",
                message=f"phase {body['phase']!r} is not in the labelset",
            )
        except InvalidSegment:
            raise MimicAnnoHTTPError(
                status=400, code="invalid_segment",
                message=f"segment_id {segment_id!r} not found in annotation",
            )

        # Step 5: 200 + new ETag.
        new_run_hash = new_manifest["run_hash"]
        return Response(
            content=json.dumps(new_manifest).encode("utf-8"),
            media_type="application/json",
            headers={
                "ETag": f'"{new_run_hash}"',
                "Cache-Control": "no-cache",
            },
        )

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
            else:
                # Surface the issue early: Phase 5 B's If-Match will silently
                # fall through to unconditional updates if ETag is missing.
                _LOG.warning(
                    "manifest %s/%s lacks run_hash; ETag header omitted",
                    name, artifact,
                )
            return Response(
                content=body, headers=headers, media_type="application/json",
            )

        # Non-manifest: FileResponse streams.
        return FileResponse(
            path=path, headers=headers, media_type="application/json",
        )

    return router
