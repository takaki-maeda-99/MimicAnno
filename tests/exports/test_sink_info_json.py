"""info.json features merger (Phase 5 Task 15, spec §4.4)."""

from __future__ import annotations

import json
from pathlib import Path

from mimicanno.exports.sink_lerobot_v3 import LeRobotV3SinkWriter
from tests.exports._helpers import (
    make_canonical_episode,
    make_profile,
    write_source_dataset,
)


def test_info_json_features_added_and_other_keys_preserved(tmp_path: Path) -> None:
    ep = make_canonical_episode(episode_index=0, num_frames=3)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path)

    writer = LeRobotV3SinkWriter()
    writer._write_info_json(out_dir=out, source_dataset=src, profile=profile)

    out_info = out / "meta" / "info.json"
    assert out_info.is_file()
    data = json.loads(out_info.read_text())

    # Top-level keys preserved verbatim
    src_data = json.loads((src / "meta" / "info.json").read_text())
    for key in ("codebase_version", "total_episodes", "chunks_size", "fps",
                "splits", "data_path", "video_path"):
        assert data[key] == src_data[key]

    # New features added
    feats = data["features"]
    assert "subtask_index" in feats
    assert feats["subtask_index"]["dtype"] == "int64"
    assert feats["subtask_index"]["shape"] == [1]
    assert feats["subtask_index"]["names"] is None

    assert "mimicanno.ee_delta_6d" in feats
    assert feats["mimicanno.ee_delta_6d"]["dtype"] == "float32"
    assert feats["mimicanno.ee_delta_6d"]["shape"] == [6]
    assert feats["mimicanno.ee_delta_6d"]["names"] == [
        "dx", "dy", "dz", "drx", "dry", "drz"
    ]

    assert "mimicanno.gripper_normalized" in feats
    assert feats["mimicanno.gripper_normalized"]["shape"] == [1]
    assert feats["mimicanno.gripper_normalized"]["names"] is None

    assert "mimicanno.gripper_delta" in feats
    assert feats["mimicanno.gripper_delta"]["shape"] == [1]

    # Existing features preserved
    assert "observation.state" in feats
    assert feats["observation.state"]["shape"] == [6]


def test_info_json_indent_two_spaces(tmp_path: Path) -> None:
    """LeRobot convention: indent with 2 spaces."""
    ep = make_canonical_episode(episode_index=0, num_frames=3)
    src = tmp_path / "src"
    src.mkdir()
    write_source_dataset(src, episodes=[ep])

    out = tmp_path / "out"
    out.mkdir()
    profile = make_profile(tmp_dir=tmp_path)
    writer = LeRobotV3SinkWriter()
    writer._write_info_json(out_dir=out, source_dataset=src, profile=profile)

    text = (out / "meta" / "info.json").read_text()
    # Spot-check the 2-space indent on a nested key
    assert '\n  "features"' in text or '\n  "data_path"' in text
