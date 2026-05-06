"""Tests for mimicanno.vlm_overlay (spec 2026-05-04 §5-§6)."""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.object_tracker.mask_cache import (
    BUILTIN_10,
    MaskCache,
    assign_palette,
    encode_mask,
)
from mimicanno.vlm_overlay import build_color_legend, compose_overlay


def _frame(h: int = 8, w: int = 8, fill: int = 100) -> np.ndarray:
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _full_mask(h: int = 8, w: int = 8) -> bytes:
    return encode_mask(np.ones((h, w), dtype=bool))


def _empty_mask(h: int = 8, w: int = 8) -> bytes:
    return encode_mask(np.zeros((h, w), dtype=bool))


def test_compose_overlay_no_prompts_returns_copy() -> None:
    frame = _frame()
    cache = MaskCache(by_frame={}, shape=(8, 8), palette={})
    out = compose_overlay(frame, cache, 0, alpha=0.4)
    np.testing.assert_array_equal(out, frame)
    assert out is not frame  # fresh copy


def test_compose_overlay_all_zero_mask_is_identity() -> None:
    frame = _frame()
    cache = MaskCache(
        by_frame={0: {"a": _empty_mask()}},
        shape=(8, 8),
        palette=assign_palette(["a"]),
    )
    out = compose_overlay(frame, cache, 0, alpha=0.4)
    np.testing.assert_array_equal(out, frame)


def test_compose_overlay_alpha_zero_is_identity() -> None:
    frame = _frame()
    cache = MaskCache(
        by_frame={0: {"a": _full_mask()}},
        shape=(8, 8),
        palette=assign_palette(["a"]),
    )
    out = compose_overlay(frame, cache, 0, alpha=0.0)
    np.testing.assert_array_equal(out, frame)


def test_compose_overlay_alpha_one_full_mask_replaces_with_color() -> None:
    frame = _frame()
    cache = MaskCache(
        by_frame={0: {"a": _full_mask()}},
        shape=(8, 8),
        palette={"a": (10, 20, 30)},
    )
    out = compose_overlay(frame, cache, 0, alpha=1.0)
    expected = np.empty_like(frame)
    expected[..., 0] = 10
    expected[..., 1] = 20
    expected[..., 2] = 30
    np.testing.assert_array_equal(out, expected)


def test_compose_overlay_blend_value_is_correct() -> None:
    """frame*(1-α) + color*α at full mask, exact pixel match."""
    frame = _frame(fill=100)
    cache = MaskCache(
        by_frame={0: {"a": _full_mask()}},
        shape=(8, 8),
        palette={"a": (200, 0, 0)},
    )
    out = compose_overlay(frame, cache, 0, alpha=0.5)
    # 100*0.5 + 200*0.5 = 150 (R), 100*0.5 + 0*0.5 = 50 (G/B)
    assert out[0, 0, 0] == 150
    assert out[0, 0, 1] == 50
    assert out[0, 0, 2] == 50


def test_compose_overlay_later_prompt_wins_at_overlap() -> None:
    """Lexicographic order — "z" paints over "a" at overlapping pixels."""
    frame = _frame(fill=0)
    full = _full_mask()
    cache = MaskCache(
        by_frame={0: {"a": full, "z": full}},
        shape=(8, 8),
        palette={"a": (255, 0, 0), "z": (0, 0, 255)},
    )
    out = compose_overlay(frame, cache, 0, alpha=1.0)
    # alpha=1 + last-wins → all pixels become "z" color (blue).
    np.testing.assert_array_equal(out[..., 0], 0)
    np.testing.assert_array_equal(out[..., 2], 255)


def test_compose_overlay_track_lost_prompt_skipped() -> None:
    frame = _frame()
    cache = MaskCache(
        by_frame={0: {"a": None, "b": _full_mask()}},
        shape=(8, 8),
        palette={"a": (255, 0, 0), "b": (0, 255, 0)},
    )
    out = compose_overlay(frame, cache, 0, alpha=1.0)
    # Only "b" green should show.
    assert out[0, 0, 1] == 255
    assert out[0, 0, 0] == 0


def test_compose_overlay_rejects_non_uint8() -> None:
    cache = MaskCache(by_frame={}, shape=(8, 8), palette={})
    with pytest.raises(ValueError, match="uint8"):
        compose_overlay(np.zeros((8, 8, 3), dtype=np.float32), cache, 0, 0.4)


def test_compose_overlay_rejects_alpha_out_of_range() -> None:
    cache = MaskCache(by_frame={}, shape=(8, 8), palette={})
    with pytest.raises(ValueError, match="alpha"):
        compose_overlay(_frame(), cache, 0, alpha=1.5)


def test_compose_overlay_rejects_shape_mismatch() -> None:
    frame = _frame(h=8, w=8)
    cache = MaskCache(
        by_frame={0: {"a": encode_mask(np.ones((4, 4), dtype=bool))}},
        shape=(4, 4),
        palette=assign_palette(["a"]),
    )
    with pytest.raises(ValueError, match="mask shape"):
        compose_overlay(frame, cache, 0, alpha=0.4)


# ---- legend builder ----

def test_build_legend_single_prompt() -> None:
    cache = MaskCache(
        by_frame={0: {"gripper": _full_mask()}},
        shape=(8, 8),
        palette={"gripper": BUILTIN_10[0]},  # blue
    )
    legend = build_color_legend(cache, [0])
    assert legend is not None
    assert "blue=gripper" in legend
    assert "may be absent" in legend


def test_build_legend_multiple_prompts_sorted() -> None:
    full = _full_mask()
    cache = MaskCache(
        by_frame={0: {"tape": full, "bottle": full}},
        shape=(8, 8),
        palette={
            "bottle": BUILTIN_10[0],  # blue (sorted first)
            "tape": BUILTIN_10[1],    # orange
        },
    )
    legend = build_color_legend(cache, [0])
    assert legend is not None
    # Sorted: bottle then tape
    assert legend.index("bottle") < legend.index("tape")
    assert "blue=bottle" in legend
    assert "orange=tape" in legend


def test_build_legend_returns_none_when_all_lost() -> None:
    cache = MaskCache(
        by_frame={0: {"a": None, "b": None}},
        shape=(8, 8),
        palette=assign_palette(["a", "b"]),
    )
    assert build_color_legend(cache, [0]) is None


def test_build_legend_includes_prompt_visible_in_any_frame() -> None:
    """Spec §5.4: a prompt visible in ≥1 segment frame stays in the legend
    even if absent in other frames."""
    full = _full_mask()
    cache = MaskCache(
        by_frame={
            0: {"a": full, "b": None},
            1: {"a": None, "b": full},
        },
        shape=(8, 8),
        palette=assign_palette(["a", "b"]),
    )
    legend = build_color_legend(cache, [0, 1])
    assert legend is not None
    assert "=a" in legend
    assert "=b" in legend


def test_build_legend_empty_frame_indices_returns_none() -> None:
    cache = MaskCache(by_frame={}, shape=(8, 8), palette={})
    assert build_color_legend(cache, []) is None
