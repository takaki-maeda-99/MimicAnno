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

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from mimicanno.exports.canonical import CanonicalEpisode
    from mimicanno.exports.profile import ExportProfile


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
