"""SAM3 mask → keyframe alpha-blend compositor + color legend builder.

Spec: 2026-05-04-vlm-mask-overlay-design.md §5-§6.

Pure functions only — no SAM3 / Gemma dependency. Inputs are uint8 RGB
frames + a :class:`MaskCache`; outputs are uint8 RGB frames + a legend
string for the prompt.
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from mimicanno.object_tracker.mask_cache import (
    BUILTIN_10,
    BUILTIN_10_NAMES,
    MaskCache,
)


def compose_overlay(
    frame: np.ndarray,
    mask_cache: MaskCache,
    frame_index: int,
    alpha: float,
) -> np.ndarray:
    """Alpha-blend every prompt's mask onto ``frame``.

    Iteration order is lexicographic by prompt name; later prompts paint
    on top of earlier ones (spec §5.2 — "後勝ち"). Track-lost prompts
    (mask is None) are skipped.

    Returns a fresh uint8 RGB array; ``frame`` is not mutated.
    """
    if frame.dtype != np.uint8:
        raise ValueError(f"expected uint8 frame, got {frame.dtype}")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected H×W×3 RGB, got shape {frame.shape}")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0,1], got {alpha}")

    out = frame.astype(np.float32)
    h, w = frame.shape[:2]
    for prompt in mask_cache.prompts_at(frame_index):
        mask = mask_cache.get(frame_index, prompt)
        if mask is None:
            continue
        if mask.shape != (h, w):
            raise ValueError(
                f"mask shape {mask.shape} != frame shape {(h, w)} for "
                f"prompt {prompt!r}"
            )
        color = np.asarray(mask_cache.palette[prompt], dtype=np.float32)
        m = mask.astype(np.float32)[..., None]  # H×W×1
        out = out * (1.0 - alpha * m) + color[None, None, :] * alpha * m
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def _color_name_for(rgb: tuple[int, int, int]) -> str:
    """Return the english color name for a BUILTIN_10 RGB triple.

    Falls back to "color" if not in the palette (defensive — currently
    palette is always builtin_10).
    """
    for color, name in zip(BUILTIN_10, BUILTIN_10_NAMES, strict=True):
        if color == rgb:
            return name
    return "color"


def build_color_legend(
    mask_cache: MaskCache,
    segment_frame_indices: Iterable[int],
) -> str | None:
    """Build the prompt legend for one segment.

    Spec §5.4-§5.5: include any prompt that has at least one non-None mask
    in any of the given frames. If every prompt is lost across the entire
    segment, return ``None`` so the caller can suppress the legend.

    Output format (spec §6.1):
        ``"Colored translucent overlays (~40% opacity) mark tracked
        objects: red=gripper, blue=red_block. An overlay may be absent in
        some frames if the object is temporarily occluded or out of view."``
    """
    visible: set[str] = set()
    for fi in segment_frame_indices:
        visible.update(mask_cache.prompts_at(fi))
    if not visible:
        return None
    parts = []
    for prompt in sorted(visible):
        rgb = mask_cache.palette.get(prompt)
        if rgb is None:
            continue
        parts.append(f"{_color_name_for(rgb)}={prompt}")
    if not parts:
        return None
    legend = ", ".join(parts)
    return (
        "Colored translucent overlays (~40% opacity) mark tracked objects: "
        f"{legend}. An overlay may be absent in some frames if the object "
        "is temporarily occluded or out of view."
    )
