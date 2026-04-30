"""Error-path coverage for every ``EXPORT_*`` code (Phase 5 Task 28, spec §11).

One test per ``ErrorCode.EXPORT_*`` enum member (18 codes). Each test
constructs the failure condition, calls into the export pipeline (or its
sub-helpers) and asserts:

- ``MimicAnnoError`` is raised with the right ``error_code``.
- The error context dict carries the spec-required fields.
- For codes only reachable via the CLI surface
  (``EXPORT_INPLACE_NO_CONFIRM``), the test invokes the subprocess CLI and
  checks exit code 2 + structured stderr JSON.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
import yaml  # type: ignore[import-untyped]

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.bulk import bulk_export
from mimicanno.exports.canonical import build_canonical_episode
from mimicanno.exports.output_layout import create_inplace_backup
from mimicanno.exports.profile import ExportProfile
from mimicanno.io import read_annotation_result, read_manifest
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    make_segment,
    write_run_dir,
    write_runs_index,
    write_source_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "exports" / "fixtures"
MINI_DATASET = FIXTURES_DIR / "mini_so101"
MINI_RUNS = FIXTURES_DIR / "mini_runs"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_mini_fixture(
    tmp_path: Path,
    *,
    episode_count: int = 1,
    pipeline_phase: int = 4,
    require_review: bool = False,
    extra_run_per_ep: bool = False,
    second_config_hash: str = "sha256:" + "9" * 64,
) -> tuple[Path, Path]:
    """Synthesise a single-episode dataset + runs root.

    ``extra_run_per_ep=True`` adds a second run dir for each episode using
    ``second_config_hash`` (used to trigger EXPORT_RUN_AMBIGUOUS).
    """
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    canonical_episodes = [
        make_canonical_episode(episode_index=i, num_frames=3)
        for i in range(episode_count)
    ]
    write_source_dataset(dataset_root, episodes=canonical_episodes)

    entries: list[dict[str, Any]] = []
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
        if extra_run_per_ep:
            canonical2 = f"{ep.episode_id}__99fedc0{ep.episode_index:01d}"
            write_run_dir(
                runs_root,
                canonical_name=canonical2,
                episode_id=ep.episode_id,
                pipeline_phase=pipeline_phase,
                config_hash=second_config_hash,
                num_frames=ep.num_frames,
                segments=[
                    make_segment(
                        episode_id=ep.episode_id,
                        start_frame=0,
                        end_frame=ep.num_frames - 1,
                        phase="grasp",
                    )
                ],
            )
            entries.append(
                {
                    "canonical_name": canonical2,
                    "episode_id": ep.episode_id,
                    "pipeline_phase": pipeline_phase,
                    "config_hash": second_config_hash,
                }
            )
    write_runs_index(runs_root, entries)
    return dataset_root, runs_root


# ---------------------------------------------------------------------------
# 1. EXPORT_PROFILE_INVALID
# ---------------------------------------------------------------------------


def test_export_profile_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [valid: yaml")
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve(str(bad))
    assert ei.value.code == ErrorCode.EXPORT_PROFILE_INVALID


def test_export_profile_invalid_schema_violation(tmp_path: Path) -> None:
    """A YAML that parses but fails the JSON Schema -> EXPORT_PROFILE_INVALID."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"schema_version": "1", "name": "x"}))
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve(str(bad))
    assert ei.value.code == ErrorCode.EXPORT_PROFILE_INVALID
    assert ei.value.context.get("path") == str(bad)


# ---------------------------------------------------------------------------
# 2. EXPORT_PROFILE_NOT_FOUND
# ---------------------------------------------------------------------------


def test_export_profile_not_found() -> None:
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve("nonexistent_xyz_profile_name")
    assert ei.value.code == ErrorCode.EXPORT_PROFILE_NOT_FOUND
    assert ei.value.context["name_or_path"] == "nonexistent_xyz_profile_name"


# ---------------------------------------------------------------------------
# 3. EXPORT_DATASET_NOT_FOUND
# ---------------------------------------------------------------------------


