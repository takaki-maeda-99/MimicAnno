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
from mimicanno.server.hands_routes import make_hands_router
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
) -> FastAPI:
    """Phase 5 A app factory + Phase 5 B r1 reviewer wiring (T7).

    ``reviewer`` is forwarded to the router so the PATCH route can stamp it
    into edited segments. ``hands_root`` enables the /api/hands/ routes;
    ``repo_root`` (defaults to Path.cwd()) is used to resolve video_source
    paths in meta.json.
    """
    if labelset is None:
        labelset = LabelSetCache.from_path()
    if repo_root is None:
        repo_root = Path.cwd()
    app = FastAPI(title="mimicanno persistence", openapi_url=None)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "HEAD", "PATCH", "OPTIONS"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    install_handlers(app)
    app.include_router(make_router(runs_root, labelset, reviewer))
    app.include_router(make_hands_router(hands_root, repo_root))
    return app
