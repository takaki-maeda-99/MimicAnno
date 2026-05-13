"""Phase 5 A — FastAPI app factory (spec §3.2).

Wires the router (routes.py) + exception handlers (errors.py) + optional
CORS middleware. ``cors_origins`` is honoured strictly: empty list means
no middleware, no wildcard.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mimicanno.server.errors import install_handlers
from mimicanno.server.labelset import LabelSetCache
from mimicanno.server.routes import make_router


def create_app(
    *,
    runs_root: Path,
    cors_origins: list[str],
    labelset: LabelSetCache | None = None,
) -> FastAPI:
    if labelset is None:
        labelset = LabelSetCache.from_path()
    app = FastAPI(title="mimicanno persistence", openapi_url=None)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "HEAD"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    install_handlers(app)
    app.include_router(make_router(runs_root, labelset))
    return app
