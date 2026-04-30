"""Per-episode list-column writer (Phase 5 Task 14, spec §4.3)."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    make_segment,
    write_source_dataset,
)


def _two_segment_episode(episode_index: int = 0) -> object:
    eid = f"episode_{episode_index:06d}"
    return make_canonical_episode(
        episode_index=episode_index,
        num_frames=4,
        segments=[
            make_segment(
                episode_id=eid, start_frame=0, end_frame=1, phase="approach"
            ),
            make_segment(
                episode_id=eid, start_frame=2, end_frame=3, phase="grasp"
            ),
        ],
    )


def test_episodes_metadata_with_mimicanno_prefix(tmp_path: Path) -> None:
    ep0 = _two_segment_episode(episode_index=0)
    ep1 = _two_segment_episode(episode_index=1)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep0, ep1])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path, annotation_prefix="mimicanno")

    writer = LeRobotV3SinkWriter()
    writer._write_episodes_metadata(
        out_dir=out,
        source_dataset=src,
        episodes=[ep0, ep1],
        profile=profile,
    )

    out_path = out / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    assert out_path.is_file()
    table = pq.read_table(out_path)  # type: ignore[no-untyped-call]
    cols = table.column_names

    # Source columns preserved (length, tasks, episode_index)
    for c in ("episode_index", "length", "tasks"):
        assert c in cols

    # Prefixed list columns added
    assert "mimicanno_subtask_names" in cols
    assert "mimicanno_subtask_start_frames" in cols
    assert "mimicanno_subtask_end_frames" in cols

    # Row order keyed by episode_index
    rows = table.to_pylist()
    assert [r["episode_index"] for r in rows] == [0, 1]
    assert rows[0]["mimicanno_subtask_names"] == ["approach", "grasp"]
    assert rows[0]["mimicanno_subtask_start_frames"] == [0, 2]
    assert rows[0]["mimicanno_subtask_end_frames"] == [1, 3]


def test_episodes_metadata_with_bare_prefix(tmp_path: Path) -> None:
    ep = _two_segment_episode(episode_index=0)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path, annotation_prefix=None)

    writer = LeRobotV3SinkWriter()
    writer._write_episodes_metadata(
        out_dir=out,
        source_dataset=src,
        episodes=[ep],
        profile=profile,
    )

    table = pq.read_table(  # type: ignore[no-untyped-call]
        out / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    )
    cols = table.column_names
    assert "subtask_names" in cols
    assert "subtask_start_frames" in cols
    assert "subtask_end_frames" in cols
    # No prefixed columns
    assert "mimicanno_subtask_names" not in cols


def test_episodes_metadata_bare_prefix_collision_raises(tmp_path: Path) -> None:
    ep = _two_segment_episode(episode_index=0)
    src = tmp_path / "src"
    src.mkdir()
    # Source carries existing bare subtask_* columns -> must raise.
    write_source_dataset(src, episodes=[ep], bare_collision_columns=True)

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path, annotation_prefix=None)

    writer = LeRobotV3SinkWriter()
    with pytest.raises(MimicAnnoError) as ei:
        writer._write_episodes_metadata(
            out_dir=out,
            source_dataset=src,
            episodes=[ep],
            profile=profile,
        )
    assert ei.value.code == ErrorCode.EXPORT_SINK_VALIDATION_FAILED
