"""Validate the mini_so101 + mini_runs fixtures (Phase 5 Task 24).

Asserts:

- ``mini_so101`` is a structurally-valid LeRobot v3 dataset (info.json valid,
  3 episode parquets readable, expected column types).
- ``mini_runs`` has 3 run dirs, all manifests + annotations validate against
  their JSON schemas via ``read_manifest`` / ``read_annotation_result``.
- Frame-coverage rule: union of segment frame ranges equals
  ``[0, num_frames - 1]`` per episode.
- Build scripts are idempotent: re-running both produces byte-identical output.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from mimicanno.io import read_annotation_result, read_manifest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DATASET_DIR = FIXTURES_DIR / "mini_so101"
RUNS_DIR = FIXTURES_DIR / "mini_runs"
NUM_EPISODES = 3
FRAMES_PER_EPISODE = 20


def _import_module(name: str, path: Path) -> object:
    """Load a build script as a module without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hash_tree(root: Path) -> dict[str, str]:
    """Recursive SHA-256 of every regular file under *root* (rel paths)."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
    return out


# ---------------------------------------------------------------------------
# mini_so101 dataset structure
# ---------------------------------------------------------------------------


def test_mini_so101_info_json_valid() -> None:
    info = json.loads((DATASET_DIR / "meta" / "info.json").read_text())
    assert info["codebase_version"] == "v3.0"
    assert info["total_episodes"] == NUM_EPISODES
    assert info["total_frames"] == NUM_EPISODES * FRAMES_PER_EPISODE
    assert info["fps"] == 15
    assert "{episode_index:" in info["data_path"]
    feats = info["features"]
    # Spot-check key columns.
    assert feats["observation.state.gripper_pos"]["dtype"] == "float64"
    assert feats["observation.state.ee_pos"]["shape"] == [3]
    assert feats["observation.state.joint_pos"]["shape"] == [6]


def test_mini_so101_episode_parquets() -> None:
    for ep in range(NUM_EPISODES):
        path = (
            DATASET_DIR
            / "data"
            / "chunk-000"
            / f"episode_{ep:06d}.parquet"
        )
        assert path.is_file()
        table = pq.read_table(path)  # type: ignore[no-untyped-call]
        assert table.num_rows == FRAMES_PER_EPISODE
        names = set(table.column_names)
        for required in (
            "timestamp",
            "frame_index",
            "episode_index",
            "index",
            "task_index",
            "observation.state.joint_pos",
            "observation.state.gripper_pos",
            "observation.state.ee_pos",
            "observation.state.ee_rotvec",
            "action.joint_pos",
            "action.gripper_pos",
            "action.ee_pos",
            "action.ee_rotvec",
        ):
            assert required in names, required
        # Gripper sweep should hit values in [0, 40] window.
        gp = table.column("observation.state.gripper_pos").to_pylist()
        assert min(gp) >= 0.0
        assert max(gp) <= 40.0


def test_mini_so101_videos_present() -> None:
    for ep in range(NUM_EPISODES):
        path = (
            DATASET_DIR
            / "videos"
            / "observation.images.front"
            / "chunk-000"
            / f"episode_{ep:06d}.mp4"
        )
        assert path.is_file()
        assert path.stat().st_size > 0


def test_mini_so101_episodes_metadata_parquet() -> None:
    path = (
        DATASET_DIR / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    )
    assert path.is_file()
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    names = set(table.column_names)
    for col in (
        "episode_index",
        "tasks",
        "length",
        "dataset_from_index",
        "dataset_to_index",
    ):
        assert col in names
    assert table.num_rows == NUM_EPISODES


def test_mini_so101_tasks_parquet() -> None:
    path = DATASET_DIR / "meta" / "tasks.parquet"
    assert path.is_file()
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    assert "task_index" in table.column_names
    assert "task" in table.column_names
    assert table.num_rows == 1


# ---------------------------------------------------------------------------
# mini_runs validity
# ---------------------------------------------------------------------------


def test_mini_runs_index_json() -> None:
    raw = json.loads((RUNS_DIR / "index.json").read_text())
    assert raw["schema_version"] == "1.0"
    assert len(raw["runs"]) == NUM_EPISODES
    episode_ids = {r["episode_id"] for r in raw["runs"]}
    assert episode_ids == {f"episode_{i:06d}" for i in range(NUM_EPISODES)}
    for r in raw["runs"]:
        assert r["pipeline_phase"] == 4
        assert r["manifest_url"].endswith("/manifest.json")


def test_mini_runs_manifests_load_and_validate() -> None:
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        m = read_manifest(run_dir / "manifest.json")
        a = read_annotation_result(run_dir / "annotation.json")
        assert m.episode_id == a.episode_id
        assert m.run_hash == a.run_hash
        assert m.config_hash == a.config_hash
        assert m.fps == 15.0
        assert m.duration_sec == FRAMES_PER_EPISODE / 15.0
        assert a.pipeline_phase == 4


def test_mini_runs_segment_coverage() -> None:
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        a = read_annotation_result(run_dir / "annotation.json")
        covered = [False] * FRAMES_PER_EPISODE
        for seg in a.segments:
            for f in range(seg.start_frame, seg.end_frame + 1):
                assert 0 <= f < FRAMES_PER_EPISODE, (
                    f"segment range out of bounds: {seg.segment_id}"
                )
                assert not covered[f], (
                    f"segment overlap at frame {f} in {run_dir.name}"
                )
                covered[f] = True
        assert all(covered), f"frame coverage gap in {run_dir.name}"
        # End boundary equals last-frame index (Phase 5 invariant).
        assert a.segments[-1].end_frame == FRAMES_PER_EPISODE - 1
        assert a.segments[0].start_frame == 0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_build_scripts_are_idempotent(tmp_path: Path) -> None:
    """Re-running both build scripts must produce byte-identical output."""
    so101_module = _import_module(
        "_mini_so101_builder",
        FIXTURES_DIR / "build_mini_so101.py",
    )
    runs_module = _import_module(
        "_mini_runs_builder",
        FIXTURES_DIR / "build_mini_runs.py",
    )
    so101_out = tmp_path / "mini_so101"
    runs_out = tmp_path / "mini_runs"
    so101_module.build(so101_out)  # type: ignore[attr-defined]
    runs_module.build(runs_out)  # type: ignore[attr-defined]

    assert _hash_tree(so101_out) == _hash_tree(DATASET_DIR)
    assert _hash_tree(runs_out) == _hash_tree(RUNS_DIR)
