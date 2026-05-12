"""Phase 5 A T2: server/errors.py + custom envelope handlers (spec §3.6)."""
from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _make_app(routes: list[Any]) -> FastAPI:
    """Build a minimal FastAPI app with handlers installed for the given
    list of (path, handler) pairs."""
    from mimicanno.server.errors import install_handlers
    app = FastAPI()
    install_handlers(app)
    for path, handler in routes:
        app.get(path)(handler)
    return app


def test_mimicanno_http_error_renders_envelope() -> None:
    """Spec §3.6: {error, message} shape, NOT FastAPI's {detail}."""
    from mimicanno.server.errors import MimicAnnoHTTPError

    def route() -> None:
        raise MimicAnnoHTTPError(status=404, code="run_not_found",
                                  message="no such run")

    client = TestClient(_make_app([("/x", route)]))
    r = client.get("/x")
    assert r.status_code == 404
    body = r.json()
    assert body == {"error": "run_not_found", "message": "no such run"}
    assert "detail" not in body  # FastAPI default key must be overridden


def test_http_exception_also_rewrapped_to_envelope() -> None:
    """A bare HTTPException must also produce the {error, message} shape so
    third-party FastAPI internals don't leak {detail} responses."""
    def route() -> None:
        raise HTTPException(status_code=400, detail="bad input")

    client = TestClient(_make_app([("/x", route)]))
    r = client.get("/x")
    assert r.status_code == 400
    body = r.json()
    assert body["message"] == "bad input"
    assert body["error"].startswith("http_")  # e.g. http_400


def test_unhandled_exception_returns_500_no_stack_leak() -> None:
    """Spec §3.6 / §3.7: 500 body must NOT contain stack trace text."""
    def route() -> None:
        raise RuntimeError("boom secret detail")

    client = TestClient(_make_app([("/x", route)]), raise_server_exceptions=False)
    r = client.get("/x")
    assert r.status_code == 500
    body_text = r.text
    assert "boom secret detail" not in body_text
    assert "Traceback" not in body_text
    assert "RuntimeError" not in body_text
    body = r.json()
    assert body["error"] == "internal"
    assert "stack" not in body and "traceback" not in body


def test_unhandled_exception_is_logged_with_stack(caplog: pytest.LogCaptureFixture) -> None:
    """The stack goes to the logger (so devs can debug), just not to the body."""
    def route() -> None:
        raise RuntimeError("inner boom")

    client = TestClient(_make_app([("/x", route)]), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="mimicanno.server"):
        client.get("/x")
    assert any("inner boom" in rec.message or "inner boom" in str(rec.exc_info)
               for rec in caplog.records), (
        "expected ERROR-level log with the original exception"
    )


def test_mimicanno_http_error_supports_3xx_5xx_status_codes() -> None:
    """Spec §3.6 has 400/404/500 entries; handler must not hard-code one."""
    from mimicanno.server.errors import MimicAnnoHTTPError

    def r400() -> None:
        raise MimicAnnoHTTPError(status=400, code="invalid_name",
                                  message="bad name")

    def r500() -> None:
        raise MimicAnnoHTTPError(status=500, code="internal",
                                  message="oops")

    app = _make_app([("/a", r400), ("/b", r500)])
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/a").status_code == 400
    assert client.get("/b").status_code == 500
