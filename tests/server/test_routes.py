"""Phase 5 A T4: routes.py — 17 unit cases per spec §4.1 (CORS-less).

CORS 3 cases live in test_app.py (T5) because they require middleware.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(runs_root: Path) -> TestClient:
    """Minimal app for route-level tests (no CORS, errors installed)."""
    from mimicanno.server.errors import install_handlers
    from mimicanno.server.labelset import LabelSetCache
    from mimicanno.server.routes import make_router
    app = FastAPI()
    install_handlers(app)
    app.include_router(
        make_router(runs_root, LabelSetCache.from_path(), reviewer=None),
    )
    return TestClient(app, raise_server_exceptions=False)


# ----- 1-3: /api/runs/index.json -----


def test_1_get_index_returns_200_json(tmp_runs_root: Path) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get("/api/runs/index.json")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "0.1.0"
    assert len(body["runs"]) == 1
    assert r.headers["content-type"].startswith("application/json")


def test_2_get_index_404_when_missing(runs_root_no_index: Path) -> None:
    client = _make_client(runs_root_no_index)
    r = client.get("/api/runs/index.json")
    assert r.status_code == 404
    assert r.json()["error"] == "index_missing"


def test_3_get_index_empty_runs_returns_200(empty_runs_root: Path) -> None:
    client = _make_client(empty_runs_root)
    r = client.get("/api/runs/index.json")
    assert r.status_code == 200
    assert r.json()["runs"] == []


# ----- 4-7: /api/runs/{name}/{artifact} -----


def test_4_get_manifest_200_with_etag(
    tmp_runs_root: Path, canonical_name: str, known_run_hash: str,
) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 200
    assert r.json()["run_hash"] == known_run_hash
    assert r.headers.get("etag") == f'"{known_run_hash}"'
    assert r.headers.get("cache-control") == "no-cache"


def test_5_get_manifest_404_when_run_missing(tmp_runs_root: Path) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get("/api/runs/episode_999999__nonexistent/manifest.json")
    assert r.status_code == 404
    assert r.json()["error"] == "run_not_found"


def test_6_get_boundaries_200(
    tmp_runs_root: Path, canonical_name: str, known_run_hash: str,
) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/boundaries.json")
    assert r.status_code == 200
    assert r.json() == {"file": "boundaries.json"}
    # Non-manifest artifacts go through FileResponse, which may emit its own
    # inode-based ETag — that's fine because B's If-Match only cares about
    # the manifest's run_hash. We just assert the ETag is NOT the run_hash
    # (which is reserved for manifest.json per spec §3.3).
    assert r.headers.get("etag", "") != f'"{known_run_hash}"'


def test_7_get_artifact_404_when_not_in_allowlist(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/video.mp4")
    assert r.status_code == 404
    assert r.json()["error"] == "artifact_not_found"


# ----- 8-11: security (traversal) -----


def test_8_invalid_canonical_name_400(tmp_runs_root: Path) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get("/api/runs/has space/manifest.json")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_name"


def test_9_literal_traversal_blocked(tmp_runs_root: Path) -> None:
    """A literal `..` in the URL is collapsed by FastAPI/Starlette routing;
    if it ever isn't, our regex + is_relative_to MUST reject."""
    client = _make_client(tmp_runs_root)
    # Starlette typically normalises this to /api/etc/passwd which then 404s
    # at routing. The point is we never return 200 with /etc/passwd content.
    r = client.get("/api/runs/..%2F..%2Fetc/manifest.json")
    assert r.status_code in (400, 404)
    if r.status_code == 400:
        assert r.json()["error"] == "invalid_name"


def test_10_percent_encoded_traversal_blocked(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """`%2F` is the percent-encoding for `/`. ASGI normalises this to a
    literal `/`, splitting the path — so the artifact param contains a
    `/` which doesn't match `[A-Za-z0-9_]+` (the path param matches one
    segment) and would 404 at routing. Either way: NEVER 200."""
    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/..%2Fmanifest.json")
    assert r.status_code in (400, 404)


def test_11_symlink_escape_blocked(
    tmp_runs_root: Path, canonical_name: str, tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"file": "outside-secret"}))
    art = tmp_runs_root / canonical_name / "annotation.json"
    art.unlink()
    art.symlink_to(outside)

    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/annotation.json")
    assert r.status_code == 404
    assert r.json()["error"] == "artifact_not_found"


# ----- 12: truncated JSON → 500 no stack -----


