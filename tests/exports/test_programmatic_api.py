"""Tests for the ``mimicanno.export()`` programmatic API (Phase 5 Task 23)."""

from __future__ import annotations

from pathlib import Path

import pytest

import mimicanno
from mimicanno import ExportProfile, ExportResult, export
from mimicanno.errors import ErrorCode, MimicAnnoError
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    make_segment,
    write_run_dir,
    write_runs_index,
    write_source_dataset,
)


def _build_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    canonical_episodes = [
        make_canonical_episode(episode_index=i, num_frames=3) for i in range(2)
    ]
    write_source_dataset(dataset_root, episodes=canonical_episodes)

    entries = []
    for ep in canonical_episodes:
        canonical = f"{ep.episode_id}__abcdef0{ep.episode_index:01d}"
        write_run_dir(
            runs_root,
            canonical_name=canonical,
            episode_id=ep.episode_id,
            pipeline_phase=4,
            num_frames=ep.num_frames,
            segments=[
                make_segment(
                    episode_id=ep.episode_id,
                    start_frame=0,
                    end_frame=ep.num_frames - 1,
                    phase="approach",
                )
            ],
        )
        entries.append(
            {
                "canonical_name": canonical,
                "episode_id": ep.episode_id,
                "pipeline_phase": 4,
            }
        )
    write_runs_index(runs_root, entries)
    return dataset_root, runs_root


def test_export_callable_with_profile_object(tmp_path: Path) -> None:
    dataset_root, runs_root = _build_fixture(tmp_path)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )
    assert isinstance(result, ExportResult)
    assert result.episode_count == 2
    assert result.reused is False


def test_export_callable_with_profile_name(tmp_path: Path) -> None:
    """Pass a profile name (str) — should be resolved internally."""
    dataset_root, runs_root = _build_fixture(tmp_path)
    out = tmp_path / "OUT"
    # so101_sarm uses generic adapter with eef_xyz_column / eef_rotvec_column
    # that match our synthetic dataset's columns.
    result = export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile="so101_sarm",
        out=out,
        output_mode="symlink",
    )
    assert isinstance(result, ExportResult)
    assert result.episode_count == 2


def test_export_accepts_str_paths(tmp_path: Path) -> None:
    dataset_root, runs_root = _build_fixture(tmp_path)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = export(
        dataset_root=str(dataset_root),
        runs_root=str(runs_root),
        target_phase=4,
        profile=profile,
        out=str(out),
    )
    assert result.episode_count == 2


def test_export_kwargs_pass_through(tmp_path: Path) -> None:
    """``skip_missing`` and other kwargs should be forwarded."""
    dataset_root, runs_root = _build_fixture(tmp_path)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        episode_filter=[0],
    )
    assert result.episode_count == 1


def test_export_propagates_mimicanno_errors(tmp_path: Path) -> None:
    """Missing dataset triggers EXPORT_DATASET_NOT_FOUND through the API."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    write_runs_index(runs_root, [])
    profile = make_profile(tmp_dir=tmp_path)

    with pytest.raises(MimicAnnoError) as ei:
        export(
            dataset_root=tmp_path / "nope",
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_DATASET_NOT_FOUND


def test_top_level_exports_are_re_exported() -> None:
    """``mimicanno`` exposes ``export`` / ``ExportProfile`` / ``ExportResult``."""
    assert hasattr(mimicanno, "export")
    assert hasattr(mimicanno, "ExportProfile")
    assert hasattr(mimicanno, "ExportResult")
    assert callable(mimicanno.export)
    assert ExportProfile is mimicanno.ExportProfile
    assert ExportResult is mimicanno.ExportResult
