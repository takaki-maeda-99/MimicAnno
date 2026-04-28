# tests/unit/test_tracks_json_schema.py
"""Round-trip + §3.2 validation rule tests for TracksFile schema."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from mimicanno.errors import ArtifactIntegrityError
from mimicanno.hashing import canonical_json
from mimicanno.io import read_tracks_json, write_tracks_json
from mimicanno.schema import (
    TracksFile,
    TracksGap,
    TracksSample,
    TracksStats,
    TracksTrack,
    TracksTrackingPlan,
)

_SNAPSHOT_PATH = (
    Path(__file__).parent.parent / "snapshots" / "phase3" / "tracks_json_smoke.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal() -> TracksFile:
    """Return the §3.1 canonical example as a TracksFile object."""
    return TracksFile(
        schema_version="0.1.0",
        episode_id="episode_000",
        fps=30.0,
        n_frames=1275,
        image_width=1280,
        image_height=720,
        track_stride_frames=10,
        tracking_plan=TracksTrackingPlan(
            task_text="pick up the red block and place it in bin A",
            object_prompts=["red block"],
            target_prompts=["bin A"],
            tool_prompts=["gripper"],
            failed_prompts=[],
        ),
        tracks=[
            TracksTrack(
                track_id="obj:object:red_block:0",
                role="object",
                prompt="red block",
                slug="red_block",
                index=0,
                primary=True,
                samples=[
                    TracksSample(frame=0, time_sec=0.0, bbox=[0.412, 0.530, 0.085, 0.072], score=0.91),
                    TracksSample(frame=10, time_sec=0.333333, bbox=[0.418, 0.531, 0.084, 0.073], score=0.93),
                    TracksSample(frame=20, time_sec=0.666667, bbox=[0.430, 0.527, 0.084, 0.071], score=0.88),
                ],
                gap_events=[
                    TracksGap(from_frame=320, to_frame=360, reason="sam3_lost"),
                ],
            ),
        ],
        stats=TracksStats(
            n_tracks=1,
            n_samples_total=3,
            mean_track_score=0.87,
            tracking_wall_time_sec=38.4,
        ),
    )


# ---------------------------------------------------------------------------
# Round-trip test
# ---------------------------------------------------------------------------


def test_round_trip_spec_example():
    """The §3.1 canonical example survives from_dict(to_dict(...)) unchanged."""
    tf = _make_minimal()
    d = tf.to_dict()
    tf2 = TracksFile.from_dict(d)
    assert tf2.to_dict() == d


def test_round_trip_via_io(tmp_path: Path):
    """write_tracks_json / read_tracks_json round-trips cleanly."""
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    tf2 = read_tracks_json(out)
    assert tf2.to_dict() == tf.to_dict()


# ---------------------------------------------------------------------------
# §3.2 field-contract negative tests (raise ValueError from from_dict)
# ---------------------------------------------------------------------------


def test_schema_version_wrong():
    d = _make_minimal().to_dict()
    d["schema_version"] = "9.9.9"
    with pytest.raises(ValueError, match="schema_version"):
        TracksFile.from_dict(d)


def test_fps_not_positive():
    d = _make_minimal().to_dict()
    d["fps"] = 0.0
    with pytest.raises(ValueError, match="fps"):
        TracksFile.from_dict(d)


def test_fps_negative():
    d = _make_minimal().to_dict()
    d["fps"] = -1.0
    with pytest.raises(ValueError, match="fps"):
        TracksFile.from_dict(d)


def test_n_frames_zero():
    d = _make_minimal().to_dict()
    d["n_frames"] = 0
    with pytest.raises(ValueError, match="n_frames"):
        TracksFile.from_dict(d)


def test_image_width_zero():
    d = _make_minimal().to_dict()
    d["image_size"]["width"] = 0
    with pytest.raises(ValueError, match="width"):
        TracksFile.from_dict(d)


def test_image_height_zero():
    d = _make_minimal().to_dict()
    d["image_size"]["height"] = 0
    with pytest.raises(ValueError, match="height"):
        TracksFile.from_dict(d)


def test_track_stride_frames_zero():
    d = _make_minimal().to_dict()
    d["track_stride_frames"] = 0
    with pytest.raises(ValueError, match="track_stride_frames"):
        TracksFile.from_dict(d)


def test_bbox_x_out_of_unit_square():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [-0.1, 0.5, 0.1, 0.1]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_bbox_w_zero():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [0.1, 0.5, 0.0, 0.1]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_bbox_h_zero():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [0.1, 0.5, 0.1, 0.0]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_bbox_x_plus_w_exceeds_1():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [0.9, 0.1, 0.2, 0.1]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_bbox_y_plus_h_exceeds_1():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [0.1, 0.9, 0.1, 0.2]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_bbox_wrong_length():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["bbox"] = [0.1, 0.5, 0.1]
    with pytest.raises(ValueError, match="bbox"):
        TracksFile.from_dict(d)


def test_sample_frame_below_zero():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["frame"] = -1
    with pytest.raises(ValueError, match="frame"):
        TracksFile.from_dict(d)


def test_sample_frame_equals_n_frames():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["frame"] = d["n_frames"]  # [0, n_frames) — n_frames itself is invalid
    with pytest.raises(ValueError, match="frame"):
        TracksFile.from_dict(d)


def test_samples_not_strictly_ascending():
    d = _make_minimal().to_dict()
    # duplicate frame index
    d["tracks"][0]["samples"][1]["frame"] = 0
    with pytest.raises(ValueError, match="ascending"):
        TracksFile.from_dict(d)


def test_samples_duplicate_frames():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["frame"] = 10  # same as index 1
    with pytest.raises(ValueError, match="ascending"):
        TracksFile.from_dict(d)


def test_sample_score_below_zero():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["score"] = -0.1
    with pytest.raises(ValueError, match="score"):
        TracksFile.from_dict(d)


def test_sample_score_above_one():
    d = _make_minimal().to_dict()
    d["tracks"][0]["samples"][0]["score"] = 1.1
    with pytest.raises(ValueError, match="score"):
        TracksFile.from_dict(d)


def test_gap_reason_unknown():
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"][0]["reason"] = "sam3_reacquired"
    with pytest.raises(ValueError, match="reason"):
        TracksFile.from_dict(d)


def test_gap_from_frame_negative():
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"][0]["from_frame"] = -1
    with pytest.raises(ValueError, match="from_frame"):
        TracksFile.from_dict(d)


def test_gap_to_frame_equals_n_frames():
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"][0]["to_frame"] = d["n_frames"]
    with pytest.raises(ValueError, match="to_frame"):
        TracksFile.from_dict(d)


def test_gap_from_frame_exceeds_to_frame():
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"][0]["from_frame"] = 400
    d["tracks"][0]["gap_events"][0]["to_frame"] = 300
    with pytest.raises(ValueError, match="from_frame"):
        TracksFile.from_dict(d)


def test_track_role_invalid():
    d = _make_minimal().to_dict()
    d["tracks"][0]["role"] = "unknown_role"
    with pytest.raises(ValueError, match="role"):
        TracksFile.from_dict(d)


def test_primary_flag_more_than_one_per_role():
    d = _make_minimal().to_dict()
    # Add a second object track also marked primary
    second = dict(d["tracks"][0])
    second["track_id"] = "obj:object:blue_block:0"
    second["prompt"] = "blue block"
    second["slug"] = "blue_block"
    second["primary"] = True
    d["tracks"].append(second)
    with pytest.raises(ValueError, match="primary"):
        TracksFile.from_dict(d)


def test_stats_n_tracks_mismatch():
    d = _make_minimal().to_dict()
    d["stats"]["n_tracks"] = 99
    with pytest.raises(ValueError, match="n_tracks"):
        TracksFile.from_dict(d)


def test_stats_n_samples_mismatch():
    d = _make_minimal().to_dict()
    d["stats"]["n_samples_total"] = 99
    with pytest.raises(ValueError, match="n_samples"):
        TracksFile.from_dict(d)


def test_stats_wall_time_negative():
    d = _make_minimal().to_dict()
    d["stats"]["tracking_wall_time_sec"] = -1.0
    with pytest.raises(ValueError, match="tracking_wall_time"):
        TracksFile.from_dict(d)


def test_track_id_duplicate_within_file():
    """spec §3.2: track_id must be unique within the file."""
    d = _make_minimal().to_dict()
    second = dict(d["tracks"][0])
    second["primary"] = False  # avoid triggering the primary-role check
    second["role"] = "target"
    # keep the same track_id — this is the violation
    d["tracks"].append(second)
    d["stats"]["n_tracks"] = 2
    d["stats"]["n_samples_total"] = 6
    with pytest.raises(ValueError, match="track_id"):
        TracksFile.from_dict(d)


def test_gap_events_not_frame_ascending():
    """spec §3.2: gap_events must be strictly frame-ascending."""
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"] = [
        {"from_frame": 500, "to_frame": 600, "reason": "sam3_lost"},
        {"from_frame": 200, "to_frame": 300, "reason": "sam3_lost"},
    ]
    with pytest.raises(ValueError, match="frame-ascending"):
        TracksFile.from_dict(d)


def test_gap_events_overlapping():
    """spec §3.2: gap_events must be non-overlapping (prev.to_frame < curr.from_frame)."""
    d = _make_minimal().to_dict()
    d["tracks"][0]["gap_events"] = [
        {"from_frame": 100, "to_frame": 300, "reason": "sam3_lost"},
        {"from_frame": 200, "to_frame": 400, "reason": "sam3_lost"},
    ]
    with pytest.raises(ValueError, match="frame-ascending"):
        TracksFile.from_dict(d)


# ---------------------------------------------------------------------------
# NaN handling for mean_track_score
# ---------------------------------------------------------------------------


def test_mean_track_score_nan_serializes_as_null():
    tf = TracksFile(
        schema_version="0.1.0",
        episode_id="episode_000",
        fps=30.0,
        n_frames=1275,
        image_width=1280,
        image_height=720,
        track_stride_frames=10,
        tracking_plan=TracksTrackingPlan(
            task_text="task",
            object_prompts=[],
            target_prompts=[],
            tool_prompts=[],
            failed_prompts=[],
        ),
        tracks=[],
        stats=TracksStats(
            n_tracks=0,
            n_samples_total=0,
            mean_track_score=float("nan"),
            tracking_wall_time_sec=0.0,
        ),
    )
    d = tf.to_dict()
    assert d["stats"]["mean_track_score"] is None


def test_mean_track_score_null_roundtrips():
    tf = TracksFile(
        schema_version="0.1.0",
        episode_id="episode_000",
        fps=30.0,
        n_frames=1275,
        image_width=1280,
        image_height=720,
        track_stride_frames=10,
        tracking_plan=TracksTrackingPlan(
            task_text="task",
            object_prompts=[],
            target_prompts=[],
            tool_prompts=[],
            failed_prompts=[],
        ),
        tracks=[],
        stats=TracksStats(
            n_tracks=0,
            n_samples_total=0,
            mean_track_score=float("nan"),
            tracking_wall_time_sec=0.0,
        ),
    )
    d = tf.to_dict()
    tf2 = TracksFile.from_dict(d)
    assert math.isnan(tf2.stats.mean_track_score)


# ---------------------------------------------------------------------------
# Cross-artifact integrity check (§3.3) — ArtifactIntegrityError
# ---------------------------------------------------------------------------


def test_read_tracks_json_episode_id_mismatch(tmp_path: Path):
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    with pytest.raises(ArtifactIntegrityError):
        read_tracks_json(out, expected=("wrong_episode", 30.0, 1275))


def test_read_tracks_json_fps_mismatch(tmp_path: Path):
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    with pytest.raises(ArtifactIntegrityError):
        read_tracks_json(out, expected=("episode_000", 25.0, 1275))


def test_read_tracks_json_n_frames_mismatch(tmp_path: Path):
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    with pytest.raises(ArtifactIntegrityError):
        read_tracks_json(out, expected=("episode_000", 30.0, 9999))


def test_read_tracks_json_expected_matches_succeeds(tmp_path: Path):
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    tf2 = read_tracks_json(out, expected=("episode_000", 30.0, 1275))
    assert tf2.episode_id == "episode_000"


def test_read_tracks_json_no_expected_succeeds(tmp_path: Path):
    tf = _make_minimal()
    out = tmp_path / "tracks.json"
    write_tracks_json(out, tf)
    tf2 = read_tracks_json(out)
    assert tf2.episode_id == "episode_000"


# ---------------------------------------------------------------------------
# Snapshot byte-equality test (Step 6.5)
# ---------------------------------------------------------------------------


def test_snapshot_reserializes_byte_equal():
    """Re-serializing the committed snapshot must produce identical bytes."""
    import json

    snapshot_text = _SNAPSHOT_PATH.read_text(encoding="utf-8")
    raw = json.loads(snapshot_text)
    tf = TracksFile.from_dict(raw)
    re_serialized = canonical_json(tf.to_dict())
    assert re_serialized == snapshot_text, (
        "Snapshot byte-equality failed — the implementation changed serialization. "
        "Regenerate tests/snapshots/phase3/tracks_json_smoke.json if intentional."
    )
