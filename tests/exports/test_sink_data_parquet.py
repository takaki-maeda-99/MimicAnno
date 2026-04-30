"""Per-frame data parquet writer (Phase 5 Task 13, spec §4.1)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    make_segment,
    write_source_dataset,
)


def test_data_parquet_preserves_source_columns_and_adds_subtask_index(
    tmp_path: Path,
) -> None:
    ep = make_canonical_episode(
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
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path)
    registry = {"approach": 0, "grasp": 1}

    writer = LeRobotV3SinkWriter()
    writer._write_data_parquet(
        out_dir=out,
        source_dataset=src,
        episode=ep,
        registry=registry,
        profile=profile,
    )

    out_path = out / "data" / "chunk-000" / "episode_000000.parquet"
    assert out_path.is_file()
    table = pq.read_table(out_path)  # type: ignore[no-untyped-call]

    # Source columns preserved
    for col in (
        "timestamp",
        "frame_index",
        "episode_index",
        "observation.state.gripper_pos",
        "observation.state.ee_pos",
        "observation.state.ee_rotvec",
        "observation.state",
        "action.joint_pos",
        "action.gripper_pos",
    ):
        assert col in table.column_names

    # subtask_index added with correct mapping
    assert "subtask_index" in table.column_names
    assert table.column("subtask_index").to_pylist() == [0, 0, 1, 1]
    assert str(table.schema.field("subtask_index").type) == "int64"

    # Extras added with profile dtype
    for name in (
        "mimicanno.ee_delta_6d",
        "mimicanno.gripper_normalized",
        "mimicanno.gripper_delta",
    ):
        assert name in table.column_names
    # ee_delta_6d shape: (T, 6)
    edd = table.column("mimicanno.ee_delta_6d").to_pylist()
    assert len(edd) == 4
    assert all(len(row) == 6 for row in edd)


def test_data_parquet_gap_frame_uses_unlabeled_index(tmp_path: Path) -> None:
    """Gap frames receive the unlabeled subtask_index (never 0-padded)."""
    ep = make_canonical_episode(
        episode_index=0,
        num_frames=4,
        segments=[
            # Covers frames 0..1 only
            make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=1,
                phase="approach",
            ),
        ],
    )
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path, extra_per_frame_columns=[])

    # Registry mirrors what _write_subtasks_registry would produce (with gap)
    registry = {"approach": 0, "unlabeled": 1}

    writer = LeRobotV3SinkWriter()
    writer._write_data_parquet(
        out_dir=out,
        source_dataset=src,
        episode=ep,
        registry=registry,
        profile=profile,
    )
    out_path = out / "data" / "chunk-000" / "episode_000000.parquet"
    table = pq.read_table(out_path)  # type: ignore[no-untyped-call]
    # Frames 0,1 -> approach (0); frames 2,3 -> unlabeled (1)
    assert table.column("subtask_index").to_pylist() == [0, 0, 1, 1]
