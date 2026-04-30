"""Tests for ``mimicanno.exports.bulk.bulk_export`` (Phase 5 Task 22)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.bulk import ExportResult, bulk_export
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    make_segment,
    write_run_dir,
    write_runs_index,
    write_source_dataset,
)


def _build_fixture(
    tmp_path: Path,
    *,
    episode_count: int = 2,
    runs_per_episode: int = 1,
    require_review: bool = False,
    pipeline_phase: int = 4,
) -> tuple[Path, Path, list[int]]:
    """Build a synthetic dataset + runs root.

    Returns ``(dataset_root, runs_root, episode_indices)``.
    """
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    canonical_episodes = [
        make_canonical_episode(episode_index=i, num_frames=3)
        for i in range(episode_count)
    ]
    write_source_dataset(dataset_root, episodes=canonical_episodes)

    entries = []
    for ep in canonical_episodes:
        canonical = f"{ep.episode_id}__abcdef0{ep.episode_index:01d}"
        seg = make_segment(
            episode_id=ep.episode_id,
            start_frame=0,
            end_frame=ep.num_frames - 1,
            phase="approach",
        )
        if require_review:
            from mimicanno.schema import SubtaskSegment

            seg = SubtaskSegment(**{**seg.__dict__, "reviewed": True})
        write_run_dir(
            runs_root,
            canonical_name=canonical,
            episode_id=ep.episode_id,
            pipeline_phase=pipeline_phase,
            num_frames=ep.num_frames,
            segments=[seg],
        )
        entries.append(
            {
                "canonical_name": canonical,
                "episode_id": ep.episode_id,
                "pipeline_phase": pipeline_phase,
            }
        )

    write_runs_index(runs_root, entries)

    return dataset_root, runs_root, list(range(episode_count))


def test_happy_path(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )

    assert isinstance(result, ExportResult)
    assert result.reused is False
    assert result.episode_count == 2
    assert result.out_path == out
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").is_file()
    assert (out / "data" / "chunk-000" / "episode_000001.parquet").is_file()
    assert (out / "meta" / "subtasks.parquet").is_file()
    assert (out / "meta" / "info.json").is_file()
    assert (out / "meta" / "mimicanno_segments.parquet").is_file()
    assert (out / ".mimicanno-export.json").is_file()
    assert result.manifest_path == out / ".mimicanno-export.json"
    assert result.sidecar_path == out / "meta" / "mimicanno_segments.parquet"
    assert result.runs_used.keys() == {0, 1}


def test_idempotency_short_circuit(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    first = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )
    assert first.reused is False

    original_generated_at = json.loads(
        (out / ".mimicanno-export.json").read_text()
    )["generated_at"]

    second = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )
    assert second.reused is True
    assert second.episode_count == 2
    assert second.runs_used == first.runs_used
    # On reuse, the manifest's generated_at field is the original.
    assert (
        json.loads((out / ".mimicanno-export.json").read_text())["generated_at"]
        == original_generated_at
    )


def test_force_replaces_existing(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )
    # Mutate the existing export so we can detect a replacement.
    sentinel = out / ".sentinel"
    sentinel.write_text("old")

    profile2 = make_profile(annotation_prefix="other", tmp_dir=tmp_path)
    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile2,
        out=out,
        output_mode="symlink",
        force=True,
    )
    assert result.reused is False
    assert not sentinel.exists()


def test_out_exists_without_force(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )

    profile2 = make_profile(annotation_prefix="other", tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile2,
            out=out,
            output_mode="symlink",
        )
    assert ei.value.code == ErrorCode.EXPORT_OUT_EXISTS


def test_skip_missing_one_episode(tmp_path: Path) -> None:
    """ep 0 has only phase 1; ep 1 has phase 4. skip_missing=True excludes ep 0."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    canonical_episodes = [
        make_canonical_episode(episode_index=i, num_frames=3) for i in range(2)
    ]
    write_source_dataset(dataset_root, episodes=canonical_episodes)

    entries = []
    # ep 0: only phase 1
    canonical0 = f"{canonical_episodes[0].episode_id}__phase1aa"
    write_run_dir(
        runs_root,
        canonical_name=canonical0,
        episode_id=canonical_episodes[0].episode_id,
        pipeline_phase=1,
        num_frames=canonical_episodes[0].num_frames,
        segments=[
            make_segment(
                episode_id=canonical_episodes[0].episode_id,
                start_frame=0,
                end_frame=canonical_episodes[0].num_frames - 1,
                phase="approach",
            )
        ],
    )
    entries.append(
        {
            "canonical_name": canonical0,
            "episode_id": canonical_episodes[0].episode_id,
            "pipeline_phase": 1,
        }
    )
    # ep 1: phase 4
    canonical1 = f"{canonical_episodes[1].episode_id}__phase4bb"
    write_run_dir(
        runs_root,
        canonical_name=canonical1,
        episode_id=canonical_episodes[1].episode_id,
        pipeline_phase=4,
        num_frames=canonical_episodes[1].num_frames,
        segments=[
            make_segment(
                episode_id=canonical_episodes[1].episode_id,
                start_frame=0,
                end_frame=canonical_episodes[1].num_frames - 1,
                phase="approach",
            )
        ],
    )
    entries.append(
        {
            "canonical_name": canonical1,
            "episode_id": canonical_episodes[1].episode_id,
            "pipeline_phase": 4,
        }
    )
    write_runs_index(runs_root, entries)

    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)
    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
        skip_missing=True,
    )
    assert result.episode_count == 1
    assert result.runs_used == {1: canonical1}
    assert (out / "data" / "chunk-000" / "episode_000001.parquet").is_file()


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
        dry_run=True,
    )
    assert result.reused is False
    assert result.episode_count == 2
    assert not out.exists()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["dry_run"] is True
    assert payload["profile"]["name"] == profile.name
    assert payload["episodes"][0]["episode_index"] == 0


