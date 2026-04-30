"""Subtasks registry writer (Phase 5 Task 12, spec §4.2)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from tests.exports._helpers import make_canonical_episode, make_segment


def test_subtasks_registry_first_appearance_order(tmp_path: Path) -> None:
    """Order: first appearance across all episodes."""
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
                end_frame=0,
                phase="grasp",  # already seen
            ),
            make_segment(
                episode_id="episode_000001",
                start_frame=1,
                end_frame=2,
                phase="lift",  # new
            ),
        ],
    )

    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    registry = writer._write_subtasks_registry(
        out_dir=out_dir, episodes=[ep0, ep1]
    )

    assert registry == {"approach": 0, "grasp": 1, "lift": 2}

    table = pq.read_table(out_dir / "meta" / "subtasks.parquet")  # type: ignore[no-untyped-call]
    assert list(table.column_names) == ["subtask", "subtask_index", "description"]
    rows = table.to_pylist()
    assert rows == [
        {"subtask": "approach", "subtask_index": 0, "description": ""},
        {"subtask": "grasp", "subtask_index": 1, "description": ""},
        {"subtask": "lift", "subtask_index": 2, "description": ""},
    ]


def test_subtasks_registry_includes_unlabeled_when_present(tmp_path: Path) -> None:
    ep = make_canonical_episode(
        episode_index=0,
        num_frames=2,
        segments=[
            make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=1,
                phase="unlabeled",
            )
        ],
    )
    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    registry = writer._write_subtasks_registry(out_dir=out_dir, episodes=[ep])
    assert "unlabeled" in registry


def test_subtasks_registry_gap_fill_adds_unlabeled(tmp_path: Path) -> None:
    """Gap in segment coverage triggers ``unlabeled`` injection per spec §4.1."""
    ep = make_canonical_episode(
        episode_index=0,
        num_frames=5,  # frames 0..4
        segments=[
            # Covers frames 0..1 only — frames 2..4 have no segment (gap).
            make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=1,
                phase="approach",
            )
        ],
    )
    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    registry = writer._write_subtasks_registry(out_dir=out_dir, episodes=[ep])
    assert "approach" in registry
    assert "unlabeled" in registry


def test_subtasks_registry_no_gap_no_unlabeled(tmp_path: Path) -> None:
    """When coverage is full, ``unlabeled`` is NOT injected."""
    ep = make_canonical_episode(
        episode_index=0,
        num_frames=3,
        segments=[
            make_segment(
                episode_id="episode_000000",
                start_frame=0,
                end_frame=2,
                phase="approach",
            )
        ],
    )
    writer = LeRobotV3SinkWriter()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    registry = writer._write_subtasks_registry(out_dir=out_dir, episodes=[ep])
    assert registry == {"approach": 0}