def test_export_dataset_not_found(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    write_runs_index(runs_root, [])
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=tmp_path / "definitely_does_not_exist",
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_DATASET_NOT_FOUND
    assert "dataset_root" in ei.value.context


# ---------------------------------------------------------------------------
# 4. EXPORT_RUNS_ROOT_NOT_FOUND
# ---------------------------------------------------------------------------


def test_export_runs_root_not_found(tmp_path: Path) -> None:
    dataset_root, _runs_root = _build_mini_fixture(tmp_path, episode_count=1)
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=tmp_path / "runs_does_not_exist",
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_RUNS_ROOT_NOT_FOUND
    assert "runs_root" in ei.value.context


# ---------------------------------------------------------------------------
# 5. EXPORT_RUN_NOT_FOUND
# ---------------------------------------------------------------------------


def test_export_run_not_found(tmp_path: Path) -> None:
    """Build runs index with no run for episode 0, then export episode 0."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(dataset_root, episodes=eps)
    # Empty runs index.
    write_runs_index(runs_root, [])

    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_RUN_NOT_FOUND
    assert ei.value.context.get("episode_index") == 0
    assert ei.value.context.get("target_phase") == 4


# ---------------------------------------------------------------------------
# 6. EXPORT_RUN_AMBIGUOUS
# ---------------------------------------------------------------------------


def test_export_run_ambiguous(tmp_path: Path) -> None:
    """Two phase-4 runs for episode 0 with distinct config_hashes -> ambiguous."""
    dataset_root, runs_root = _build_mini_fixture(
        tmp_path, episode_count=1, extra_run_per_ep=True
    )
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_RUN_AMBIGUOUS
    candidates = ei.value.context.get("candidates")
    assert isinstance(candidates, list) and len(candidates) >= 2
    for c in candidates:
        assert "canonical_name" in c
        assert "config_hash_short" in c


# ---------------------------------------------------------------------------
# 7. EXPORT_EPISODE_MISMATCH
# ---------------------------------------------------------------------------


def test_export_episode_mismatch(tmp_path: Path) -> None:
    """An annotation whose episode_id does not match the parquet's episode_id."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(dataset_root, episodes=eps)

    # Run dir's annotation declares episode_id=episode_000005 but we'll feed it
    # for episode 0 directly via build_canonical_episode.
    canonical = "episode_000005__deadbeef"
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000005",
        pipeline_phase=4,
        num_frames=3,
    )

    manifest = read_manifest(runs_root / canonical / "manifest.json")
    annotation = read_annotation_result(runs_root / canonical / "annotation.json")
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        build_canonical_episode(
            dataset_root=dataset_root,
            episode_index=0,
            annotation=annotation,
            manifest=manifest,
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_EPISODE_MISMATCH
    assert ei.value.context["annotation_episode_id"] == "episode_000005"
    assert ei.value.context["parquet_episode_id"] == "episode_000000"


# ---------------------------------------------------------------------------
# 8. EXPORT_PHASE_DOWNGRADE
# ---------------------------------------------------------------------------


def test_export_phase_downgrade(tmp_path: Path) -> None:
    """Manifest reports degraded_from_phase=3, profile gates forbid downgrade."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(dataset_root, episodes=eps)

    canonical = "episode_000000__deadbeef"
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000000",
        pipeline_phase=4,
        num_frames=3,
        degraded_from_phase=3,
    )
    write_runs_index(
        runs_root,
        [
            {
                "canonical_name": canonical,
                "episode_id": "episode_000000",
                "pipeline_phase": 4,
            }
        ],
    )

    profile = make_profile(tmp_dir=tmp_path)
    profile = replace(
        profile,
        gates=replace(profile.gates, forbid_degraded_pipeline=True),
    )
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_PHASE_DOWNGRADE
    assert ei.value.context["episode_id"] == "episode_000000"


# ---------------------------------------------------------------------------
# 9. EXPORT_UNLABELED_PRESENT
# ---------------------------------------------------------------------------


def test_export_unlabeled_present(tmp_path: Path) -> None:
    """Annotation has a phase='unlabeled' segment, gate forbids it."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(dataset_root, episodes=eps)

    canonical = "episode_000000__deadbeef"
    seg_unlabeled = make_segment(
        episode_id="episode_000000",
        start_frame=0,
        end_frame=2,
        phase="unlabeled",
    )
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000000",
        pipeline_phase=4,
        num_frames=3,
        segments=[seg_unlabeled],
    )
    write_runs_index(
        runs_root,
        [
            {
                "canonical_name": canonical,
                "episode_id": "episode_000000",
                "pipeline_phase": 4,
            }
        ],
    )

    profile = make_profile(tmp_dir=tmp_path)
    profile = replace(
        profile,
        gates=replace(profile.gates, forbid_unlabeled_segments=True),
    )
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_UNLABELED_PRESENT


