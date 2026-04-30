"""Sidecar parquet writer (Phase 5 Task 11, spec §3.1)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from tests.exports._helpers import make_canonical_episode, make_segment

SIDECAR_COLUMNS = [
    "episode_index",
    "segment_index",
    "segment_id",
    "phase",
    "verb",
    "object",
    "target",
    "failure_flags",
    "start_frame",
    "end_frame",
    "start_time",
    "end_time",
    "label_source",
    "object_state_unavailable",
    "object_track_ids",
    "label_version",
    "boundary_confidence",
    "vlm_confidence",
    "overall_confidence",
    "evidence",
    "reviewed",
    "reviewer_id",
    "smoothing_ops",
    "boundary_source_start",
    "boundary_source_end",
    "run_hash",
    "config_hash",
    "input_hash",
    "pipeline_phase",
    "mimicanno_version",
    "generated_at",
]


def test_sidecar_writes_31_columns_and_correct_rows(tmp_path: Path) -> None:
    ep0 = make_canonical_episode(
        episode_index=0,
        num_frames=4,
        segments=[
            make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=1,
                phase="approach",
            ),
            make_segment(
                episode_id="episode_000000",
                start_frame=2,
                end_frame=3,
                phase="grasp",
            ),
        ],
    )
    ep1 = make_canonical_episode(
        episode_index=1,
        num_frames=3,
        segments=[
            make_segment(
                episode_id="episode_000001",
                start_frame=0,
                end_frame=2,
                phase="lift",
            )
        ],
    )

    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    writer._write_sidecar(out_dir=out_dir, episodes=[ep0, ep1])

    sidecar_path = out_dir / "meta" / "mimicanno_segments.parquet"
    assert sidecar_path.is_file()
    table = pq.read_table(sidecar_path)  # type: ignore[no-untyped-call]
    assert table.num_rows == 3  # 2 + 1

    # All 31 columns present and in canonical order.
    assert list(table.column_names) == SIDECAR_COLUMNS

    rows = table.to_pylist()
    # Sorted by (episode_index, segment_index)
    assert [(r["episode_index"], r["segment_index"]) for r in rows] == [
        (0, 0),
        (0, 1),
        (1, 0),
    ]
    # Sample-row values
    r0 = rows[0]
    assert r0["phase"] == "approach"
    assert r0["start_frame"] == 0
    assert r0["end_frame"] == 1
    assert r0["run_hash"] == ep0.run_hash
    assert r0["pipeline_phase"] == 1
    assert r0["mimicanno_version"] == "0.1.0"
    assert r0["smoothing_ops"] == []
    assert r0["boundary_source_start"] == ["episode_start"]


def test_sidecar_empty_episodes_writes_empty_table(tmp_path: Path) -> None:
    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    writer._write_sidecar(out_dir=out_dir, episodes=[])
    sidecar_path = out_dir / "meta" / "mimicanno_segments.parquet"
    assert sidecar_path.is_file()
    table = pq.read_table(sidecar_path)  # type: ignore[no-untyped-call]
    assert table.num_rows == 0
    assert list(table.column_names) == SIDECAR_COLUMNS
