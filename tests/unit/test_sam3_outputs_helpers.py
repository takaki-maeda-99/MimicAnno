"""Unit tests for the sam3 native outputs-dict helpers
(``_outputs_to_bbox_score_list`` and ``_outputs_to_bbox_score``).

These helpers map the ``{out_obj_ids, out_boxes_xywh, out_probs, ...}`` dict
that ``Sam3VideoPredictor.handle_request/handle_stream_request`` returns into
MimicAnno's ``BBox`` value objects. Coordinate convention (top-left xywh,
normalized [0,1]) is verified by ``scripts/smoke_sam3_bbox_only.py``.

Spec: docs/superpowers/specs/2026-05-04-sam3-submodule-backend-design.md §4.1, §4.2
Plan: docs/superpowers/plans/2026-05-04-sam3-submodule-backend-plan.md Task 5
"""

from __future__ import annotations

import numpy as np
import pytest

from mimicanno.object_tracker.propagator import BBox
from mimicanno.object_tracker.sam3_runtime import (
    _coerce_outputs_arrays,
    _outputs_to_bbox_score,
    _outputs_to_bbox_score_list,
)


def _make_outputs(
    obj_ids: list[int],
    boxes: list[list[float]],
    probs: list[float],
) -> dict:
    """Mirrors the actual sam3 output dict shape (verified 2026-05-04 smoke)."""
    return {
        "out_obj_ids": np.asarray(obj_ids, dtype=np.int64),
        "out_boxes_xywh": np.asarray(boxes, dtype=np.float32).reshape(-1, 4),
        "out_probs": np.asarray(probs, dtype=np.float32),
        # mask + frame_stats omitted — helpers ignore them.
    }


# ---------------------------------------------------------------------------
# _outputs_to_bbox_score_list — used by ground_on_frame
# ---------------------------------------------------------------------------


def test_list_single_detection_yields_single_bbox():
    out = _make_outputs([0], [[0.1, 0.2, 0.3, 0.4]], [0.9])
    result = _outputs_to_bbox_score_list(out)
    assert len(result) == 1
    bbox, score = result[0]
    assert (bbox.x, bbox.y, bbox.w, bbox.h) == pytest.approx(
        (0.1, 0.2, 0.3, 0.4), abs=1e-6
    )
    assert score == pytest.approx(0.9)


def test_list_zero_detections_returns_empty_list():
    out = _make_outputs([], [], [])
    assert _outputs_to_bbox_score_list(out) == []


def test_list_results_sorted_descending_by_score():
    out = _make_outputs(
        obj_ids=[0, 1, 2],
        boxes=[
            [0.0, 0.0, 0.1, 0.1],  # score 0.5
            [0.2, 0.2, 0.1, 0.1],  # score 0.9
            [0.4, 0.4, 0.1, 0.1],  # score 0.1
        ],
        probs=[0.5, 0.9, 0.1],
    )
    result = _outputs_to_bbox_score_list(out)
    assert [s for _, s in result] == [
        pytest.approx(0.9), pytest.approx(0.5), pytest.approx(0.1),
    ]


def test_list_skips_out_of_unit_square_bbox():
    """x + w > 1.0 violates BBox invariants — entry is skipped silently."""
    out = _make_outputs(
        obj_ids=[0, 1],
        boxes=[
            [0.95, 0.20, 0.10, 0.10],  # x+w=1.05 → invalid
            [0.50, 0.50, 0.20, 0.20],  # valid
        ],
        probs=[0.9, 0.4],
    )
    result = _outputs_to_bbox_score_list(out)
    assert len(result) == 1
    assert result[0][1] == pytest.approx(0.4)  # only the valid one survives


def test_list_skips_zero_size_bbox():
    """w=0 or h=0 fails BBox invariants — skipped, no exception."""
    out = _make_outputs(
        obj_ids=[0, 1],
        boxes=[
            [0.5, 0.5, 0.0, 0.1],  # w=0 → invalid
            [0.5, 0.5, 0.1, 0.0],  # h=0 → invalid
        ],
        probs=[0.7, 0.6],
    )
    assert _outputs_to_bbox_score_list(out) == []


