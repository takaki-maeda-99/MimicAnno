"""Phase 3 prompt assembly tests with ObjectStateSummary (spec §5.4)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from mimicanno.schema import ObjectStateSummary
from mimicanno.vlm_labeler import VLMRequest
from mimicanno.vlm_prompt import build_prompt

SNAPS = Path(__file__).resolve().parents[1] / "snapshots" / "phase3"


def _request() -> VLMRequest:
    """Canonical VLMRequest matching Phase 2 test (for byte-identity checks)."""
    return VLMRequest(
        task_text="Pick the red block and place it in the white bin.",
        allowed_labels=[
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat",
        ],
        label_version="manipulation.v1",
        robot_type="aloha",
        fps=30.0,
        episode_duration_sec=15.13,
        segment_index=3,
        segment_total=8,
        segment_id="s_003",
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0, 0.5, 1.0, 1.5],
        robot_state_summary={
            "duration_sec": 1.83,
            "mean_eef_speed_mps": 0.082,
            "gripper_open_fraction": 0.41,
            "gripper_transitions": 1,
            "dwell_fraction": 0.12,
        },
    )


def test_phase2_byte_identity_when_omitted() -> None:
    """Byte-identical to Phase 2 when object_state_summary field is omitted."""
    req = _request()
    # Don't include object_state_summary key in request at all
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    expected = (SNAPS / "prompt_phase2_byte_identical.txt").read_text(encoding="utf-8")
    assert got == expected


def test_phase2_byte_identity_when_none() -> None:
    """Byte-identical to Phase 2 when object_state_summary=None explicitly."""
    req = _request()
    req["object_state_summary"] = None
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    expected = (SNAPS / "prompt_phase2_byte_identical.txt").read_text(encoding="utf-8")
    assert got == expected


def test_phase3_mode_adds_two_system_blocks() -> None:
    """Phase 3 mode adds 2 SYSTEM sub-blocks when object_state_summary is non-None."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.42,
        gripper_object_distance_at_end=0.41,
        gripper_object_distance_min=0.03,
        primary_object_displacement=0.18,
        primary_object_max_speed=0.32,
        primary_object_at_target_at_end=True,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    # Check that both new blocks are present
    assert "Tracked entities in this scene:" in got
    assert "Object-state summary for this segment:" in got
    # Advisory line must be present
    assert "(Prefer one of the listed" in got


def test_phase3_prompt_snapshot_byte_stable() -> None:
    """Phase 3 prompt with canonical ObjectStateSummary matches snapshot."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["red block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.42,
        gripper_object_distance_at_end=0.41,
        gripper_object_distance_min=0.03,
        primary_object_displacement=0.18,
        primary_object_max_speed=0.32,
        primary_object_at_target_at_end=True,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    expected = (SNAPS / "prompt_phase3_full.txt").read_text(encoding="utf-8")
    assert got == expected


def test_empty_lists_render_as_brackets() -> None:
    """Empty *_prompts lists render as []."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=[],
        target_prompts=[],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.42,
        gripper_object_distance_at_end=0.41,
        gripper_object_distance_min=0.03,
        primary_object_displacement=0.18,
        primary_object_max_speed=0.32,
        primary_object_at_target_at_end=True,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "objects: []" in got
    assert "targets: []" in got
    assert "tools:   []" in got


def test_float_formatting_6g() -> None:
    """Float values format with :.6g precision."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["obj"],
        target_prompts=["tgt"],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.123456789,
        gripper_object_distance_at_end=0.999999999,
        gripper_object_distance_min=0.000000123,
        primary_object_displacement=0.5,
        primary_object_max_speed=1.23,
        primary_object_at_target_at_end=None,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    # 0.123456789 with :.6g should be 0.123457
    assert "gripper_object_distance_at_start: 0.123457" in got
    # 0.999999999 with :.6g should be 1 (with alignment spacing)
    assert "gripper_object_distance_at_end:   1" in got
    # 0.000000123 with :.6g should be 1.23e-07 (with alignment spacing)
    assert "gripper_object_distance_min:      1.23e-07" in got


def test_null_rendering_for_none_scalars() -> None:
    """None scalar values render as 'null' (JSON-style)."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["obj"],
        target_prompts=["tgt"],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=None,
        gripper_object_distance_at_end=None,
        gripper_object_distance_min=None,
        primary_object_displacement=None,
        primary_object_max_speed=None,
        primary_object_at_target_at_end=None,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "gripper_object_distance_at_start: null" in got
    assert "gripper_object_distance_at_end:   null" in got
    assert "gripper_object_distance_min:      null" in got
    assert "primary_object_displacement:      null" in got
    assert "primary_object_max_speed:         null" in got
    assert "primary_object_at_target_at_end:  null" in got


def test_boolean_rendering() -> None:
    """Boolean values render as 'true' / 'false' (JSON-style)."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["obj"],
        target_prompts=["tgt"],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.5,
        gripper_object_distance_at_end=0.5,
        gripper_object_distance_min=0.5,
        primary_object_displacement=0.5,
        primary_object_max_speed=0.5,
        primary_object_at_target_at_end=True,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "primary_object_at_target_at_end:  true" in got

    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["obj"],
        target_prompts=["tgt"],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.5,
        gripper_object_distance_at_end=0.5,
        gripper_object_distance_min=0.5,
        primary_object_displacement=0.5,
        primary_object_max_speed=0.5,
        primary_object_at_target_at_end=False,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "primary_object_at_target_at_end:  false" in got


def test_advisory_line_always_present_phase3() -> None:
    """Advisory line always present in Phase 3 mode (even with empty lists)."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=[],
        target_prompts=[],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=None,
        gripper_object_distance_at_end=None,
        gripper_object_distance_min=None,
        primary_object_displacement=None,
        primary_object_max_speed=None,
        primary_object_at_target_at_end=None,
    )
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "(Prefer one of the listed" in got


def test_retry_amendment_placement_unchanged() -> None:
    """Retry amendment goes at END (after Phase 3 sub-blocks)."""
    req = _request()
    req["object_state_summary"] = ObjectStateSummary(
        object_prompts=["obj"],
        target_prompts=["tgt"],
        tool_prompts=[],
        visible_track_ids=[],
        gripper_object_distance_at_start=0.5,
        gripper_object_distance_at_end=0.5,
        gripper_object_distance_min=0.5,
        primary_object_displacement=0.5,
        primary_object_max_speed=0.5,
        primary_object_at_target_at_end=True,
    )
    got = build_prompt(req, attempt=2, last_reject_reason="invalid_label")
    # Amendment text should be present
    assert "Your previous response was rejected" in got
    # Amendment should be at the end
    assert got.endswith("Re-emit the JSON object exactly per the schema.\n")
