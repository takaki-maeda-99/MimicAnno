"""LeRobot v3 sink writer (Phase 5 Tasks 10–16, spec §4).

Writes a fresh LeRobot v3 dataset under ``out_dir`` using a list of
``CanonicalEpisode`` and an ``ExportProfile``. Each sub-write is individually
atomic via tmp-file + ``os.replace``; transaction-level atomicity (the whole
output dir publish) is the output_layout module's responsibility (Phase D).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.dataset_layout import resolve_episode_path

if TYPE_CHECKING:
    from mimicanno.exports.canonical import CanonicalEpisode
    from mimicanno.exports.profile import ExportProfile


_DTYPE_MAP: dict[str, pa.DataType] = {
    "float32": pa.float32(),
    "float64": pa.float64(),
    "int32": pa.int32(),
    "int64": pa.int64(),
}


# ---------------------------------------------------------------------------
# Atomic parquet write helper
# ---------------------------------------------------------------------------


def _atomic_write_parquet(path: Path, table: pa.Table) -> None:
    """Atomically write ``table`` to ``path`` via ``.tmp.<pid>`` + ``os.replace``.

    Mirrors the pattern in ``mimicanno.io.write_json_atomic`` /
    ``mimicanno.publish``: write to a sibling tmp file, then atomically rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    pq.write_table(table, tmp)  # type: ignore[no-untyped-call]
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Extra-column helper (Task 13, spec §4.1)
# ---------------------------------------------------------------------------


def _build_extra_column(
    values: np.ndarray | None,
    arrow_dtype: pa.DataType,
    n_frames: int,
) -> pa.Array:
    """Build a pa.Array from a CanonicalEpisode field (1-D or 2-D ndarray)."""
    if values is None:
        raise MimicAnnoError(
            ErrorCode.EXPORT_SINK_VALIDATION_FAILED,
            "profile demands extra_per_frame_columns entry but source field is None",
            {},
        )
    arr = np.asarray(values)
    if arr.shape[0] != n_frames:
        raise MimicAnnoError(
            ErrorCode.EXPORT_SINK_VALIDATION_FAILED,
            (
                f"extra_per_frame_columns: source has {arr.shape[0]} rows "
                f"but episode has {n_frames} frames"
            ),
            {"shape": list(arr.shape), "n_frames": n_frames},
        )
    if arr.ndim == 1:
        return pa.array(arr.tolist(), type=arrow_dtype)
    if arr.ndim == 2:
        list_type = pa.list_(arrow_dtype, list_size=arr.shape[1])
        return pa.array(arr.tolist(), type=list_type)
    raise MimicAnnoError(
        ErrorCode.EXPORT_SINK_VALIDATION_FAILED,
        f"extra_per_frame_columns: unsupported ndim={arr.ndim}",
        {"shape": list(arr.shape)},
    )


# ---------------------------------------------------------------------------
# Coverage-gap helper (Task 12, spec §4.1)
# ---------------------------------------------------------------------------


def _episodes_have_coverage_gaps(episodes: list[CanonicalEpisode]) -> bool:
    """Return True if any episode has a frame not covered by a segment.

    Mimicanno's bracketing guarantees full coverage for runs that completed
    normally; this helper exists so that synthesized / edited / imported
    annotations with gaps trigger ``unlabeled`` injection in the registry.
    """
    for ep in episodes:
        covered = [False] * ep.num_frames
        for seg in ep.segments:
            for f in range(seg.start_frame, seg.end_frame + 1):
                if 0 <= f < ep.num_frames:
                    covered[f] = True
        if not all(covered):
            return True
    return False


# ---------------------------------------------------------------------------
# Sidecar parquet (Task 11, spec §3.1)
# ---------------------------------------------------------------------------