def test_12_truncated_manifest_returns_500_no_stack(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """If manifest.json is malformed, ETag computation raises. Spec §3.6:
    body must not contain the stack."""
    (tmp_runs_root / canonical_name / "manifest.json").write_text('{"run_hash":')
    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 500
    assert r.json()["error"] == "internal"
    assert "Traceback" not in r.text
    assert "JSONDecodeError" not in r.text


# ----- 13-14: dir-gap retry -----


def test_13_dirgap_retry_succeeds(
    tmp_runs_root: Path, canonical_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mimicanno.server import runs_repo as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    real_read_bytes = Path.read_bytes
    calls = {"n": 0}

    def fake_read_bytes(self: Path) -> bytes:
        if self.name == "manifest.json" and calls["n"] < 2:
            calls["n"] += 1
            raise FileNotFoundError(self)
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 200
    assert calls["n"] == 2


def test_14_dirgap_retry_exhausted_404(
    tmp_runs_root: Path, canonical_name: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mimicanno.server import runs_repo as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    def always_missing(self: Path) -> bytes:
        if self.name == "manifest.json":
            raise FileNotFoundError(self)
        return b"{}"

    monkeypatch.setattr(Path, "read_bytes", always_missing)

    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 404
    assert r.json()["error"] == "run_not_found"


# ----- 15: /healthz -----


def test_15_healthz_returns_ok(tmp_runs_root: Path) -> None:
    client = _make_client(tmp_runs_root)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["runs_root"] == str(tmp_runs_root.resolve())


# ----- 16: HEAD -----


def test_16_head_manifest(
    tmp_runs_root: Path, canonical_name: str, known_run_hash: str,
) -> None:
    client = _make_client(tmp_runs_root)
    r = client.head(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 200
    assert r.headers.get("etag") == f'"{known_run_hash}"'
    assert r.content == b""


# ----- 17: large file streaming -----


def test_17_large_artifact_uses_filestream(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """Non-manifest artifacts go through FileResponse so memory doesn't
    balloon for 10MB+ tracks.json (spec §4.1 #20).

    We assert the response stream actually delivers the right bytes; a
    deeper "memory not loaded" test would need profiling and is overkill.
    The route choice (FileResponse for non-manifest) is exercised by
    test_open_artifact_non_manifest_returns_path_only in test_runs_repo.
    """
    big = (tmp_runs_root / canonical_name / "tracks.json")
    # 1MB of JSON-ish payload — enough to exercise streaming chunking
    big.write_text('{"data":"' + ("x" * (1024 * 1024)) + '"}')

    client = _make_client(tmp_runs_root)
    r = client.get(f"/api/runs/{canonical_name}/tracks.json")
    assert r.status_code == 200
    assert len(r.content) > 1024 * 1024
    assert r.headers.get("cache-control") == "no-cache"


# ----- follow-up (2026-05-13 review): explicit HEAD on non-manifest -----


def test_18_head_non_manifest(
    tmp_runs_root: Path, canonical_name: str,
) -> None:
    """HEAD on a non-manifest artifact must succeed with empty body and the
    same content-type / cache-control headers as GET."""
    client = _make_client(tmp_runs_root)
    r = client.head(f"/api/runs/{canonical_name}/boundaries.json")
    assert r.status_code == 200
    assert r.content == b""
    assert r.headers.get("cache-control") == "no-cache"


# ----- follow-up: ETag fallback when run_hash is missing -----


def test_19_manifest_without_run_hash_no_etag_with_warning(
    tmp_runs_root: Path, canonical_name: str, caplog: pytest.LogCaptureFixture,
) -> None:
    """A manifest that lacks ``run_hash`` (or has a non-string value) must
    still serve 200 but emit no ETag header. The omission is logged at
    WARNING on ``mimicanno.server`` so Phase 5 B's If-Match contract issues
    surface early (review finding 2026-05-13)."""
    import json as _json
    import logging
    mani_path = tmp_runs_root / canonical_name / "manifest.json"
    parsed = _json.loads(mani_path.read_text())
    del parsed["run_hash"]
    mani_path.write_text(_json.dumps(parsed))

    client = _make_client(tmp_runs_root)
    with caplog.at_level(logging.WARNING, logger="mimicanno.server"):
        r = client.get(f"/api/runs/{canonical_name}/manifest.json")
    assert r.status_code == 200
    assert "etag" not in {k.lower() for k in r.headers}
    assert any("run_hash" in rec.message for rec in caplog.records)