# ---------------------------------------------------------------------------
# 10. EXPORT_NOT_REVIEWED
# ---------------------------------------------------------------------------


def test_export_not_reviewed(tmp_path: Path) -> None:
    """Default fixture has reviewed=False; CLI override require_reviewed=True."""
    dataset_root, runs_root = _build_mini_fixture(tmp_path, episode_count=1)
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
            require_reviewed=True,
        )
    assert ei.value.code == ErrorCode.EXPORT_NOT_REVIEWED


# ---------------------------------------------------------------------------
# 11. EXPORT_OUT_EXISTS
# ---------------------------------------------------------------------------


def test_export_out_exists(tmp_path: Path) -> None:
    """First export succeeds; second with a different profile hash (no force) raises."""
    dataset_root, runs_root = _build_mini_fixture(tmp_path, episode_count=1)
    out = tmp_path / "OUT"
    profile = make_profile(tmp_dir=tmp_path)
    bulk_export(
        dataset_root=dataset_root,
        runs_root=runs_root,
        target_phase=4,
        profile=profile,
        out=out,
    )
    profile2 = make_profile(annotation_prefix="other", tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile2,
            out=out,
        )
    assert ei.value.code == ErrorCode.EXPORT_OUT_EXISTS
    assert "current" in ei.value.context
    assert "existing" in ei.value.context


# ---------------------------------------------------------------------------
# 12. EXPORT_OUT_PARENT_MISSING
# ---------------------------------------------------------------------------


def test_export_out_parent_missing(tmp_path: Path) -> None:
    dataset_root, runs_root = _build_mini_fixture(tmp_path, episode_count=1)
    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "definitely_missing_parent" / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_OUT_PARENT_MISSING
    assert "parent" in ei.value.context


# ---------------------------------------------------------------------------
# 13. EXPORT_RAW_ACTION_MISSING
# ---------------------------------------------------------------------------


