"""Phase 5 A — HTTP error envelope (spec 2026-05-12 §3.6).

FastAPI's default `{"detail": "..."}` shape is replaced with
`{"error": "<code>", "message": "<human>"}` so the server's contract with
the frontend is stable and machine-readable.

Generic `Exception` is caught and rendered as a 500 with NO stack trace
in the response body (spec §3.6 / §3.7). The full stack is logged at
ERROR level on the ``mimicanno.server`` logger.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


_LOG = logging.getLogger("mimicanno.server")


class MimicAnnoHTTPError(Exception):
    """Application-level HTTP error. Carries the status code and the
    ``{error, message}`` envelope fields directly so handlers stay trivial."""

    def __init__(self, *, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _envelope(*, code: str, message: str) -> dict[str, str]:
    return {"error": code, "message": message}


def install_handlers(app: FastAPI) -> None:
    """Register exception handlers that always emit the envelope shape.

    Starlette's ``add_exception_handler`` is typed as accepting only
    ``Callable[[Request, Exception], ...]`` — sub-class typed handlers
    are rejected by mypy. We therefore take ``Exception`` and narrow
    inside.
    """

    async def _mimicanno_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        assert isinstance(exc, MimicAnnoHTTPError)
        return JSONResponse(
            status_code=exc.status,
            content=_envelope(code=exc.code, message=exc.message),
        )

    async def _http_exception_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code=f"http_{exc.status_code}",
                message=detail,
            ),
        )

    async def _unhandled_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        # Log the full stack so developers can debug, but never leak it
        # into the response body (spec §3.6 / §3.7).
        _LOG.exception(
            "unhandled exception on %s %s", request.method, request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=_envelope(code="internal", message="unexpected error"),
        )

    app.add_exception_handler(MimicAnnoHTTPError, _mimicanno_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
