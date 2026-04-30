"""SinkWriter protocol + LeRobotV3SinkWriter skeleton (Phase 5 Task 10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mimicanno.exports.sink_base import SinkWriter
from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter


def test_lerobot_v3_implements_sink_writer_protocol() -> None:
    writer = LeRobotV3SinkWriter()
    # Protocol structural check
    assert isinstance(writer, SinkWriter)


def test_write_all_raises_not_implemented(tmp_path: Path) -> None:
    writer = LeRobotV3SinkWriter()
    with pytest.raises(NotImplementedError):
        writer.write_all(
            out_dir=tmp_path, episodes=[], profile=None, source_dataset=tmp_path
        )  # type: ignore[arg-type]