def test_list_accepts_python_list_input():
    """Defensive: helpers coerce Python lists via np.asarray (no type guard)."""
    out = {
        "out_obj_ids": [0, 1],
        "out_boxes_xywh": [[0.0, 0.0, 0.1, 0.1], [0.5, 0.5, 0.2, 0.2]],
        "out_probs": [0.6, 0.7],
    }
    result = _outputs_to_bbox_score_list(out)
    assert len(result) == 2
    assert result[0][1] == pytest.approx(0.7)  # sorted desc


# ---------------------------------------------------------------------------
# _outputs_to_bbox_score — used by propagate
# ---------------------------------------------------------------------------


def test_score_returns_bbox_for_target_obj_id_zero():
    out = _make_outputs([0], [[0.1, 0.1, 0.2, 0.2]], [0.85])
    result = _outputs_to_bbox_score(out, target_obj_id=0)
    assert result is not None
    bbox, score = result
    assert (bbox.x, bbox.y) == pytest.approx((0.1, 0.1))
    assert score == pytest.approx(0.85)


def test_score_returns_none_when_target_obj_lost():
    """Track lost: sam3 drops the obj_id from out_obj_ids (verified 2026-05-04)."""
    out = _make_outputs([1, 2], [[0, 0, 0.1, 0.1], [0.5, 0.5, 0.1, 0.1]], [0.5, 0.6])
    assert _outputs_to_bbox_score(out, target_obj_id=0) is None


def test_score_returns_none_for_empty_outputs():
    """Frame fully untracked → empty obj_ids → None."""
    out = _make_outputs([], [], [])
    assert _outputs_to_bbox_score(out, target_obj_id=0) is None


def test_score_picks_only_target_when_multiple_objs_present():
    out = _make_outputs(
        obj_ids=[0, 1],
        boxes=[[0.1, 0.1, 0.2, 0.2], [0.5, 0.5, 0.2, 0.2]],
        probs=[0.9, 0.3],
    )
    target0 = _outputs_to_bbox_score(out, target_obj_id=0)
    target1 = _outputs_to_bbox_score(out, target_obj_id=1)
    assert target0 is not None and target0[1] == pytest.approx(0.9)
    assert target1 is not None and target1[1] == pytest.approx(0.3)


def test_score_returns_none_for_invalid_bbox():
    """Edge-of-frame x+w>1 → BBox raises → returned as None (counts as lost)."""
    out = _make_outputs([0], [[0.95, 0.5, 0.10, 0.10]], [0.9])
    assert _outputs_to_bbox_score(out, target_obj_id=0) is None


def test_score_handles_int64_obj_id_against_python_int_target():
    """obj_ids dtype is int64 from sam3; comparison with Python int must work."""
    out = _make_outputs([np.int64(0)], [[0.1, 0.1, 0.1, 0.1]], [0.5])
    result = _outputs_to_bbox_score(out, target_obj_id=0)
    assert result is not None


# ---------------------------------------------------------------------------
# _coerce_outputs_arrays — input validation
# ---------------------------------------------------------------------------


def test_coerce_missing_obj_ids_raises_keyerror():
    out = {"out_boxes_xywh": np.zeros((0, 4)), "out_probs": np.zeros((0,))}
    with pytest.raises(KeyError, match="out_obj_ids"):
        _coerce_outputs_arrays(out)


def test_coerce_missing_probs_raises_keyerror():
    out = {
        "out_obj_ids": np.array([0]),
        "out_boxes_xywh": np.array([[0, 0, 0.1, 0.1]]),
    }
    with pytest.raises(KeyError, match="out_probs"):
        _coerce_outputs_arrays(out)


def test_coerce_misshapen_boxes_raises_valueerror():
    """boxes_xywh shape=(N, 3) is malformed (sam3 always emits 4-col)."""
    out = {
        "out_obj_ids": np.array([0]),
        "out_boxes_xywh": np.array([[0.0, 0.0, 0.1]]),
        "out_probs": np.array([0.5]),
    }
    with pytest.raises(ValueError, match="shape"):
        _coerce_outputs_arrays(out)


def test_coerce_length_mismatch_raises_valueerror():
    out = {
        "out_obj_ids": np.array([0, 1]),
        "out_boxes_xywh": np.array([[0, 0, 0.1, 0.1]]),
        "out_probs": np.array([0.5, 0.6]),
    }
    with pytest.raises(ValueError, match="length mismatch"):
        _coerce_outputs_arrays(out)