def test_export_raw_action_missing(tmp_path: Path) -> None:
    """Source parquet has no action.* columns and pass_through_raw_action=True."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(dataset_root, episodes=eps)

    # Wipe action.* columns from the source per-episode parquet.
    src_parquet = (
        dataset_root / "data" / "chunk-000" / "episode_000000.parquet"
    )
    table = pq.read_table(src_parquet)  # type: ignore[no-untyped-call]
    keep = [c for c in table.column_names if not c.startswith("action")]
    pq.write_table(table.select(keep), src_parquet)  # type: ignore[no-untyped-call]

    canonical = "episode_000000__deadbeef"
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000000",
        pipeline_phase=4,
        num_frames=3,
    )
    write_runs_index(
        runs_root,
        [
            {
                "canonical_name": canonical,
                "episode_id": "episode_000000",
                "pipeline_phase": 4,
            }
        ],
    )

    profile = make_profile(tmp_dir=tmp_path)
    profile = replace(
        profile,
        source=replace(profile.source, pass_through_raw_action=True),
    )
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_RAW_ACTION_MISSING


# ---------------------------------------------------------------------------
# 14. EXPORT_FRAME_COUNT_MISMATCH
# ---------------------------------------------------------------------------


def test_export_frame_count_mismatch(tmp_path: Path) -> None:
    """annotation.segments[-1].end_frame != num_frames - 1."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=5)]  # 5 frames
    write_source_dataset(dataset_root, episodes=eps)

    canonical = "episode_000000__deadbeef"
    # Segment ends at frame 2 (not 4 == num_frames - 1)
    bad_seg = make_segment(
        episode_id="episode_000000",
        start_frame=0,
        end_frame=2,
        phase="approach",
    )
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000000",
        pipeline_phase=4,
        num_frames=5,
        segments=[bad_seg],
    )
    write_runs_index(
        runs_root,
        [
            {
                "canonical_name": canonical,
                "episode_id": "episode_000000",
                "pipeline_phase": 4,
            }
        ],
    )

    profile = make_profile(tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_FRAME_COUNT_MISMATCH
    assert ei.value.context["last_end_frame"] == 2
    assert ei.value.context["num_frames"] == 5


# ---------------------------------------------------------------------------
# 15. EXPORT_INPLACE_NO_CONFIRM (CLI subprocess)
# ---------------------------------------------------------------------------


def test_export_inplace_no_confirm_via_cli() -> None:
    """``--in-place`` without ``--yes-i-mean-it`` -> exit 2 with structured stderr."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    res = subprocess.run(
        [
            sys.executable, "-m", "mimicanno",
            "export",
            "--dataset", str(MINI_DATASET),
            "--runs-root", str(MINI_RUNS),
            "--target-phase", "4",
            "--profile", "so101_sarm",
            "--in-place",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 2, f"stdout={res.stdout}\nstderr={res.stderr}"
    err = json.loads(res.stderr.strip().splitlines()[-1])
    assert err["error_code"] == "EXPORT_INPLACE_NO_CONFIRM"
    assert err["context"]["dataset"] == str(MINI_DATASET)


# ---------------------------------------------------------------------------
# 16. EXPORT_INPLACE_BACKUP_FAILED
# ---------------------------------------------------------------------------


def test_export_inplace_backup_failed(tmp_path: Path) -> None:
    """Make the backup-target parent unwritable and confirm graceful abort.

    Strategy: ``create_inplace_backup`` derives the backup dir as
    ``<source>/.mimicanno-backup-<ISO>``. If we revoke write permission on
    ``source``, the ``backup_dir.mkdir()`` call fails with PermissionError,
    which the helper translates to ``EXPORT_INPLACE_BACKUP_FAILED``.
    """
    source = tmp_path / "src"
    source.mkdir()
    target = source / "file_to_back_up"
    target.write_text("x")

    # Make source read-only.
    orig_mode = source.stat().st_mode
    os.chmod(source, stat.S_IREAD | stat.S_IEXEC)
    try:
        with pytest.raises(MimicAnnoError) as ei:
            create_inplace_backup(source, [target])
        assert ei.value.code == ErrorCode.EXPORT_INPLACE_BACKUP_FAILED
        assert "backup_dir" in ei.value.context
    finally:
        os.chmod(source, orig_mode)


# ---------------------------------------------------------------------------
# 17. EXPORT_SINK_VALIDATION_FAILED
# ---------------------------------------------------------------------------


def test_export_sink_validation_failed_bare_collision(tmp_path: Path) -> None:
    """annotation_prefix=None plus source already has bare ``subtask_names``
    on the per-episode parquet -> EXPORT_SINK_VALIDATION_FAILED."""
    dataset_root = tmp_path / "dataset"
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    eps = [make_canonical_episode(episode_index=0, num_frames=3)]
    write_source_dataset(
        dataset_root,
        episodes=eps,
        bare_collision_columns=True,
    )
    canonical = "episode_000000__deadbeef"
    write_run_dir(
        runs_root,
        canonical_name=canonical,
        episode_id="episode_000000",
        pipeline_phase=4,
        num_frames=3,
    )
    write_runs_index(
        runs_root,
        [
            {
                "canonical_name": canonical,
                "episode_id": "episode_000000",
                "pipeline_phase": 4,
            }
        ],
    )

    profile = make_profile(annotation_prefix=None, tmp_dir=tmp_path)
    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_SINK_VALIDATION_FAILED
    assert "collisions" in ei.value.context


# ---------------------------------------------------------------------------
# 18. EXPORT_EE_POSE_UNAVAILABLE
# ---------------------------------------------------------------------------


def test_export_ee_pose_unavailable(tmp_path: Path) -> None:
    """Adapter returns None for eef_pose -> EXPORT_EE_POSE_UNAVAILABLE.

    We build a profile with the GenericAdapter configured WITHOUT
    ``eef_xyz_column`` so ``GenericAdapter.eef_pose`` returns None, then
    ``build_canonical_episode`` raises with the documented code.
    """
    dataset_root, runs_root = _build_mini_fixture(tmp_path, episode_count=1)

    # Build a profile whose adapter has no eef_xyz_column.
    cfg = {
        "schema_version": "1",
        "name": "no_pose",
        "description": "",
        "source": {
            "robot_adapter": "generic",
            "pass_through_raw_action": False,
            "generic_adapter_config": {
                "schema_version": "0.2.0",
                "name": "no_pose",
                "gripper_column": "observation.state.gripper_pos",
                "gripper_scale_min": 0.0,
                "gripper_scale_max": 100.0,
                "eef_xyz_column": None,
                "eef_rotvec_column": None,
                "eef_quat_column": None,
            },
        },
        "canonical": {
            "delta_basis": "body_frame_t",
            "rotation_repr": "rotvec",
            "gripper_source": "observation",
        },
        "sink": {
            "writer": "lerobot_v3",
            "params": {
                "annotation_prefix": "mimicanno",
                "subtask_registry_path": "meta/subtasks.parquet",
                "extra_per_frame_columns": [
                    # Profile demands ee_delta_6d -> EXPORT_EE_POSE_UNAVAILABLE
                    # when adapter has no eef columns configured.
                    {
                        "name": "mimicanno.ee_delta_6d",
                        "source": "ee_delta_6d",
                        "dtype": "float32",
                    },
                ],
            },
        },
        "sidecar": {"enabled": True, "path": "meta/mimicanno_segments.parquet"},
        "gates": {
            "require_reviewed": False,
            "forbid_degraded_pipeline": False,
            "forbid_unlabeled_segments": False,
        },
    }
    yaml_path = tmp_path / "no_pose.yaml"
    yaml_path.write_text(yaml.safe_dump(cfg))
    profile = ExportProfile.from_yaml(yaml_path)

    with pytest.raises(MimicAnnoError) as ei:
        bulk_export(
            dataset_root=dataset_root,
            runs_root=runs_root,
            target_phase=4,
            profile=profile,
            out=tmp_path / "OUT",
        )
    assert ei.value.code == ErrorCode.EXPORT_EE_POSE_UNAVAILABLE
    assert ei.value.context.get("adapter") == "generic"


# ---------------------------------------------------------------------------
# Sanity: every code is covered by a test in this module
# ---------------------------------------------------------------------------


def test_every_export_code_has_a_test_in_this_file() -> None:
    """Meta-assert: every ErrorCode.EXPORT_* has a test_export_* function here."""
    import inspect
    import sys as _sys
    module = _sys.modules[__name__]
    test_names = {
        name for name, obj in inspect.getmembers(module)
        if inspect.isfunction(obj) and name.startswith("test_export_")
    }
    # We allow >1 test per code (e.g. EXPORT_PROFILE_INVALID has _yaml /
    # _schema_violation variants), so check for prefix coverage.
    for code in ErrorCode:
        if not code.name.startswith("EXPORT_"):
            continue
        prefix = f"test_{code.name.lower()}"
        matches = [n for n in test_names if n.startswith(prefix)]
        assert matches, (
            f"no test in test_errors.py covers {code.name}; "
            f"expected at least one function starting with {prefix!r}; "
            f"have {sorted(test_names)}"
        )
