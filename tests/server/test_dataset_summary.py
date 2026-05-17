"""U-A2 — tests for dataset summary reader + route.

Reader tests directly exercise compute_summary().
Route tests use TestClient against the full app.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.server.dataset_summary import compute_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dataset(data_root: Path, name: str, ep_count: int) -> Path:
    """Minimal LeRobot v3 dataset structure."""
    ds = data_root / name
    (ds / "meta").mkdir(parents=True)
    info = {
        "robot_type": "so101",
        "total_episodes": ep_count,
        "fps": 15,
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": {"observation.images.front": {"dtype": "video"}},
    }
    (ds / "meta" / "info.json").write_text(json.dumps(info))
    return ds


def _make_run_set(
    runs_root: Path,
    rs_name: str,
    episodes: list[dict],
) -> Path:
    """Create a run-set directory with index.json and annotation.json files.

    Each item in ``episodes`` is:
        {
            "episode_id": "episode_000000",
            "canonical": "episode_000000__abc123def456",
            "segments": [
                {"phase": "approach_object", "reviewed": True, "verb": None, ...},
                ...
            ],
        }
    """
    rs_dir = runs_root / rs_name
    rs_dir.mkdir(parents=True, exist_ok=True)
    runs_index = []
    for ep in episodes:
        ep_id = ep["episode_id"]
        canonical = ep["canonical"]
        can_dir = rs_dir / canonical
        can_dir.mkdir(exist_ok=True)

        # Write annotation.json
        ann = {
            "schema_version": "0.2.0",
            "episode_id": ep_id,
            "run_hash": "sha256:" + "a" * 64,
            "generated_at": ep.get("generated_at", "2026-05-17T10:00:00Z"),
            "segments": ep.get("segments", []),
        }
        (can_dir / "annotation.json").write_text(json.dumps(ann))

        runs_index.append({
            "episode_id": ep_id,
            "canonical_name": canonical,
            "run_hash": "sha256:" + "a" * 64,
            "run_hash_short": canonical.split("__")[1],
            "generated_at": ep.get("generated_at", "2026-05-17T10:00:00Z"),
            "manifest_url": f"{canonical}/manifest.json",
            "pipeline_phase": 4,
        })

    (rs_dir / "index.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "runs": runs_index,
    }))
    return rs_dir


def _seg(phase: str, reviewed: bool = False, verb: str | None = None) -> dict:
    return {
        "segment_id": "s_001",
        "phase": phase,
        "reviewed": reviewed,
        "verb": verb,
        "object": None,
        "target": None,
    }


def _make_app(data_root: Path, runs_root: Path) -> TestClient:
    from mimicanno.server.app import create_app
    app = create_app(
        runs_root=runs_root,
        cors_origins=[],
        jobs_dir=runs_root.parent / ".jobs",
        data_root=data_root,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Reader tests
# ---------------------------------------------------------------------------


def test_happy_path_aggregation(tmp_path: Path) -> None:
    """Two annotated episodes → correct label_distribution and stats."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=5)
    _make_run_set(runs_root, "so101_v5", [
        {
            "episode_id": "episode_000000",
            "canonical": "episode_000000__aaa",
            "segments": [
                _seg("approach_object", reviewed=True),
                _seg("grasp", reviewed=True),
                _seg("place_object", reviewed=False),
            ],
        },
        {
            "episode_id": "episode_000001",
            "canonical": "episode_000001__bbb",
            "segments": [
                _seg("approach_object", reviewed=True),
                _seg("approach_object", reviewed=True),
            ],
        },
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="so101_v5")
    assert result["run_set"] == "so101_v5"
    assert result["ep_count"] == 5
    assert result["annotated_ep_count"] == 2
    dist = result["label_distribution"]
    assert dist["approach_object"] == 3
    assert dist["grasp"] == 1
    assert dist["place_object"] == 1
    stats = result["segment_count_stats"]
    assert stats["min"] == 2
    assert stats["max"] == 3
    assert abs(stats["mean"] - 2.5) < 0.01
    # reviewed: 4 out of 5 total segments
    assert abs(result["reviewed_rate"] - 0.8) < 0.01


def test_empty_run_set(tmp_path: Path) -> None:
    """Run_set with 0 annotated eps → zeros."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=3)
    _make_run_set(runs_root, "empty_rs", [])
    result = compute_summary("SO101", data_root, runs_root, run_set="empty_rs")
    assert result["annotated_ep_count"] == 0
    assert result["label_distribution"] == {}
    assert result["segment_count_stats"] == {"mean": 0, "min": 0, "max": 0}
    assert result["reviewed_rate"] == 0.0
    assert result["per_episode"] == []


def test_malformed_annotation_graceful(tmp_path: Path) -> None:
    """Malformed annotation.json → ep skipped gracefully (not counted)."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=3)
    rs_dir = _make_run_set(runs_root, "so101_v5", [
        {
            "episode_id": "episode_000000",
            "canonical": "episode_000000__bad",
            "segments": [_seg("approach_object")],
        },
    ])
    # Corrupt the annotation.json
    bad_ann = rs_dir / "episode_000000__bad" / "annotation.json"
    bad_ann.write_text("not valid json {{{")
    result = compute_summary("SO101", data_root, runs_root, run_set="so101_v5")
    # The ep is listed in index.json but annotation.json is unreadable
    # annotated_ep_count is based on index, but per_episode may be empty
    # (graceful: skip bad eps in aggregation)
    assert result["label_distribution"] == {}


def test_label_distribution_counts_phases(tmp_path: Path) -> None:
    """Phase counts are accumulated correctly across multiple episodes."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=2)
    _make_run_set(runs_root, "v1", [
        {
            "episode_id": "episode_000000",
            "canonical": "episode_000000__x1",
            "segments": [_seg("grasp"), _seg("grasp"), _seg("unlabeled")],
        },
        {
            "episode_id": "episode_000001",
            "canonical": "episode_000001__x2",
            "segments": [_seg("grasp"), _seg("approach_object")],
        },
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="v1")
    dist = result["label_distribution"]
    assert dist["grasp"] == 3
    assert dist["unlabeled"] == 1
    assert dist["approach_object"] == 1


def test_segment_count_stats_math(tmp_path: Path) -> None:
    """min/max/mean are computed over annotated episodes."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=3)
    _make_run_set(runs_root, "v1", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__a",
         "segments": [_seg("grasp")] * 2},
        {"episode_id": "episode_000001", "canonical": "episode_000001__b",
         "segments": [_seg("grasp")] * 6},
        {"episode_id": "episode_000002", "canonical": "episode_000002__c",
         "segments": [_seg("grasp")] * 4},
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="v1")
    stats = result["segment_count_stats"]
    assert stats["min"] == 2
    assert stats["max"] == 6
    assert abs(stats["mean"] - 4.0) < 0.01


