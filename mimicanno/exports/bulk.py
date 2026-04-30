"""Bulk export orchestrator (Phase 5 Task 22, spec §1.1 / §9).

The integrator that ties together:

- :func:`mimicanno.exports.dataset_layout.enumerate_episodes`
- :func:`mimicanno.exports.run_resolution.resolve_runs_for_episodes`
- :func:`mimicanno.io.read_manifest` / :func:`mimicanno.io.read_annotation_result`
- :func:`mimicanno.exports.canonical.build_canonical_episode`
- :class:`mimicanno.exports.sink_lerobot_v3.LeRobotV3SinkWriter`
- :mod:`mimicanno.exports.output_layout` (prepare / finalize / backup / meta-copy)
- :mod:`mimicanno.exports.provenance` (.mimicanno-export.json)

Idempotency (spec §9.1): when ``out`` already contains a matching
``.mimicanno-export.json`` (same ``profile.hash`` and ``runs_used``), the
function returns ``ExportResult(reused=True)`` without writing. ``force=True``
overrides the match check; mismatches without force raise
``EXPORT_OUT_EXISTS``.
"""

from __future__ import annotations

import dataclasses
import json
import platform
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from mimicanno import __version__ as _MIMICANNO_VERSION  # noqa: N812
from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.canonical import (
    CanonicalEpisode,
    build_canonical_episode,
)
from mimicanno.exports.dataset_layout import (
    enumerate_episodes,
    resolve_episode_path,
)
from mimicanno.exports.output_layout import (
    copy_meta_verbatim,
    create_inplace_backup,
    finalize,
    prepare_layout,
)
from mimicanno.exports.profile import ExportProfile
from mimicanno.exports.provenance import (
    read_export_manifest,
    write_export_manifest,
)
from mimicanno.exports.run_resolution import resolve_runs_for_episodes
from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from mimicanno.io import read_annotation_result, read_manifest


@dataclass(frozen=True)
class ExportResult:
    """Return value of :func:`bulk_export`."""

    out_path: Path
    manifest_path: Path
    sidecar_path: Path
    episode_count: int
    subtask_count: int
    runs_used: dict[int, str]
    reused: bool


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _host_info() -> dict[str, str]:
    return {
        "platform": platform.system().lower(),
        "python": platform.python_version(),
    }


def _apply_cli_gate_overrides(
    profile: ExportProfile,
    *,
    require_reviewed: bool,
    allow_degraded: bool,
    allow_unlabeled: bool,
) -> ExportProfile:
    """Combine profile gates with CLI overrides per spec §5.3.

    - require_reviewed: OR (CLI strengthens the gate)
    - forbid_degraded_pipeline: AND NOT allow_degraded (CLI weakens the gate)
    - forbid_unlabeled_segments: AND NOT allow_unlabeled (CLI weakens the gate)
    """
    new_gates = dataclasses.replace(
        profile.gates,
        require_reviewed=profile.gates.require_reviewed or require_reviewed,
        forbid_degraded_pipeline=(
            profile.gates.forbid_degraded_pipeline and not allow_degraded
        ),
        forbid_unlabeled_segments=(
            profile.gates.forbid_unlabeled_segments and not allow_unlabeled
        ),
    )
    return replace(profile, gates=new_gates)


def _files_to_back_up_for_inplace(
    dataset_root: Path,
    *,
    episode_indices: list[int],
) -> list[Path]:
    """List every file the in-place export writes to (for backup)."""
    files: list[Path] = []
    for ep_idx in episode_indices:
        try:
            parquet_path, _ = resolve_episode_path(
                dataset_root, episode_index=ep_idx
            )
        except FileNotFoundError:
            continue
        files.append(parquet_path)
    files.append(dataset_root / "meta" / "info.json")
    files.append(dataset_root / "meta" / "subtasks.parquet")
    files.append(dataset_root / "meta" / "mimicanno_segments.parquet")
    episodes_root = dataset_root / "meta" / "episodes"
    if episodes_root.is_dir():
        files.extend(sorted(episodes_root.glob("chunk-*/file-*.parquet")))
    return files


