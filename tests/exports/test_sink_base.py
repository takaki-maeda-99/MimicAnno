"""SinkWriter protocol + LeRobotV3SinkWriter (Phase 5 Task 10)."""

from __future__ import annotations

from mimicanno.exports.sink_base import SinkWriter
from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter


def test_lerobot_v3_implements_sink_writer_protocol() -> None:
    writer = LeRobotV3SinkWriter()
    # Protocol structural check
    assert isinstance(writer, SinkWriter)