def test_reviewed_rate_math(tmp_path: Path) -> None:
    """reviewed_rate = reviewed_segments / total_segments."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=1)
    _make_run_set(runs_root, "v1", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__a",
         "segments": [
             _seg("approach_object", reviewed=True),
             _seg("approach_object", reviewed=True),
             _seg("approach_object", reviewed=False),
             _seg("approach_object", reviewed=False),
         ]},
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="v1")
    assert abs(result["reviewed_rate"] - 0.5) < 0.01


def test_per_episode_order(tmp_path: Path) -> None:
    """per_episode is sorted ascending by episode idx."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=3)
    _make_run_set(runs_root, "v1", [
        {"episode_id": "episode_000002", "canonical": "episode_000002__a",
         "segments": [_seg("grasp")]},
        {"episode_id": "episode_000000", "canonical": "episode_000000__b",
         "segments": [_seg("grasp"), _seg("place_object")]},
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="v1")
    idxs = [ep["idx"] for ep in result["per_episode"]]
    assert idxs == sorted(idxs)


def test_most_recent_run_set_default(tmp_path: Path) -> None:
    """When run_set=None, selects the run_set with the most recent index.json mtime."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=5)
    # Create two run_sets; make so101_v5's index.json newer
    _make_run_set(runs_root, "so101_v4", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__old",
         "segments": [_seg("grasp")]},
    ])
    time.sleep(0.05)  # ensure mtime difference
    _make_run_set(runs_root, "so101_v5", [
        {"episode_id": "episode_000001", "canonical": "episode_000001__new",
         "segments": [_seg("approach_object")]},
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set=None)
    assert result["run_set"] == "so101_v5"
    assert result["label_distribution"] == {"approach_object": 1}


def test_label_diversity_per_episode(tmp_path: Path) -> None:
    """label_diversity = distinct phase values in that episode's segments."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=2)
    _make_run_set(runs_root, "v1", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__a",
         "segments": [
             _seg("approach_object"), _seg("approach_object"),
             _seg("grasp"), _seg("place_object"),
         ]},
        {"episode_id": "episode_000001", "canonical": "episode_000001__b",
         "segments": [_seg("unlabeled"), _seg("unlabeled")],
         },
    ])
    result = compute_summary("SO101", data_root, runs_root, run_set="v1")
    per_ep = {ep["idx"]: ep for ep in result["per_episode"]}
    assert per_ep[0]["label_diversity"] == 3  # approach_object, grasp, place_object
    assert per_ep[1]["label_diversity"] == 1  # only unlabeled


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def test_route_200_happy(tmp_path: Path) -> None:
    """GET /api/datasets/{name}/summary → 200 + valid shape."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=3)
    _make_run_set(runs_root, "so101_v5", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__abc",
         "segments": [_seg("approach_object", reviewed=True), _seg("grasp")]},
    ])
    client = _make_app(data_root, runs_root)
    resp = client.get("/api/datasets/SO101/summary?run_set=so101_v5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_set"] == "so101_v5"
    assert body["ep_count"] == 3
    assert "label_distribution" in body
    assert "segment_count_stats" in body
    assert "reviewed_rate" in body
    assert "per_episode" in body
    assert isinstance(body["per_episode"], list)


def test_route_default_run_set_most_recent(tmp_path: Path) -> None:
    """No run_set param → most recent selected."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=5)
    _make_run_set(runs_root, "so101_v4", [
        {"episode_id": "episode_000000", "canonical": "episode_000000__old",
         "segments": [_seg("grasp")]},
    ])
    time.sleep(0.05)
    _make_run_set(runs_root, "so101_v5", [
        {"episode_id": "episode_000001", "canonical": "episode_000001__new",
         "segments": [_seg("approach_object")]},
    ])
    client = _make_app(data_root, runs_root)
    resp = client.get("/api/datasets/SO101/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_set"] == "so101_v5"


