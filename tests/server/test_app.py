"""Phase 5 A T5: app.py factory + CORS middleware (spec §3.5)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_app_reachable(tmp_runs_root: Path) -> None:
    """Factory wires routes + error handlers; basic endpoint works."""
    from mimicanno.server.app import create_app
    client = TestClient(create_app(runs_root=tmp_runs_root, cors_origins=[]))
    r = client.get("/healthz")
    assert r.status_code == 200


def test_cors_preflight_allowed_origin(tmp_runs_root: Path) -> None:
    """Allowed origin sees Access-Control-Allow-Origin in preflight."""
    from mimicanno.server.app import create_app
    app = create_app(
        runs_root=tmp_runs_root,
        cors_origins=["http://localhost:5173"],
    )
    client = TestClient(app)
    r = client.options(
        "/api/runs/index.json",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_no_origin_configured(tmp_runs_root: Path) -> None:
    """Without --cors-origin, preflight emits no allow-origin header."""
    from mimicanno.server.app import create_app
    app = create_app(runs_root=tmp_runs_root, cors_origins=[])
    client = TestClient(app)
    r = client.options(
        "/api/runs/index.json",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Without middleware no Allow-Origin appears.
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_cors_disallowed_origin(tmp_runs_root: Path) -> None:
    """A request from an origin NOT in the allow-list gets no header."""
    from mimicanno.server.app import create_app
    app = create_app(
        runs_root=tmp_runs_root,
        cors_origins=["http://localhost:5173"],
    )
    client = TestClient(app)
    r = client.options(
        "/api/runs/index.json",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow = r.headers.get("access-control-allow-origin", "")
    assert allow != "http://evil.example"
    assert allow != "*"