def _emit_dry_run_summary(
    *,
    profile: ExportProfile,
    out: Path,
    output_mode: str,
    runs_used: dict[int, str],
    run_hashes: dict[int, str],
    source_dataset: Path,
) -> None:
    payload = {
        "dry_run": True,
        "profile": {"name": profile.name, "hash": profile.hash()},
        "output_mode": output_mode,
        "out": str(out),
        "episodes": [
            {
                "episode_index": ep_idx,
                "canonical_name": canonical,
                "run_hash": run_hashes.get(ep_idx, ""),
            }
            for ep_idx, canonical in sorted(runs_used.items())
        ],
        "would_write": [
            f"{out}/data/chunk-NNN/episode_NNNNNN.parquet (per episode)",
            f"{out}/meta/subtasks.parquet",
            f"{out}/meta/episodes/chunk-NNN/file-NNN.parquet",
            f"{out}/meta/mimicanno_segments.parquet",
            f"{out}/meta/info.json",
            f"{out}/.mimicanno-export.json",
        ],
        "would_symlink": (
            [f"{out}/videos -> {source_dataset}/videos"]
            if output_mode == "symlink"
            else []
        ),
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()


def bulk_export(
    *,
    dataset_root: Path,
    runs_root: Path,
    target_phase: int,
    profile: ExportProfile,
    out: Path,
    output_mode: Literal["symlink", "copy", "in_place"] = "symlink",
    config_hash: str | None = None,
    explicit_runs: list[str] | None = None,
    episode_filter: list[int] | None = None,
    force: bool = False,
    require_reviewed: bool = False,
    allow_degraded: bool = False,
    allow_unlabeled: bool = False,
    skip_missing: bool = False,
    dry_run: bool = False,
    cli_args: list[str] | None = None,
) -> ExportResult:
    """Run the full Phase 5 export pipeline (spec §1.1)."""
    # Step 1: validate dataset_root
    if not dataset_root.exists() or not (dataset_root / "meta" / "info.json").is_file():
        raise MimicAnnoError(
            ErrorCode.EXPORT_DATASET_NOT_FOUND,
            (
                f"dataset_root not found or missing meta/info.json: "
                f"{dataset_root}"
            ),
            {"dataset_root": str(dataset_root)},
        )

    # Step 2: enumerate episodes (intersect with filter)
    all_episodes = enumerate_episodes(dataset_root)
    if episode_filter is not None:
        wanted = set(episode_filter)
        episode_indices = [i for i in all_episodes if i in wanted]
    else:
        episode_indices = list(all_episodes)

    # Step 3: resolve runs
    runs_used = resolve_runs_for_episodes(
        runs_root,
        episode_indices,
        target_phase,
        config_hash=config_hash,
        explicit_runs=explicit_runs,
        skip_missing=skip_missing,
    )

    # Apply CLI gate overrides to a fresh profile copy.
    effective_profile = _apply_cli_gate_overrides(
        profile,
        require_reviewed=require_reviewed,
        allow_degraded=allow_degraded,
        allow_unlabeled=allow_unlabeled,
    )

    # Pre-load each canonical's manifest + annotation so we can:
    # (a) populate run_hashes for provenance / dry-run summary
    # (b) build CanonicalEpisode below.
    loaded: dict[int, tuple[Any, Any]] = {}  # ep_idx -> (Manifest, AnnotationResult)
    run_hashes: dict[int, str] = {}
    for ep_idx, canonical in runs_used.items():
        manifest = read_manifest(runs_root / canonical / "manifest.json")
        annotation = read_annotation_result(
            runs_root / canonical / "annotation.json"
        )
        loaded[ep_idx] = (manifest, annotation)
        run_hashes[ep_idx] = manifest.run_hash

    # Step 4: idempotency check (only meaningful for symlink/copy out paths
    # that are distinct from dataset_root, but the manifest match works for
    # in_place too if .mimicanno-export.json already exists).
    if output_mode != "in_place" and out.exists() and not force:
        existing = read_export_manifest(out)
        if existing is not None:
            existing_profile_hash = existing.get("profile", {}).get("hash")
            existing_runs_used = existing.get("runs_used", {})
            current_runs_used_str = {
                str(k): v for k, v in runs_used.items()
            }
            if (
                existing_profile_hash == effective_profile.hash()
                and existing_runs_used == current_runs_used_str
            ):
                sys.stderr.write(
                    "INFO: existing export matches current request; no-op\n"
                )
                sys.stderr.flush()
                return ExportResult(
                    out_path=out,
                    manifest_path=out / ".mimicanno-export.json",
                    sidecar_path=out / "meta" / "mimicanno_segments.parquet",
                    episode_count=int(existing.get("episode_count", 0)),
                    subtask_count=int(existing.get("subtask_count", 0)),
                    runs_used=dict(runs_used),
                    reused=True,
                )
            # Mismatch — raise EXPORT_OUT_EXISTS so user must --force.
            raise MimicAnnoError(
                ErrorCode.EXPORT_OUT_EXISTS,
                (
                    f"output {out} already contains a different export; "
                    f"pass --force to replace"
                ),
                {
                    "existing": existing,
                    "current": {
                        "profile_hash": effective_profile.hash(),
                        "runs_used": current_runs_used_str,
                    },
                },
            )

    # Step 5: out_parent must exist for symlink/copy modes.
    if output_mode != "in_place" and not out.parent.exists():
        raise MimicAnnoError(
            ErrorCode.EXPORT_OUT_PARENT_MISSING,
            f"parent directory of out does not exist: {out.parent}",
            {"out": str(out), "parent": str(out.parent)},
        )

    # Dry-run path: emit summary, skip layout / writes.
    if dry_run:
        _emit_dry_run_summary(
            profile=effective_profile,
            out=out,
            output_mode=output_mode,
            runs_used=runs_used,
            run_hashes=run_hashes,
            source_dataset=dataset_root,
        )
        return ExportResult(
            out_path=out,
            manifest_path=out / ".mimicanno-export.json",
            sidecar_path=out / "meta" / "mimicanno_segments.parquet",
            episode_count=len(runs_used),
            subtask_count=0,
            runs_used=dict(runs_used),
            reused=False,
        )

    # Step 6: prepare staging (or in-place backup).
    staging: Path
    if output_mode == "in_place":
        files_to_back_up = _files_to_back_up_for_inplace(
            dataset_root, episode_indices=list(runs_used.keys())
        )
        create_inplace_backup(dataset_root, files_to_back_up)
        staging = dataset_root
    else:
        staging = prepare_layout(
            output_mode, source=dataset_root, out=out
        )

    try:
        # Step 7: build CanonicalEpisode list.
        episodes: list[CanonicalEpisode] = []
        for ep_idx in sorted(runs_used.keys()):
            manifest, annotation = loaded[ep_idx]
            ep = build_canonical_episode(
                dataset_root=dataset_root,
                episode_index=ep_idx,
                annotation=annotation,
                manifest=manifest,
                profile=effective_profile,
            )
            episodes.append(ep)

        # Step 8: sink-write.
        sink = LeRobotV3SinkWriter()
        sink.write_all(
            out_dir=staging,
            episodes=episodes,
            profile=effective_profile,
            source_dataset=dataset_root,
        )

        # Step 9: copy meta verbatim (symlink/copy modes only — for in_place,
        # the source's meta/* files are already where they need to be and we
        # only overwrite the files the sink writer touches).
        if output_mode != "in_place":
            copy_meta_verbatim(dataset_root, staging)

        # Step 10: provenance manifest.
        # subtask_count = number of unique phases across exported episodes
        # (matches meta/subtasks.parquet row count via the registry).
        unique_phases: set[str] = set()
        gap_present = False
        for ep in episodes:
            covered = [False] * ep.num_frames
            for seg in ep.segments:
                unique_phases.add(seg.phase)
                for f in range(seg.start_frame, seg.end_frame + 1):
                    if 0 <= f < ep.num_frames:
                        covered[f] = True
            if not all(covered):
                gap_present = True
        subtask_count = len(unique_phases) + (
            1 if gap_present and "unlabeled" not in unique_phases else 0
        )

        write_export_manifest(
            staging,
            profile=effective_profile,
            runs_used=runs_used,
            run_hashes=run_hashes,
            source_dataset=dataset_root,
            runs_root=runs_root,
            target_phase=target_phase,
            config_hash_filter=config_hash,
            output_mode=output_mode,
            mimicanno_version=_MIMICANNO_VERSION,
            generated_at=_now_iso(),
            cli_args=list(cli_args) if cli_args is not None else [],
            host=_host_info(),
            episode_count=len(episodes),
            subtask_count=subtask_count,
        )

        # Step 11: finalize (atomic publish for symlink/copy; no-op for in_place).
        finalize(
            output_mode,
            source=dataset_root,
            out=out if output_mode != "in_place" else None,
            staging=staging,
            success=True,
        )
    except Exception:
        # Leave staging / backup in place for inspection; finalize with success=False.
        finalize(
            output_mode,
            source=dataset_root,
            out=out if output_mode != "in_place" else None,
            staging=staging,
            success=False,
        )
        raise

    final_root = out if output_mode != "in_place" else dataset_root
    return ExportResult(
        out_path=final_root,
        manifest_path=final_root / ".mimicanno-export.json",
        sidecar_path=final_root / "meta" / "mimicanno_segments.parquet",
        episode_count=len(episodes),
        subtask_count=subtask_count,
        runs_used=dict(runs_used),
        reused=False,
    )


__all__ = ["ExportResult", "bulk_export"]
