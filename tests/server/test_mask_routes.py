"""U-A4: tests for mimicanno.server.mask_routes (T1 – T12).

T1  - GET meta.json → 200 with injected run_set
T2  - GET meta.json for legacy run (no _masks/) → 200 with frame_count=0
T3  - GET meta.json missing run_set → 400 run_set_required
T4  - GET meta.json path-traversal run_set → 400 invalid_run_set
T5  - GET meta.json unknown run_set → 404 run_set_not_found
T6  - GET meta.json unknown canonical → 404 canonical_not_found
T7  - GET masks/<frame> present PNG → 200 image/png
T8  - GET masks/<frame> no _masks/ sidecar → 204
T9  - GET masks/<frame> absent frame → 204
T10 - GET masks/<frame> bad frame (non-int) → 400 invalid_frame
T11 - GET masks/<frame> negative frame → 400 invalid_frame
T12 - mask routes must NOT fall through to the catch-all /api/runs/{name}/{artifact}
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mimicanno.object_tracker.mask_cache import MaskCache, assign_palette, encode_mask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(parent_root: Path) -> TestClient:
    from mimicanno.server.errors import install_handlers
    from mimicanno.server.mask_routes import make_mask_router

    app = FastAPI()
    install_handlers(app)
    app.include_router(make_mask_router(parent_root))
    return TestClient(app, raise_server_exceptions=False)


def _make_run_dir(parent_root: Path, run_set: str, canonical: str) -> Path:
    run_dir = parent_root / run_set / canonical
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_masks_sidecar(run_dir: Path) -> None:
    """Write a minimal _masks/ sidecar (frame 0, one prompt 'obj')."""
    from mimicanno.masks.sidecar import write_masks_sidecar

    h, w = 4, 4
    arr = np.zeros((h, w), dtype=bool)
    arr[0, 0] = True
    cache = MaskCache(
        by_frame={0: {"obj": encode_mask(arr)}},
        shape=(h, w),
        palette=assign_palette(["obj"]),
    )
    write_masks_sidecar(run_dir, cache, [], canonical="ep0")


# ---------------------------------------------------------------------------
# T1: GET meta.json → 200, run_set injected
# ---------------------------------------------------------------------------


def test_t1_meta_200_with_run_set(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, "rs1", "ep0")
    _write_masks_sidecar(run_dir)
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/meta.json?run_set=rs1")
    assert r.status_code == 200
    body = r.json()
    assert body["run_set"] == "rs1"
    assert body["canonical"] == "ep0"
    assert body["frame_count"] == 1


# ---------------------------------------------------------------------------
# T2: GET meta.json for legacy run (no _masks/) → 200, frame_count=0
# ---------------------------------------------------------------------------


def test_t2_meta_legacy_run(tmp_path: Path) -> None:
    _make_run_dir(tmp_path, "rs1", "ep_legacy")
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep_legacy/masks/meta.json?run_set=rs1")
    assert r.status_code == 200
    body = r.json()
    assert body["frame_count"] == 0
    assert body["tracks"] == []
    assert body["run_set"] == "rs1"


# ---------------------------------------------------------------------------
# T3: GET meta.json missing run_set → 400
# ---------------------------------------------------------------------------


def test_t3_meta_missing_run_set(tmp_path: Path) -> None:
    _make_run_dir(tmp_path, "rs1", "ep0")
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/meta.json")
    assert r.status_code == 400
    assert r.json()["error"] == "run_set_required"


# ---------------------------------------------------------------------------
# T4: GET meta.json path-traversal run_set → 400
# ---------------------------------------------------------------------------


def test_t4_meta_path_traversal(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/meta.json?run_set=../etc")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_run_set"


# ---------------------------------------------------------------------------
# T5: GET meta.json unknown run_set → 404
# ---------------------------------------------------------------------------


def test_t5_meta_unknown_run_set(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/meta.json?run_set=nonexistent")
    assert r.status_code == 404
    assert r.json()["error"] == "run_set_not_found"


# ---------------------------------------------------------------------------
# T6: GET meta.json unknown canonical → 404
# ---------------------------------------------------------------------------


def test_t6_meta_unknown_canonical(tmp_path: Path) -> None:
    (tmp_path / "rs1").mkdir()
    client = _make_client(tmp_path)

    r = client.get("/api/runs/unknown_ep/masks/meta.json?run_set=rs1")
    assert r.status_code == 404
    assert r.json()["error"] == "canonical_not_found"


# ---------------------------------------------------------------------------
# T7: GET masks/<frame> present PNG → 200 image/png
# ---------------------------------------------------------------------------


def test_t7_png_200(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, "rs1", "ep0")
    _write_masks_sidecar(run_dir)
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/0?run_set=rs1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # Should be a valid PNG (starts with PNG magic bytes)
    assert r.content[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# T8: GET masks/<frame> no _masks/ sidecar → 204
# ---------------------------------------------------------------------------


def test_t8_png_no_sidecar_204(tmp_path: Path) -> None:
    _make_run_dir(tmp_path, "rs1", "ep0")
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/0?run_set=rs1")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# T9: GET masks/<frame> absent frame → 204
# ---------------------------------------------------------------------------


def test_t9_png_absent_frame_204(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, "rs1", "ep0")
    _write_masks_sidecar(run_dir)  # writes frame 0 only
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/999?run_set=rs1")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# T10: GET masks/<frame> non-integer frame → 400
# ---------------------------------------------------------------------------


def test_t10_bad_frame_non_int(tmp_path: Path) -> None:
    _make_run_dir(tmp_path, "rs1", "ep0")
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/abc?run_set=rs1")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"


# ---------------------------------------------------------------------------
# T11: GET masks/<frame> negative frame → 400
# ---------------------------------------------------------------------------


def test_t11_negative_frame(tmp_path: Path) -> None:
    _make_run_dir(tmp_path, "rs1", "ep0")
    client = _make_client(tmp_path)

    r = client.get("/api/runs/ep0/masks/-1?run_set=rs1")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_frame"


# ---------------------------------------------------------------------------
# T12: mask routes registered before catch-all in make_router
# ---------------------------------------------------------------------------


def test_t12_routes_before_catch_all(tmp_path: Path) -> None:
    """T12: make_router registers mask routes BEFORE the catch-all {artifact}.

    Verify by checking that /api/runs/{canonical}/masks/meta.json in the
    full app (not just mask_routes in isolation) routes to the mask handler
    (returns JSON with 'frame_count') rather than the catch-all (which would
    return 404 trying to serve a file called 'masks/meta.json').
    """
    from mimicanno.server.errors import install_handlers
    from mimicanno.server.labelset import LabelSetCache
    from mimicanno.server.routes import make_router

    # Build a run-set with a run dir (no _masks/) so meta returns frame_count=0
    run_set = tmp_path / "rs1"
    run_set.mkdir()
    run_dir = run_set / "ep0"
    run_dir.mkdir()
    # write a minimal index.json so get_effective_root doesn't 404
    (run_set / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0", "runs": [],
    }))

    app = FastAPI()
    install_handlers(app)
    app.include_router(make_router(tmp_path, LabelSetCache.from_path()))
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/api/runs/ep0/masks/meta.json?run_set=rs1")
    # If catch-all intercepted, status would be 404 (file not found).
    # mask route returns 200 with JSON (frame_count=0 for legacy run).
    assert r.status_code == 200
    body = r.json()
    assert "frame_count" in body
