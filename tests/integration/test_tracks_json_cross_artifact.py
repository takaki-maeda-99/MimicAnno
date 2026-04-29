"""Spec §3.3: tracks.json cross-artifact integrity.

When the (episode_id, fps, n_frames) baked into tracks.json don't match
the manifest's expected values, `read_tracks_json(path, expected=...)`
must raise `ArtifactIntegrityError` with code
`tracks_json_integrity_violation`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mimicanno.errors import ArtifactIntegrityError
from mimicanno.io import read_tracks_json
from mimicanno.schema import TracksFile, TracksStats, TracksTrackingPlan


def _write_minimal_tracks(
    path: Path, *, episode_id: str, fps: float, n_frames: int,
) -> None:
    tf = TracksFile(
        schema_version="0.1.0",
        episode_id=episode_id,
        fps=fps,
        n_frames=n_frames,
        image_width=64,
        image_height=64,
        track_stride_frames=10,
        tracking_plan=TracksTrackingPlan(
            task_text="pick block",
            object_prompts=["red block"],
            target_prompts=[],
            tool_prompts=[],
            failed_prompts=[],
        ),
        tracks=[],
        stats=TracksStats(
            n_tracks=0,
            n_samples_total=0,
            mean_track_score=0.0,
            tracking_wall_time_sec=0.0,
        ),
    )
    path.write_text(json.dumps(tf.to_dict()))


def test_episode_id_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    p = tmp_path / "tracks.json"
    _write_minimal_tracks(p, episode_id="MISMATCH", fps=30.0, n_frames=120)
    with pytest.raises(ArtifactIntegrityError) as excinfo:
        read_tracks_json(p, expected=("real_episode", 30.0, 120))
    assert excinfo.value.code == "tracks_json_integrity_violation"
    assert excinfo.value.context["field"] == "episode_id"


def test_fps_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    p = tmp_path / "tracks.json"
    _write_minimal_tracks(p, episode_id="real_episode", fps=29.0, n_frames=120)
    with pytest.raises(ArtifactIntegrityError) as excinfo:
        read_tracks_json(p, expected=("real_episode", 30.0, 120))
    assert excinfo.value.code == "tracks_json_integrity_violation"
    assert excinfo.value.context["field"] == "fps"


def test_n_frames_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    p = tmp_path / "tracks.json"
    _write_minimal_tracks(p, episode_id="real_episode", fps=30.0, n_frames=100)
    with pytest.raises(ArtifactIntegrityError) as excinfo:
        read_tracks_json(p, expected=("real_episode", 30.0, 120))
    assert excinfo.value.code == "tracks_json_integrity_violation"
    assert excinfo.value.context["field"] == "n_frames"
