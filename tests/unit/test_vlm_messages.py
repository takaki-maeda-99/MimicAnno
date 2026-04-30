"""Tests for `build_messages` — chat-template form (transformers 5.x)."""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.vlm_labeler import VLMRequest
from mimicanno.vlm_prompt import KEYFRAMES_MARKER, build_messages, build_prompt


def _request(n_keyframes: int = 2) -> VLMRequest:
    return VLMRequest(
        task_text="Put the tape into the bottle",
        allowed_labels=[
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat",
        ],
        label_version="manipulation.v1",
        robot_type="so101",
        fps=15.0,
        episode_duration_sec=10.0,
        segment_index=0,
        segment_total=8,
        segment_id="s_000",
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)] * n_keyframes,
        keyframe_offsets_sec=[float(i) for i in range(n_keyframes)],
        robot_state_summary={
            "duration_sec": 1.0,
            "mean_eef_speed_mps": 0.05,
            "gripper_open_fraction": 0.5,
            "gripper_transitions": 0,
            "dwell_fraction": 0.2,
        },
    )


def test_returns_single_user_message() -> None:
    msgs = build_messages(_request(), attempt=1, last_reject_reason=None)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_image_block_count_matches_keyframe_count() -> None:
    """The crucial invariant for transformers 5.x: number of image content
    blocks == number of images later passed to processor(images=...)."""
    for n in (1, 2, 4, 8):
        msgs = build_messages(_request(n_keyframes=n), attempt=1, last_reject_reason=None)
        content = msgs[0]["content"]
        image_blocks = [b for b in content if b["type"] == "image"]
        assert len(image_blocks) == n, f"keyframes={n}: got {len(image_blocks)} image blocks"


def test_text_blocks_contain_full_prompt_content() -> None:
    """Concatenating the text blocks should reconstitute the build_prompt
    output (modulo the [KEYFRAMES] marker which is replaced by image blocks)."""
    req = _request(n_keyframes=2)
    msgs = build_messages(req, attempt=1, last_reject_reason=None)
    text_blocks = [b["text"] for b in msgs[0]["content"] if b["type"] == "text"]
    combined = "\n".join(text_blocks)
    expected_text = build_prompt(req, attempt=1, last_reject_reason=None)
    # Marker should NOT appear in the chat-template output.
    for tb in text_blocks:
        assert KEYFRAMES_MARKER not in tb
    # Both fragments before/after the marker should be present in the combined text.
    before, _, after = expected_text.partition(KEYFRAMES_MARKER)
    assert before.rstrip("\n") in combined
    assert after.lstrip("\n") in combined


def test_block_order_is_text_images_text() -> None:
    """Order matters: pre-text → images → post-text. This is what gives
    apply_chat_template the right context for the visual reasoning."""
    msgs = build_messages(_request(n_keyframes=3), attempt=1, last_reject_reason=None)
    types = [b["type"] for b in msgs[0]["content"]]
    # First block is text, last block is text, all middle blocks are images.
    assert types[0] == "text"
    assert types[-1] == "text"
    assert all(t == "image" for t in types[1:-1])
    assert types.count("image") == 3


def test_retry_amendment_appears_in_post_text() -> None:
    msgs = build_messages(_request(), attempt=2, last_reject_reason="invalid_label")
    post_text = next(
        b["text"] for b in reversed(msgs[0]["content"]) if b["type"] == "text"
    )
    assert "reject_reason=invalid_label" in post_text


def test_zero_keyframes_yields_no_image_blocks() -> None:
    """Edge case (defensive): a request with no keyframes produces a valid
    messages list with zero image blocks."""
    msgs = build_messages(_request(n_keyframes=0), attempt=1, last_reject_reason=None)
    image_blocks = [b for b in msgs[0]["content"] if b["type"] == "image"]
    assert len(image_blocks) == 0