def test_in_place_creates_backup(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    profile = make_profile(tmp_dir=tmp_path)

    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=dataset_root,
        output_mode="in_place",
    )
    assert result.reused is False
    # Backup directory exists under dataset_root.
    backups = list(dataset_root.glob(".mimicanno-backup-*"))
    assert len(backups) == 1
    # Provenance manifest written in dataset_root.
    assert (dataset_root / ".mimicanno-export.json").is_file()
    # Sidecar parquet written inside dataset_root.
    assert (dataset_root / "meta" / "mimicanno_segments.parquet").is_file()


def test_dataset_not_found(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    write_runs_index(runs_root, [])
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=tmp_path / "missing",
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
            output_mode="symlink",
        )
    assert ei.value.code == ErrorCode.EXPORT_DATASET_NOT_FOUND


def test_out_parent_missing(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=1)
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "missing_parent" / "OUT",
            output_mode="symlink",
        )
    assert ei.value.code == ErrorCode.EXPORT_OUT_PARENT_MISSING


def test_episode_filter(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=3)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)

    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
        episode_filter=[1],
    )
    assert result.episode_count == 1
    assert result.runs_used.keys() == {1}


def test_cli_gates_override_profile(tmp_path: Path) -> None:
    """``require_reviewed=True`` from CLI flips the profile gate even if profile
    has ``require_reviewed=False`` — and triggers EXPORT_NOT_REVIEWED."""
    dataset_root, runs_root, _ = _build_fixture(
        tmp_path, episode_count=1, require_review=False
    )
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)  # require_reviewed=False
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=out,
            output_mode="symlink",
            require_reviewed=True,
        )
    assert ei.value.code == ErrorCode.EXPORT_NOT_REVIEWED


def test_subtask_count_in_result(tmp_path: Path) -> None:
    dataset_root, runs_root, _ = _build_fixture(tmp_path, episode_count=2)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)
    result = bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
        output_mode="symlink",
    )
    # Only one phase ('approach') across both episodes; no gaps so no
    # 'unlabeled' injection.
    assert result.subtask_count == 1
