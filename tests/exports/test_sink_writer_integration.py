"""Integrator + post-write validation (Phase 5 Task 16, spec §4 / §1.1)."""

from __future__ import annotations

import json
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


def _two_segment_episode(idx: int) -> object:
    eid = f"episode_{idx:06d}"
    return make_canonical_episode(
        episode_index=idx,
        num_frames=4,
        segments=[
            make_segment(episode_id=eid, start_frame=0, end_frame=1, phase="approach"),
            make_segment(episode_id=eid, start_frame=2, end_frame=3, phase="grasp"),
        ],
    )


def test_write_all_end_to_end(tmp_path: Path) -> None:
    ep0 = _two_segment_episode(0)
    ep1 = _two_segment_episode(1)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep0, ep1])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path)

    writer = LeRobotV3SinkWriter()
    writer.write_all(
        out_dir=out,
        episodes=[ep0, ep1],
        profile=profile,
        source_dataset=src,
    )

    # subtasks.parquet
    subtasks = pq.read_table(out / "meta" / "subtasks.parquet")  # type: ignore[no-untyped-call]
    assert subtasks.num_rows >= 2
    assert list(subtasks.column_names) == ["subtask", "subtask_index", "description"]

    # data parquets
    for idx in (0, 1):
        path = out / "data" / "chunk-000" / f"episode_{idx:06d}.parquet"
        assert path.is_file()
        t = pq.read_table(path)  # type: ignore[no-untyped-call]
        assert "subtask_index" in t.column_names
        for col in (
            "mimicanno.ee_delta_6d",
            "mimicanno.gripper_normalized",
            "mimicanno.gripper_delta",
        ):
            assert col in t.column_names

    # episodes parquet
    ep_table = pq.read_table(  # type: ignore[no-untyped-call]
        out / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    )
    for c in (
        "mimicanno_subtask_names",
        "mimicanno_subtask_start_frames",
        "mimicanno_subtask_end_frames",
    ):
        assert c in ep_table.column_names

    # info.json
    info = json.loads((out / "meta" / "info.json").read_text())
    assert "subtask_index" in info["features"]
    assert "mimicanno.ee_delta_6d" in info["features"]

    # sidecar
    sidecar = pq.read_table(out / "meta" / "mimicanno_segments.parquet")  # type: ignore[no-untyped-call]
    assert sidecar.num_rows == 4  # 2 + 2 segments
    assert len(sidecar.column_names) == 31


def test_validate_output_detects_missing_subtask_index(tmp_path: Path) -> None:
    """Hand-corrupt the output and confirm validation raises."""
    ep = _two_segment_episode(0)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path)
    writer = LeRobotV3SinkWriter()
    writer.write_all(out_dir=out, episodes=[ep], profile=profile, source_dataset=src)

    # Replace data parquet with one that lacks subtask_index column.
    import pyarrow as pa

    bad = pa.table({"timestamp": [0.0, 1.0]})
    target = out / "data" / "chunk-000" / "episode_000000.parquet"
    pq.write_table(bad, target)  # type: ignore[no-untyped-call]

    with pytest.raises(MimicAnnoError) as ei:
        writer._validate_output(out_dir=out, episodes=[ep], profile=profile)
    assert ei.value.code == ErrorCode.EXPORT_SINK_VALIDATION_FAILED