_SIDECAR_SCHEMA = pa.schema(
    [
        ("episode_index", pa.int64()),
        ("segment_index", pa.int32()),
        ("segment_id", pa.string()),
        ("phase", pa.string()),
        ("verb", pa.string()),
        ("object", pa.string()),
        ("target", pa.string()),
        ("failure_flags", pa.list_(pa.string())),
        ("start_frame", pa.int64()),
        ("end_frame", pa.int64()),
        ("start_time", pa.float64()),
        ("end_time", pa.float64()),
        ("label_source", pa.string()),
        ("object_state_unavailable", pa.bool_()),
        ("object_track_ids", pa.list_(pa.string())),
        ("label_version", pa.string()),
        ("boundary_confidence", pa.float32()),
        ("vlm_confidence", pa.float32()),
        ("overall_confidence", pa.float32()),
        ("evidence", pa.string()),
        ("reviewed", pa.bool_()),
        ("reviewer_id", pa.string()),
        ("smoothing_ops", pa.list_(pa.string())),
        ("boundary_source_start", pa.list_(pa.string())),
        ("boundary_source_end", pa.list_(pa.string())),
        ("run_hash", pa.string()),
        ("config_hash", pa.string()),
        ("input_hash", pa.string()),
        ("pipeline_phase", pa.int8()),
        ("mimicanno_version", pa.string()),
        ("generated_at", pa.string()),
    ]
)


