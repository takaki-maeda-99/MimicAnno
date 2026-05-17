"""Phase 6: PATCH on a 0.3.0 annotation auto-bumps schema_version to 0.4.0.

D r2 backend B1 (f7f1579) introduced the auto-upgrade mechanism. After
Task 1's schema bump, that mechanism's target version becomes "0.4.0".
This file is a regression guard against future drift.

CRITICAL: the standard test harness writes annotation.json with the current
ARTIFACT_SCHEMA_VERSIONS["annotation"] value (now "0.4.0"). To exercise the
real upgrade path, each test must explicitly downgrade the on-disk
annotation.json to "0.3.0" BEFORE issuing the PATCH.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_manifest
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
from mimicanno.server.app import create_app
from tests.server.conftest import _LOADABLE_RUN_NAME, _build_loadable_fixture


def _client(runs_root: Path) -> TestClient:
    app = create_app(runs_root=runs_root, cors_origins=[])
    return TestClient(app)


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


def _set_annotation_schema_version(ann_path: Path, version: str) -> None:
    """Overwrite schema_version in the on-disk annotation.json.

    Used to force a specific schema_version before a PATCH call so we can
    verify the upgrade path independently of the frozen fixture's baseline.
    """
    ann_doc = json.loads(ann_path.read_text())
    ann_doc["schema_version"] = version
    ann_path.write_text(json.dumps(ann_doc))


# Fixture-specific IDs (same as test_history_old_new_values.py).
_SEG_ID_0 = "episode_000000__seg0000"
_SEG_ID_4 = "episode_000000__seg0004"
_SEG_ID_3 = "episode_000000__seg0003"
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"


@pytest.mark.parametrize(
    "route_id,url_suffix,body",
    [
        (
            "relabel",
            f"segments/{_SEG_ID_0}",
            {"phase": "grasp_object"},
        ),
        (
            "boundary",
            f"boundaries/{_BOUNDARY_ID_0_1}",
            {"frame": 15},
        ),
        (
            "reviewed",
            f"segments/{_SEG_ID_4}/reviewed",
            {"reviewed": True},
        ),
        (
            "labels",
            f"segments/{_SEG_ID_3}/labels",
            {"verb": "pick", "object": "tape", "target": None, "failure_flags": []},
        ),
    ],
)
def test_p11_p12_patch_upgrades_0_3_0_annotation_to_0_4_0(
    runs_root_with_loadable: Path,
    route_id: str,
    url_suffix: str,
    body: dict,
) -> None:
    """For each of the 4 PATCH routes, a fixture pre-loaded with
    schema_version='0.3.0' gets bumped to '0.4.0' after the PATCH.

    Regression guard: if any repo hardcodes a stale schema_version string
    instead of using ARTIFACT_SCHEMA_VERSIONS, this test will catch it.
    """
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    ann_path = root / name / "annotation.json"

    # 2. Force the on-disk annotation to 0.3.0 (the frozen fixture may be at a
    #    different version; we explicitly set it to test the 0.3.0 → 0.4.0 path).
    _set_annotation_schema_version(ann_path, "0.3.0")

    # Verify the downgrade took effect.
    assert json.loads(ann_path.read_text())["schema_version"] == "0.3.0", (
        "downgrade did not take effect before PATCH"
    )

    # 3. Issue the parametrized PATCH.
    rh = read_manifest(root / name / "manifest.json").run_hash
    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/{url_suffix}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps(body),
    )
    assert resp.status_code == 200, (
        f"[{route_id}] PATCH failed: {resp.status_code} {resp.text}"
    )

    # 4. Re-read annotation.json from disk; verify schema_version is now 0.4.0.
    ann_doc_after = json.loads(ann_path.read_text())
    assert ann_doc_after["schema_version"] == "0.4.0", (
        f"PATCH route '{route_id}' did not upgrade schema_version "
        f"(stayed at {ann_doc_after['schema_version']!r})"
    )
    # Also verify via the constant for future-proofness.
    assert ann_doc_after["schema_version"] == ARTIFACT_SCHEMA_VERSIONS["annotation"], (
        f"PATCH route '{route_id}' schema_version {ann_doc_after['schema_version']!r} "
        f"does not match ARTIFACT_SCHEMA_VERSIONS['annotation'] "
        f"{ARTIFACT_SCHEMA_VERSIONS['annotation']!r}"
    )