def test_route_404_dataset_unknown(tmp_path: Path) -> None:
    """GET /api/datasets/nonexistent/summary → 404."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    client = _make_app(data_root, runs_root)
    resp = client.get("/api/datasets/nonexistent/summary")
    assert resp.status_code == 404


def test_route_legacy_run_set(tmp_path: Path) -> None:
    """run_set=__legacy__ (top-level index.json) returns valid summary."""
    data_root = tmp_path / "data"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _make_dataset(data_root, "SO101", ep_count=2)
    # Create a legacy run_set (index.json at runs_root level)
    canonical = "episode_000000__legacyabc"
    can_dir = runs_root / canonical
    can_dir.mkdir()
    ann = {
        "schema_version": "0.2.0",
        "episode_id": "episode_000000",
        "run_hash": "sha256:" + "b" * 64,
        "generated_at": "2026-05-17T09:00:00Z",
        "segments": [_seg("approach_object", reviewed=True)],
    }
    (can_dir / "annotation.json").write_text(json.dumps(ann))
    index = {
        "schema_version": "0.1.0",
        "runs": [{
            "episode_id": "episode_000000",
            "canonical_name": canonical,
            "run_hash": "sha256:" + "b" * 64,
            "generated_at": "2026-05-17T09:00:00Z",
            "manifest_url": f"{canonical}/manifest.json",
            "pipeline_phase": 4,
        }],
    }
    (runs_root / "index.json").write_text(json.dumps(index))
    client = _make_app(data_root, runs_root)
    resp = client.get("/api/datasets/SO101/summary?run_set=__legacy__")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_set"] == "__legacy__"
    assert body["annotated_ep_count"] == 1