class LeRobotV3SinkWriter:
    """Writes a fresh LeRobot v3 dataset (spec §4)."""

    def write_all(
        self,
        *,
        out_dir: Path,
        episodes: list[CanonicalEpisode],
        profile: ExportProfile,
        source_dataset: Path,
    ) -> None:
        raise NotImplementedError(
            "LeRobotV3SinkWriter.write_all is not yet implemented (Phase 5 Task 16)"
        )

    # -----------------------------------------------------------------
    # Task 13: per-frame data parquet writer
    # -----------------------------------------------------------------

    def _write_data_parquet(
        self,
        *,
        out_dir: Path,
        source_dataset: Path,
        episode: CanonicalEpisode,
        registry: dict[str, int],
        profile: ExportProfile,
    ) -> None:
        """Write ``data/<chunk>/episode_NNNNNN.parquet`` for one episode (spec §4.1).

        Source columns are preserved byte-for-byte. ``subtask_index`` is added
        per frame using closed-closed inclusive segment ranges; gap frames
        fall through to the ``unlabeled`` index. Each entry in
        ``profile.sink.params.extra_per_frame_columns`` is pulled from the
        ``CanonicalEpisode`` and cast to the profile-specified dtype.
        """
        src_path, _filter = resolve_episode_path(
            source_dataset, episode_index=episode.episode_index
        )
        src_table = pq.read_table(src_path)  # type: ignore[no-untyped-call]
        n_frames = src_table.num_rows
        if n_frames != episode.num_frames:
            raise MimicAnnoError(
                ErrorCode.EXPORT_FRAME_COUNT_MISMATCH,
                (
                    f"source parquet has {n_frames} rows but CanonicalEpisode "
                    f"has num_frames={episode.num_frames}"
                ),
                {"episode_index": episode.episode_index},
            )

        # Build subtask_index column. First-match-wins; gaps -> unlabeled.
        unlabeled_idx = registry.get("unlabeled")
        subtask_index = [-1] * n_frames
        for seg in episode.segments:
            phase_idx = registry[seg.phase]
            for f in range(seg.start_frame, seg.end_frame + 1):
                if 0 <= f < n_frames and subtask_index[f] == -1:
                    subtask_index[f] = phase_idx
        for f in range(n_frames):
            if subtask_index[f] == -1:
                if unlabeled_idx is None:
                    raise MimicAnnoError(
                        ErrorCode.EXPORT_SINK_VALIDATION_FAILED,
                        (
                            f"frame {f} of episode {episode.episode_index} has "
                            "no segment coverage and 'unlabeled' is not in the "
                            "subtasks registry"
                        ),
                        {"episode_index": episode.episode_index, "frame": f},
                    )
                subtask_index[f] = unlabeled_idx

        # Append columns to the source table, preserving original column order.
        out_table = src_table.append_column(
            "subtask_index",
            pa.array(subtask_index, type=pa.int64()),
        )

        for entry in profile.sink.params.get("extra_per_frame_columns", []):
            col_name = entry["name"]
            source_field = entry["source"]
            dtype_str = entry["dtype"]
            arrow_dtype = _DTYPE_MAP[dtype_str]
            values = getattr(episode, source_field)
            arr = _build_extra_column(values, arrow_dtype, n_frames)
            out_table = out_table.append_column(col_name, arr)

        # Output path mirrors the source layout (template-resolved via
        # resolve_episode_path; reuse the same chunk filename).
        rel = src_path.relative_to(source_dataset)
        out_path = out_dir / rel
        _atomic_write_parquet(out_path, out_table)

    # -----------------------------------------------------------------
    # Task 12: subtasks registry writer
    # -----------------------------------------------------------------

    def _write_subtasks_registry(
        self,
        *,
        out_dir: Path,
        episodes: list[CanonicalEpisode],
    ) -> dict[str, int]:
        """Write ``meta/subtasks.parquet`` and return ``{phase → subtask_index}``.

        Order is first-appearance across all episodes' segments, scanned in
        ``episode_index`` order then segment order. ``unlabeled`` is injected
        when needed for gap-filling (spec §4.1) so the data parquet writer can
        always assign every frame a valid subtask_index.
        """
        registry: dict[str, int] = {}
        for ep in sorted(episodes, key=lambda e: e.episode_index):
            for seg in ep.segments:
                if seg.phase not in registry:
                    registry[seg.phase] = len(registry)

        # Detect gap risk: any episode where the union of segment ranges does
        # not cover [0, num_frames). If so, ``unlabeled`` must be in the
        # registry so the data writer can assign gap frames.
        if _episodes_have_coverage_gaps(episodes) and "unlabeled" not in registry:
            registry["unlabeled"] = len(registry)

        rows = [
            {"subtask": phase, "subtask_index": idx, "description": ""}
            for phase, idx in registry.items()
        ]
        schema = pa.schema(
            [
                ("subtask", pa.string()),
                ("subtask_index", pa.int64()),
                ("description", pa.string()),
            ]
        )
        table = pa.Table.from_pylist(rows, schema=schema)
        _atomic_write_parquet(out_dir / "meta" / "subtasks.parquet", table)
        return registry

    # -----------------------------------------------------------------
    # Task 11: sidecar parquet writer
    # -----------------------------------------------------------------

    def _write_sidecar(
        self,
        *,
        out_dir: Path,
        episodes: list[CanonicalEpisode],
    ) -> None:
        """Write ``meta/mimicanno_segments.parquet`` (spec §3.1).

        One row per segment, sorted by ``(episode_index, segment_index)``.
        Provenance fields are redundant per row (every row in the same episode
        shares the same ``run_hash`` etc.) — this is intentional per spec.
        """
        rows: list[dict[str, object]] = []
        for ep in sorted(episodes, key=lambda e: e.episode_index):
            for seg_index, seg in enumerate(ep.segments):
                row = seg.to_sidecar_row()
                row["episode_index"] = ep.episode_index
                row["segment_index"] = seg_index
                row["run_hash"] = ep.run_hash
                row["config_hash"] = ep.config_hash
                row["input_hash"] = ep.input_hash
                row["pipeline_phase"] = ep.pipeline_phase
                row["mimicanno_version"] = ep.mimicanno_version
                row["generated_at"] = ep.generated_at
                rows.append(row)

        # Project to canonical column order; pa.Table.from_pylist with a
        # supplied schema enforces nullable types and column order.
        ordered_rows = [
            {col.name: r.get(col.name) for col in _SIDECAR_SCHEMA} for r in rows
        ]
        table = pa.Table.from_pylist(ordered_rows, schema=_SIDECAR_SCHEMA)
        _atomic_write_parquet(
            out_dir / "meta" / "mimicanno_segments.parquet", table
        )
