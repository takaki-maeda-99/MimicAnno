"""Tests for ``mimicanno.exports.run_resolution`` (Phase 5 Task 20)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.run_resolution import resolve_runs_for_episodes


def _write_run(
    runs_root: Path,
    *,
    canonical_name: str,
    episode_id: str,
    pipeline_phase: int,
    config_hash: str,
    generated_at: str,
    run_hash: str = "sha256:" + "0" * 64,
) -> None:
    """Write a minimal ``runs/<canonical>/manifest.json`` fixture."""
    run_dir = runs_root / canonical_name
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "task": {"text": "pick the cube", "version": None},
        "generated_at": generated_at,
        "generator": {
            "name": "mimicanno",
            "cli_version": "0.1.0",
            "pipeline_phase": pipeline_phase,
        },
        "config_hash": config_hash,
        "input_hash": "sha256:" + "f" * 64,
        "run_hash": run_hash,
        "model_versions": {},
        "pipeline_params": {},
        "inputs": {},
        "time_base": "frame",
        "fps": 30.0,
        "duration_sec": 1.0,
        "pipeline_status": {
            "object_state_available": False,
            "degraded_from_phase": None,
            "degrade_reason": None,
        },
        "compat": {},
        "artifacts": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))


def _write_index(runs_root: Path, rows: list[dict]) -> None:
    payload = {"schema_version": "1.0", "runs": rows}
    (runs_root / "index.json").write_text(json.dumps(payload))


def _idx_row(
    *,
    episode_id: str,
    canonical: str,
    pipeline_phase: int,
    config_hash: str = "sha256:" + "1" * 64,
    generated_at: str = "2026-04-30T12:00:00Z",
    run_hash: str = "sha256:" + "0" * 64,
) -> dict:
    short_len = len(canonical) - len(episode_id) - len("__")
    return {
        "episode_id": episode_id,
        "run_hash": run_hash,
        "run_hash_short": run_hash.removeprefix("sha256:")[:short_len],
        "config_hash_short": config_hash.removeprefix("sha256:")[:8],
        "input_hash_short": "ffffffff",
        "manifest_url": f"{canonical}/manifest.json",
        "task_text": "pick the cube",
        "pipeline_phase": pipeline_phase,
        "generated_at": generated_at,
    }


def test_runs_root_missing(tmp_path: Path) -> None:
    with pytest.raises(MimicAnnoError) as ei:
        resolve_runs_for_episodes(
            tmp_path / "nope",
            episode_indices=[0],
            target_phase=4,
        )
    assert ei.value.code == ErrorCode.EXPORT_RUNS_ROOT_NOT_FOUND


def test_index_file_missing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    with pytest.raises(MimicAnnoError) as ei:
        resolve_runs_for_episodes(
            runs_root,
            episode_indices=[0],
            target_phase=4,
        )
    assert ei.value.code == ErrorCode.EXPORT_RUNS_ROOT_NOT_FOUND


def test_happy_path_single_match(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_run(
        runs_root,
        canonical_name="episode_000000__abc12345",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__abc12345",
                pipeline_phase=4,
            )
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root, episode_indices=[0], target_phase=4
    )
    assert out == {0: "episode_000000__abc12345"}


def test_filter_by_target_phase(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # Phase-1 run for ep 0 — should be ignored when target_phase=4
    _write_run(
        runs_root,
        canonical_name="episode_000000__phase1aa",
        episode_id="episode_000000",
        pipeline_phase=1,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000000__phase4bb",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__phase1aa",
                pipeline_phase=1,
            ),
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__phase4bb",
                pipeline_phase=4,
            ),
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root, episode_indices=[0], target_phase=4
    )
    assert out == {0: "episode_000000__phase4bb"}


def test_zero_matches_raises(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_run(
        runs_root,
        canonical_name="episode_000000__phase1aa",
        episode_id="episode_000000",
        pipeline_phase=1,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__phase1aa",
                pipeline_phase=1,
            )
        ],
    )
    with pytest.raises(MimicAnnoError) as ei:
        resolve_runs_for_episodes(
            runs_root, episode_indices=[0], target_phase=4
        )
    assert ei.value.code == ErrorCode.EXPORT_RUN_NOT_FOUND


def test_zero_matches_skip_missing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # ep 0 has only phase 1; ep 1 has phase 4
    _write_run(
        runs_root,
        canonical_name="episode_000000__phase1aa",
        episode_id="episode_000000",
        pipeline_phase=1,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000001__phase4cc",
        episode_id="episode_000001",
        pipeline_phase=4,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__phase1aa",
                pipeline_phase=1,
            ),
            _idx_row(
                episode_id="episode_000001",
                canonical="episode_000001__phase4cc",
                pipeline_phase=4,
            ),
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root,
        episode_indices=[0, 1],
        target_phase=4,
        skip_missing=True,
    )
    assert out == {1: "episode_000001__phase4cc"}


def test_ambiguous_with_no_filter(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    h1 = "sha256:" + "1" * 64
    h2 = "sha256:" + "2" * 64
    _write_run(
        runs_root,
        canonical_name="episode_000000__cfgaa111",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h1,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000000__cfgbb222",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h2,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__cfgaa111",
                pipeline_phase=4,
                config_hash=h1,
            ),
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__cfgbb222",
                pipeline_phase=4,
                config_hash=h2,
            ),
        ],
    )
    with pytest.raises(MimicAnnoError) as ei:
        resolve_runs_for_episodes(
            runs_root, episode_indices=[0], target_phase=4
        )
    assert ei.value.code == ErrorCode.EXPORT_RUN_AMBIGUOUS
    assert "candidates" in ei.value.context


def test_ambiguous_resolved_by_config_hash(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    h1 = "sha256:" + "1" * 64
    h2 = "sha256:" + "2" * 64
    _write_run(
        runs_root,
        canonical_name="episode_000000__cfgaa111",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h1,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000000__cfgbb222",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h2,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__cfgaa111",
                pipeline_phase=4,
                config_hash=h1,
            ),
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__cfgbb222",
                pipeline_phase=4,
                config_hash=h2,
            ),
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root, episode_indices=[0], target_phase=4, config_hash=h2
    )
    assert out == {0: "episode_000000__cfgbb222"}


def test_same_config_picks_newest(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    h = "sha256:" + "1" * 64
    _write_run(
        runs_root,
        canonical_name="episode_000000__rerun001",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000000__rerun002",
        episode_id="episode_000000",
        pipeline_phase=4,
        config_hash=h,
        generated_at="2026-04-30T13:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__rerun001",
                pipeline_phase=4,
                config_hash=h,
                generated_at="2026-04-30T11:00:00Z",
            ),
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__rerun002",
                pipeline_phase=4,
                config_hash=h,
                generated_at="2026-04-30T13:00:00Z",
            ),
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root, episode_indices=[0], target_phase=4
    )
    assert out == {0: "episode_000000__rerun002"}


def test_explicit_runs_overrides_filters(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_run(
        runs_root,
        canonical_name="episode_000000__phase1aa",
        episode_id="episode_000000",
        pipeline_phase=1,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T11:00:00Z",
    )
    _write_run(
        runs_root,
        canonical_name="episode_000001__phase4bb",
        episode_id="episode_000001",
        pipeline_phase=4,
        config_hash="sha256:" + "1" * 64,
        generated_at="2026-04-30T12:00:00Z",
    )
    _write_index(
        runs_root,
        [
            _idx_row(
                episode_id="episode_000000",
                canonical="episode_000000__phase1aa",
                pipeline_phase=1,
            ),
            _idx_row(
                episode_id="episode_000001",
                canonical="episode_000001__phase4bb",
                pipeline_phase=4,
            ),
        ],
    )
    out = resolve_runs_for_episodes(
        runs_root,
        episode_indices=[0, 1],  # ignored when explicit
        target_phase=4,  # ignored when explicit
        explicit_runs=[
            "episode_000000__phase1aa",
            "episode_000001__phase4bb",
        ],
    )
    assert out == {0: "episode_000000__phase1aa", 1: "episode_000001__phase4bb"}


def test_explicit_runs_unknown_canonical(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _write_index(runs_root, [])
    with pytest.raises(MimicAnnoError) as ei:
        resolve_runs_for_episodes(
            runs_root,
            episode_indices=[0],
            target_phase=4,
            explicit_runs=["episode_000000__doesnot"],
        )
    assert ei.value.code == ErrorCode.EXPORT_RUN_NOT_FOUND
