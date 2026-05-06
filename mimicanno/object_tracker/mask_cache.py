"""In-memory mask cache for SAM3 outputs (spec 2026-05-04 §4.2-§4.4).

Stores RLE-encoded binary masks indexed by ``(frame_index, prompt)`` so the
clip-feature extractor can re-attach the right mask to each keyframe.

The pycocotools COCO RLE format is wrapped behind a thin ``bytes`` API; no
caller outside this module touches the column-major dict shape.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pycocotools import mask as coco_mask  # type: ignore[import-untyped]

# RGB uint8 — matplotlib tab10 snapshot. We deliberately do NOT depend on
# matplotlib at runtime; the values are frozen in this module so palette
# behavior is independent of any upstream matplotlib version drift.
BUILTIN_10: list[tuple[int, int, int]] = [
    (31, 119, 180),    # blue
    (255, 127, 14),    # orange
    (44, 160, 44),     # green
    (214, 39, 40),     # red
    (148, 103, 189),   # purple
    (140, 86, 75),     # brown
    (227, 119, 194),   # pink
    (127, 127, 127),   # gray
    (188, 189, 34),    # olive
    (23, 190, 207),    # cyan
]

# Index → English color name. Used by vlm_overlay.build_color_legend so the
# legend reads naturally to Gemma ("red=gripper" not "(214,39,40)=gripper").
BUILTIN_10_NAMES: list[str] = [
    "blue", "orange", "green", "red", "purple",
    "brown", "pink", "gray", "olive", "cyan",
]

PaletteName = Literal["builtin_10"]


def encode_mask(arr: np.ndarray) -> bytes:
    """Encode a 2-D bool mask to opaque bytes.

    Wraps pycocotools so callers never see the column-major COCO dict.
    Format: 4-byte big-endian H, 4-byte big-endian W, then raw RLE counts.
    """
    if arr.ndim != 2:
        raise ValueError(f"expected 2-D array, got shape {arr.shape}")
    if arr.dtype != np.bool_:
        raise ValueError(f"expected bool dtype, got {arr.dtype}")
    fortran = np.asfortranarray(arr.astype(np.uint8))
    rle = coco_mask.encode(fortran)
    h, w = rle["size"]
    counts: bytes = rle["counts"]
    return struct.pack(">II", int(h), int(w)) + counts


def decode_mask(blob: bytes) -> np.ndarray:
    """Inverse of :func:`encode_mask`. Returns 2-D bool ndarray."""
    if len(blob) < 8:
        raise ValueError(f"blob too short: {len(blob)} bytes")
    h, w = struct.unpack(">II", blob[:8])
    counts = blob[8:]
    decoded = coco_mask.decode({"size": [h, w], "counts": counts})
    return decoded.astype(bool)


def assign_palette(
    prompts: list[str],
    palette_name: PaletteName = "builtin_10",
) -> dict[str, tuple[int, int, int]]:
    """Map prompts → RGB deterministically.

    Prompts are assigned colors by their lexicographic-sorted index. Beyond
    10 prompts we cycle (``idx % 10``) — spec §12.3 flags this as a future
    improvement (tab20 etc.) but SO101 stays well under 10.
    """
    if palette_name != "builtin_10":
        raise ValueError(f"unknown palette: {palette_name!r}")
    out: dict[str, tuple[int, int, int]] = {}
    for idx, prompt in enumerate(sorted(set(prompts))):
        out[prompt] = BUILTIN_10[idx % len(BUILTIN_10)]
    return out


@dataclass(frozen=True)
class MaskCache:
    """Frame-indexed RLE mask store (spec §4.2).

    `frozen=True` blocks reassignment but does NOT freeze nested dicts —
    callers must treat the inner dicts as immutable after construction.

    Attributes
    ----------
    by_frame:
        ``{frame_index: {prompt: rle_bytes | None}}``. ``None`` marks
        track-lost at that frame (distinct from "not yet seen" — that case
        is just absent from the dict).
    shape:
        ``(h, w)`` of the stored masks (already downsampled to keyframe
        size). Decode results match this shape.
    palette:
        Per-prompt RGB. Built once at MaskCache construction; consumers
        (overlay compositor, prompt legend) all read from this.
    """
    by_frame: dict[int, dict[str, bytes | None]]
    shape: tuple[int, int]
    palette: dict[str, tuple[int, int, int]]

    def get(self, frame_index: int, prompt: str) -> np.ndarray | None:
        per_frame = self.by_frame.get(frame_index)
        if per_frame is None:
            return None
        blob = per_frame.get(prompt)
        if blob is None:
            return None
        return decode_mask(blob)

    def prompts_at(self, frame_index: int) -> list[str]:
        """Prompts with a non-None mask at this frame, sorted lexicographically."""
        per_frame = self.by_frame.get(frame_index)
        if per_frame is None:
            return []
        return sorted(p for p, blob in per_frame.items() if blob is not None)

    def all_prompts(self) -> list[str]:
        """All prompts ever seen across frames, sorted lexicographically."""
        seen: set[str] = set()
        for per_frame in self.by_frame.values():
            seen.update(per_frame.keys())
        return sorted(seen)


def empty_cache(
    shape: tuple[int, int],
    prompts: list[str],
    palette_name: PaletteName = "builtin_10",
) -> MaskCache:
    """Construct an empty MaskCache with palette pre-assigned."""
    return MaskCache(
        by_frame={},
        shape=shape,
        palette=assign_palette(prompts, palette_name),
    )
