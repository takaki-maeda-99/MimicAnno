"""Tests for mimicanno.object_tracker.mask_cache (spec 2026-05-04 §4)."""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.object_tracker.mask_cache import (
    BUILTIN_10,
    MaskCache,
    assign_palette,
    decode_mask,
    empty_cache,
    encode_mask,
)


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


@pytest.mark.parametrize("seed", range(20))
def test_rle_round_trip_random_bool(seed: int) -> None:
    rng = _rng(seed)
    h = int(rng.integers(1, 64))
    w = int(rng.integers(1, 64))
    arr = rng.random((h, w)) > 0.5
    blob = encode_mask(arr)
    out = decode_mask(blob)
    assert out.shape == arr.shape
    assert out.dtype == np.bool_
    np.testing.assert_array_equal(out, arr)


def test_rle_round_trip_all_zero() -> None:
    arr = np.zeros((10, 12), dtype=bool)
    np.testing.assert_array_equal(decode_mask(encode_mask(arr)), arr)


def test_rle_round_trip_all_one() -> None:
    arr = np.ones((10, 12), dtype=bool)
    np.testing.assert_array_equal(decode_mask(encode_mask(arr)), arr)


def test_encode_rejects_non_bool() -> None:
    with pytest.raises(ValueError, match="bool dtype"):
        encode_mask(np.zeros((4, 4), dtype=np.uint8))


def test_encode_rejects_non_2d() -> None:
    with pytest.raises(ValueError, match="2-D"):
        encode_mask(np.zeros((4, 4, 1), dtype=bool))


def test_assign_palette_deterministic_and_sorted() -> None:
    p1 = assign_palette(["b", "a", "c"])
    p2 = assign_palette(["c", "a", "b"])
    assert p1 == p2
    # First palette slot goes to "a" (lexicographically first), etc.
    assert p1["a"] == BUILTIN_10[0]
    assert p1["b"] == BUILTIN_10[1]
    assert p1["c"] == BUILTIN_10[2]


def test_assign_palette_dedupes() -> None:
    p = assign_palette(["a", "a", "b"])
    assert set(p.keys()) == {"a", "b"}


def test_assign_palette_cycles_past_ten() -> None:
    prompts = [f"p{i:02d}" for i in range(12)]
    p = assign_palette(prompts)
    # idx 10 (p10 by sort order) wraps back to BUILTIN_10[0]
    assert p["p10"] == BUILTIN_10[0]
    assert p["p11"] == BUILTIN_10[1]


def test_assign_palette_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown palette"):
        assign_palette(["a"], palette_name="tab20")  # type: ignore[arg-type]


def test_mask_cache_get_returns_none_for_unknown_frame() -> None:
    cache = empty_cache(shape=(8, 8), prompts=["a"])
    assert cache.get(0, "a") is None


def test_mask_cache_get_returns_decoded_mask() -> None:
    arr = np.zeros((8, 8), dtype=bool)
    arr[2:5, 3:6] = True
    cache = MaskCache(
        by_frame={0: {"a": encode_mask(arr)}},
        shape=(8, 8),
        palette=assign_palette(["a"]),
    )
    out = cache.get(0, "a")
    assert out is not None
    np.testing.assert_array_equal(out, arr)


def test_mask_cache_get_returns_none_for_track_lost() -> None:
    cache = MaskCache(
        by_frame={0: {"a": None}},
        shape=(4, 4),
        palette=assign_palette(["a"]),
    )
    assert cache.get(0, "a") is None


def test_mask_cache_prompts_at_excludes_none_and_is_sorted() -> None:
    arr = encode_mask(np.ones((4, 4), dtype=bool))
    cache = MaskCache(
        by_frame={
            0: {"c": arr, "a": None, "b": arr},
        },
        shape=(4, 4),
        palette=assign_palette(["a", "b", "c"]),
    )
    assert cache.prompts_at(0) == ["b", "c"]
    assert cache.prompts_at(99) == []


def test_mask_cache_all_prompts_is_sorted_union() -> None:
    arr = encode_mask(np.ones((2, 2), dtype=bool))
    cache = MaskCache(
        by_frame={
            0: {"b": arr},
            5: {"a": None, "c": arr},
        },
        shape=(2, 2),
        palette=assign_palette(["a", "b", "c"]),
    )
    assert cache.all_prompts() == ["a", "b", "c"]
