"""Task 11 (vlm-mask-overlay): MIMICANNO_VLM_DUMP_DIR captures overlay-baked
keyframes + the mask_overlay_legend in request.json.

The dump hook itself is unchanged — overlay baking happens upstream in
``_build_request`` via ``ClipFeatureExtractor``. These tests pin that
contract so a future refactor that puts the overlay step elsewhere
can't silently desync the dump artifacts from what Gemma actually saw.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from mimicanno.vlm_labeler import VLMRequest, _maybe_dump_vlm_input


def _make_request_with_overlay(keyframe: np.ndarray) -> VLMRequest:
    req = VLMRequest(
        task_text="x",
        allowed_labels=["idle"],
        label_version="manipulation.v1",
        robot_type="so101",
        fps=15.0,
        episode_duration_sec=1.0,
        segment_index=1,
        segment_total=1,
        segment_id="s_000",
        keyframes=[keyframe],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0,
            "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.0,
            "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )
    req["mask_overlay_legend"] = (
        "Colored translucent overlays (~40% opacity) mark tracked objects: "
        "red=tape. An overlay may be absent in some frames if the object "
        "is temporarily occluded or out of view."
    )
    return req


def test_dump_keyframe_is_overlay_baked(tmp_path: Path, monkeypatch) -> None:
    """The PNG written under <dump_dir>/<seg>/attempt_N/keyframe_*.png must
    be pixel-identical to the in-memory keyframe (which is already overlay-
    baked by ClipFeatureExtractor when mask_cache is wired in)."""
    monkeypatch.setenv("MIMICANNO_VLM_DUMP_DIR", str(tmp_path))

    # Synthesize an "overlay-baked" keyframe: half black, half saturated red.
    h, w = 16, 16
    keyframe = np.zeros((h, w, 3), dtype=np.uint8)
    keyframe[:, w // 2:, 0] = 255  # right half is red

    req = _make_request_with_overlay(keyframe)
    _maybe_dump_vlm_input(
        req, prompt="hello", attempt=1, last_reject_reason=None,
    )

    png = tmp_path / "s_000" / "attempt_1" / "keyframe_00.png"
    assert png.is_file()
    from PIL import Image
    loaded = np.array(Image.open(png).convert("RGB"))
    np.testing.assert_array_equal(loaded, keyframe)


def test_dump_request_json_includes_legend(tmp_path: Path, monkeypatch) -> None:
    """request.json carries the mask_overlay_legend so v2 (no overlay)
    vs v3 (overlay) dumps are diff-able by humans."""
    monkeypatch.setenv("MIMICANNO_VLM_DUMP_DIR", str(tmp_path))
    req = _make_request_with_overlay(np.zeros((4, 4, 3), dtype=np.uint8))
    _maybe_dump_vlm_input(
        req, prompt="hello", attempt=1, last_reject_reason=None,
    )
    meta = json.loads(
        (tmp_path / "s_000" / "attempt_1" / "request.json").read_text()
    )
    assert meta["mask_overlay_legend"] is not None
    assert "red=tape" in meta["mask_overlay_legend"]


def test_dump_request_json_legend_null_when_overlay_off(
    tmp_path: Path, monkeypatch,
) -> None:
    """When overlay is off, mask_overlay_legend is absent from the request;
    request.json should record null (not raise)."""
    monkeypatch.setenv("MIMICANNO_VLM_DUMP_DIR", str(tmp_path))
    req = VLMRequest(
        task_text="x",
        allowed_labels=["idle"],
        label_version="manipulation.v1",
        robot_type="so101",
        fps=15.0,
        episode_duration_sec=1.0,
        segment_index=1,
        segment_total=1,
        segment_id="s_001",
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0,
            "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.0,
            "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )
    _maybe_dump_vlm_input(
        req, prompt="x", attempt=1, last_reject_reason=None,
    )
    meta = json.loads(
        (tmp_path / "s_001" / "attempt_1" / "request.json").read_text()
    )
    assert meta["mask_overlay_legend"] is None
