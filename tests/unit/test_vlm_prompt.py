"""Prompt assembly snapshot tests (spec §3.3)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from mimicanno.vlm_labeler import VLMRequest
from mimicanno.vlm_prompt import build_prompt

SNAPS = Path(__file__).resolve().parents[1] / "snapshots" / "phase2"


def _request() -> VLMRequest:
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


def test_initial_prompt_matches_snapshot() -> None:
    got = build_prompt(_request(), attempt=1, last_reject_reason=None)
    expected = (SNAPS / "prompt_initial.txt").read_text(encoding="utf-8")
    assert got == expected


def test_retry_prompt_appends_strict_amendment() -> None:
    got = build_prompt(_request(), attempt=2, last_reject_reason="invalid_label")
    expected = (SNAPS / "prompt_retry_invalid_label.txt").read_text(encoding="utf-8")
    assert got == expected


def test_null_eef_data_rendered_as_null() -> None:
    req = _request()
    req["robot_state_summary"]["mean_eef_speed_mps"] = None
    req["robot_state_summary"]["dwell_fraction"] = None
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "mean_eef_speed_mps: null" in got
    assert "dwell_fraction: null" in got


# ---------------------------------------------------------------------------
# Task 7 (vlm-mask-overlay): color legend insertion
# ---------------------------------------------------------------------------


_LEGEND_EXAMPLE = (
    "Colored translucent overlays (~40% opacity) mark tracked objects: "
    "red=gripper, blue=red_block. An overlay may be absent in some frames "
    "if the object is temporarily occluded or out of view."
)


def test_prompt_with_legend_inserts_single_line_near_top() -> None:
    """legend != None → string appears once, in the SYSTEM block."""
    got = build_prompt(_request(), attempt=1, last_reject_reason=None,
                       legend=_LEGEND_EXAMPLE)
    assert got.count(_LEGEND_EXAMPLE) == 1
    # Inserted before the "Allowed phase labels" section.
    legend_idx = got.index(_LEGEND_EXAMPLE)
    allowed_idx = got.index("Allowed phase labels")
    assert legend_idx < allowed_idx
    # And after the "This is segment ..." intro.
    intro_idx = got.index("This is segment")
    assert intro_idx < legend_idx


def test_prompt_with_legend_none_is_byte_identical_to_default() -> None:
    """legend=None reproduces the snapshot exactly (spec §6.1 backward-compat)."""
    got_default = build_prompt(_request(), attempt=1, last_reject_reason=None)
    got_explicit_none = build_prompt(_request(), attempt=1,
                                     last_reject_reason=None, legend=None)
    assert got_default == got_explicit_none
    expected = (SNAPS / "prompt_initial.txt").read_text(encoding="utf-8")
    assert got_explicit_none == expected
