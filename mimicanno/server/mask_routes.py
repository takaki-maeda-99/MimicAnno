"""U-A4 — SAM3 mask overlay backend routes.

Registers two routes (MUST be included before the catch-all
``/api/runs/{name}/{artifact}`` in make_router):

- ``GET /api/runs/{canonical}/masks/meta.json?run_set=<rs>``
  Returns track metadata; ``run_set`` is injected at read time.

- ``GET /api/runs/{canonical}/masks/{frame}?run_set=<rs>``
  Returns the RGBA PNG for the given frame (as a 6-digit zero-padded
  integer), or 204 when no sidecar exists or the frame is absent.

Both routes return 400 for missing/invalid ``run_set`` and 404 for
unknown run-set directories or canonical names.

Security: ``run_set`` and ``canonical`` are validated to prevent
path traversal (same guards as the vlm_dumps route in routes.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from mimicanno.masks.sidecar import png_path_for_frame, read_mask_meta
from mimicanno.server.errors import MimicAnnoHTTPError

_CANONICAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")


def _resolve_run_dir(
    parent_root: Path,
    canonical: str,
    run_set: str | None,
) -> Path:
    """Validate inputs and return the run directory path.

    Raises :class:`MimicAnnoHTTPError` for all invalid inputs.
    """
    if run_set is None:
        raise MimicAnnoHTTPError(
            status=400,
            code="run_set_required",
            message="run_set query parameter is required",
        )
    # Reject path-traversal attempts.
    if run_set in ("..", ".") or Path(run_set).name != run_set:
        raise MimicAnnoHTTPError(
            status=400,
            code="invalid_run_set",
            message=f"run_set {run_set!r} is not a direct subdirectory",
        )
    if not _CANONICAL_RE.match(canonical):
        raise MimicAnnoHTTPError(
            status=400,
            code="invalid_canonical",
            message=f"canonical {canonical!r} contains invalid characters",
        )
    run_set_dir = parent_root / run_set
    if not run_set_dir.is_dir():
        raise MimicAnnoHTTPError(
            status=404,
            code="run_set_not_found",
            message=f"run_set {run_set!r} not found",
        )
    run_dir = run_set_dir / canonical
    if not run_dir.is_dir():
        raise MimicAnnoHTTPError(
            status=404,
            code="canonical_not_found",
            message=f"canonical {canonical!r} not found in run_set {run_set!r}",
        )
    return run_dir


def make_mask_router(parent_root: Path) -> APIRouter:
    """Return an APIRouter with both mask routes bound to *parent_root*."""
    router: APIRouter = APIRouter()

    @router.get("/api/runs/{canonical}/masks/meta.json")
    def get_mask_meta(
        canonical: str,
        run_set: str | None = Query(None, alias="run_set"),
    ) -> Response:
        run_dir = _resolve_run_dir(parent_root, canonical, run_set)
        assert run_set is not None  # _resolve_run_dir already validated
        meta = read_mask_meta(run_dir, canonical, run_set)
        return Response(
            content=json.dumps(meta),
            media_type="application/json",
            headers={"Cache-Control": "no-cache"},
        )

    @router.get("/api/runs/{canonical}/masks/{frame}")
    def get_mask_png(
        canonical: str,
        frame: str,
        run_set: str | None = Query(None, alias="run_set"),
    ) -> Response:
        run_dir = _resolve_run_dir(parent_root, canonical, run_set)

        # Validate frame is a non-negative integer.
        try:
            frame_int = int(frame)
            if frame_int < 0:
                raise ValueError("negative")
        except ValueError:
            raise MimicAnnoHTTPError(
                status=400,
                code="invalid_frame",
                message=f"frame {frame!r} must be a non-negative integer",
            )

        masks_dir = run_dir / "_masks"
        if not masks_dir.is_dir():
            # Legacy run — no sidecar. Return 204 No Content.
            return Response(status_code=204)

        png_path = png_path_for_frame(masks_dir, frame_int)
        if not png_path.exists():
            # Frame not cached (e.g., non-keyframe or gap). Return 204.
            return Response(status_code=204)

        return FileResponse(
            path=png_path,
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    return router
