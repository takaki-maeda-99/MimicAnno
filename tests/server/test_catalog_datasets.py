"""U-A1 B1+B2 — GET /api/datasets and GET /api/datasets/{name} tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.server.catalog import scan_datasets, get_dataset_detail
from mimicanno.server.job_runner import JobQueue, JobRunner
from mimicanno.server.job_store import JobStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_dataset(root: Path, name: str, ep_count: int, robot_type: str = "unknown") -> Path:
    """Create a minimal LeRobot v3 dataset structure."""
    ds = root / name
    ds.mkdir(parents=True)
    meta = ds / "meta"
    meta.mkdir()
    info = {
        "robot_type": robot_type,
        "total_episodes": ep_count,
        "fps": 15,
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": {
            "observation.images.front": {"dtype": "video"},
        },
    }
    (meta / "info.json").write_text(json.dumps(info))
    return ds


def _make_run_set(runs_root: Path, rs_name: str, episode_ids: list[str]) -> None:
    """Create a run-set subdirectory with index.json entries."""
    rs_dir = runs_root / rs_name
    rs_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for ep_id in episode_ids:
        canonical = f"{ep_id}__abc123def456"
        (rs_dir / canonical).mkdir(exist_ok=True)
        runs.append({
            "episode_id": ep_id,
            "canonical_name": canonical,
            "run_hash": "sha256:" + "a" * 64,
            "run_hash_short": "abc123def456",
            "config_hash_short": "deadbeef",
            "input_hash_short": "cafebabe",
            "generated_at": "2026-05-17T10:00:00Z",
            "manifest_url": f"{canonical}/manifest.json",
            "pipeline_phase": 4,
            "task_text": "test task",
        })
    index = {"schema_version": "0.1.0", "runs": runs}
    (rs_dir / "index.json").write_text(json.dumps(index))


def _make_app_with(data_root: Path, runs_root: Path) -> "TestClient":
    """Build a TestClient with the catalog router."""
    from mimicanno.server.app import create_app
    fastapi_app = create_app(
        runs_root=runs_root,
        cors_origins=[],
        jobs_dir=runs_root.parent / ".jobs",
        data_root=data_root,
    )
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# B1 — GET /api/datasets
# ---------------------------------------------------------------------------

def test_list_datasets_empty_data_root(tmp_path: Path) -> None:
    """Empty data_root → empty list."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_datasets_one_dataset_no_runs(tmp_path: Path) -> None:
    """One dataset, no runs → annotated_ep_count=0."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=5)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    ds = body[0]
    assert ds["name"] == "SO101"
    assert ds["ep_count"] == 5
    assert ds["annotated_ep_count"] == 0
    assert ds["path"] == "data/SO101"


def test_list_datasets_with_run_set(tmp_path: Path) -> None:
    """One dataset + one run-set with 3 annotated episodes."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=10)
    _make_run_set(runs_root, "so101_v5", ["episode_000000", "episode_000001", "episode_000002"])
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    assert resp.status_code == 200
    body = resp.json()
    ds = body[0]
    assert ds["annotated_ep_count"] == 3


def test_list_datasets_union_across_run_sets(tmp_path: Path) -> None:
    """Multiple run-sets: union of annotated episodes (no double counting)."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=10)
    _make_run_set(runs_root, "so101_v4", ["episode_000000", "episode_000001"])
    _make_run_set(runs_root, "so101_v5", ["episode_000001", "episode_000002"])  # ep1 overlap
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    body = resp.json()
    ds = body[0]
    assert ds["annotated_ep_count"] == 3  # 0, 1, 2 (not 4)


def test_list_datasets_robot_hint_from_info(tmp_path: Path) -> None:
    """robot_hint extracted from info.json.robot_type; 'unknown' → null."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=5, robot_type="so101")
    _make_dataset(data_root, "Piper", ep_count=3, robot_type="unknown")
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    body = {ds["name"]: ds for ds in resp.json()}
    assert body["SO101"]["robot_hint"] == "so101"
    assert body["Piper"]["robot_hint"] is None


def test_list_datasets_last_modified_present(tmp_path: Path) -> None:
    """last_modified field is a non-empty ISO string."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=1)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    body = resp.json()
    assert body[0]["last_modified"]  # non-empty string
    # Should look like an ISO timestamp
    assert "T" in body[0]["last_modified"]


def test_list_datasets_legacy_bare_canonicals(tmp_path: Path) -> None:
    """Bare canonical dirs at runs root → __legacy__ bucket counts toward annotated."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # No top-level index.json → multi-mode
    _make_dataset(data_root, "SO101", ep_count=5)
    # Create a bare canonical dir with manifest.json (legacy)
    legacy_dir = runs_root / "episode_000000__abc123def456"
    legacy_dir.mkdir()
    manifest = {
        "schema_version": "0.2.0",
        "run_hash": "sha256:" + "a" * 64,
        "episode_id": "episode_000000",
        "generated_at": "2026-05-17T10:00:00Z",
        "generator": {"pipeline_phase": 4},
    }
    (legacy_dir / "manifest.json").write_text(json.dumps(manifest))
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    body = resp.json()
    assert body[0]["annotated_ep_count"] == 1


def test_list_datasets_videos_root_extracted(tmp_path: Path) -> None:
    """videos_root is extracted from the first video feature key."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=1)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets")
    body = resp.json()
    # videos_root should contain the video key path
    assert body[0]["videos_root"] is not None
    assert "observation.images.front" in body[0]["videos_root"]


# ---------------------------------------------------------------------------
# B2 — GET /api/datasets/{name}
# ---------------------------------------------------------------------------

def test_get_dataset_not_found(tmp_path: Path) -> None:
    """GET /api/datasets/nonexistent → 404."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets/nonexistent")
    assert resp.status_code == 404


def test_get_dataset_no_runs(tmp_path: Path) -> None:
    """Dataset with no runs → episodes[i].runs=[]."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=3)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets/SO101")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "SO101"
    assert len(body["episodes"]) == 3
    for ep in body["episodes"]:
        assert ep["runs"] == []
        assert ep["fps"] == 15.0


def test_get_dataset_with_runs_in_run_set(tmp_path: Path) -> None:
    """Dataset with runs in a run-set: correct runs[] per episode."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=5)
    _make_run_set(runs_root, "so101_v5", ["episode_000001", "episode_000003"])
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets/SO101")
    assert resp.status_code == 200
    body = resp.json()
    eps = {ep["idx"]: ep for ep in body["episodes"]}
    assert len(eps[1]["runs"]) == 1
    assert eps[1]["runs"][0]["run_set"] == "so101_v5"
    assert len(eps[0]["runs"]) == 0
    assert len(eps[2]["runs"]) == 0


def test_get_dataset_video_path_from_template(tmp_path: Path) -> None:
    """Episode video_path is derived from info.json video_path template."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=2)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets/SO101")
    body = resp.json()
    ep0 = body["episodes"][0]
    assert "episode_000000" in ep0["video_path"]
    assert ep0["video_path"].endswith(".mp4")
    assert "episode_000000" in ep0["parquet_path"]
    assert ep0["parquet_path"].endswith(".parquet")


def test_get_dataset_fps_from_info(tmp_path: Path) -> None:
    """fps field in episodes comes from info.json."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    (runs_root / "index.json").write_text('{"schema_version":"0.1.0","runs":[]}')
    _make_dataset(data_root, "SO101", ep_count=1)
    client = _make_app_with(data_root, runs_root)
    resp = client.get("/api/datasets/SO101")
    body = resp.json()
    assert body["episodes"][0]["fps"] == 15.0
