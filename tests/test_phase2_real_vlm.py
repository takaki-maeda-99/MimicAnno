"""Real-VLM smoke (Layer 3, env-gated). Loads the pinned default Gemma 4
multimodal IT model and runs labeling on one short pre-canned segment.

NOT a CI gate. Run manually:
  MIMICANNO_RUN_VLM_SMOKE=1 \
    env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
    .venv/bin/pytest tests/test_phase2_real_vlm.py -v
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_VLM_SMOKE") != "1",
    reason="real-VLM smoke is opt-in via MIMICANNO_RUN_VLM_SMOKE=1",
)


def test_real_vlm_labels_one_segment_to_a_valid_phase() -> None:
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available; skipping real-VLM smoke")

    import numpy as np

    from mimicanno.config import VLMConfig
    from mimicanno.preflight import resolve_vlm_model
    from mimicanno.vlm_labeler import (
        DEFAULT_LOCAL_GEMMA_MODEL_ID,
        LocalGemmaVLMLabeler,
        VLMRequest,
    )

    pre = resolve_vlm_model(DEFAULT_LOCAL_GEMMA_MODEL_ID, offline=False)
    cfg = VLMConfig(
        model_id=pre.model_id, resolved_checkpoint=pre.resolved_checkpoint,
        device="cuda", dtype="bfloat16", max_retries=1, max_output_tokens=128,
    )
    lab = LocalGemmaVLMLabeler(cfg)
    req = VLMRequest(
        task_text="Pick the red block and place it in the white bin.",
        allowed_labels=[
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat",
        ],
        label_version="manipulation.v1", robot_type="aloha",
        fps=30.0, episode_duration_sec=2.0, segment_index=1, segment_total=1,
        segment_id="s_000",
        keyframes=[np.zeros((224, 224, 3), dtype=np.uint8)] * 4,
        keyframe_offsets_sec=[0.0, 0.5, 1.0, 1.5],
        robot_state_summary={
            "duration_sec": 2.0, "mean_eef_speed_mps": 0.05,
            "gripper_open_fraction": 0.5, "gripper_transitions": 0,
            "dwell_fraction": 0.3,
        },
    )
    resp = lab.label_segment(req, attempt=1)
    assert resp["phase"] in set(req["allowed_labels"]) | {"unknown"}
    assert 0.0 <= resp["vlm_confidence"] <= 1.0
