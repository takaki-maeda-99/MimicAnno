# tests/unit/test_tracks_json_failed_prompts_roundtrip.py
"""
Verify that cross-role duplicates in failed_prompts are preserved (spec §3.2).

The on-disk shape is list[{role, prompt}]; cross-role duplicates like
  [("object", "red block"), ("target", "red block")]
must NOT collapse into a single entry after round-trip.
"""

from __future__ import annotations

from mimicanno.schema import (
    TracksFile,
    TracksStats,
    TracksTrackingPlan,
)


def _make_tracks_file_with_failed_prompts() -> TracksFile:
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
            target_prompts=["red block"],  # same string, different role
            tool_prompts=[],
            failed_prompts=[
                ("object", "red block"),
                ("target", "red block"),
            ],
        ),
        tracks=[],
        stats=TracksStats(
            n_tracks=0,
            n_samples_total=0,
            mean_track_score=float("nan"),
            tracking_wall_time_sec=0.0,
        ),
    )


def test_failed_prompts_cross_role_duplicates_preserved():
    """Two (role, prompt) pairs with same prompt but different roles must survive."""
    tf = _make_tracks_file_with_failed_prompts()
    d = tf.to_dict()

    failed = d["tracking_plan"]["failed_prompts"]
    assert len(failed) == 2, f"expected 2 entries, got {len(failed)}: {failed}"

    roles = [entry["role"] for entry in failed]
    assert "object" in roles
    assert "target" in roles

    prompts = [entry["prompt"] for entry in failed]
    assert prompts == ["red block", "red block"]


def test_failed_prompts_roundtrip_preserves_count():
    """After from_dict(to_dict(...)), the two entries are still distinct."""
    tf = _make_tracks_file_with_failed_prompts()
    d = tf.to_dict()
    tf2 = TracksFile.from_dict(d)

    assert len(tf2.tracking_plan.failed_prompts) == 2


def test_failed_prompts_dict_shape_on_disk():
    """Each entry serializes as {"role": ..., "prompt": ...} — not a string."""
    tf = _make_tracks_file_with_failed_prompts()
    d = tf.to_dict()
    for entry in d["tracking_plan"]["failed_prompts"]:
        assert isinstance(entry, dict), f"expected dict, got {type(entry)}"
        assert set(entry.keys()) == {"role", "prompt"}


def test_failed_prompts_role_values_are_valid():
    """After round-trip, role values are from the allowed set."""
    tf = _make_tracks_file_with_failed_prompts()
    d = tf.to_dict()
    tf2 = TracksFile.from_dict(d)
    valid_roles = {"object", "target", "tool"}
    for role, _ in tf2.tracking_plan.failed_prompts:
        assert role in valid_roles
