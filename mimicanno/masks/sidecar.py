"""SAM3 mask sidecar writer/reader (U-A4 spec §3).

Layout on disk::

    runs/<run_set>/<canonical>/_masks/<frame:06d>.png   # RGBA, one per keyframe
    runs/<run_set>/<canonical>/_masks/meta.json         # track metadata

The sidecar is written inside ``_write_artifacts()`` so it ends up in the
``tmp_dir`` that ``publish.py`` atomically renames to the final run directory.

Reading is done at request time by :func:`read_mask_meta`; the ``run_set``
field is injected from the query parameter (stored as ``""`` on disk).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from mimicanno.object_tracker.mask_cache import MaskCache, decode_mask

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _composite_frame_png(
    mask_cache: MaskCache,
    frame: int,
) -> "np.ndarray[Any, np.dtype[np.uint8]]":
    """Return an RGBA uint8 ndarray (H, W, 4) for the given frame.

    Prompts are composited in lexicographic order (deterministic). Each
    mask pixel gets the palette colour for its prompt at alpha=255.
    Pixels covered by multiple prompts: last-write-wins (lex order).
    """
    h, w = mask_cache.shape
    canvas = np.zeros((h, w, 4), dtype=np.uint8)  # RGBA, all transparent
    per_frame = mask_cache.by_frame.get(frame, {})
    for prompt in sorted(per_frame.keys()):
        blob = per_frame[prompt]
        if blob is None:
            continue
        arr = decode_mask(blob)          # bool (H, W)
        r, g, b = mask_cache.palette[prompt]
        canvas[arr, 0] = r
        canvas[arr, 1] = g
        canvas[arr, 2] = b
        canvas[arr, 3] = 255
    return canvas


def _build_track_meta(
    mask_cache: MaskCache,
    tracks: list[Any],  # list[Track] — avoid hard import cycle
) -> list[dict[str, Any]]:
    """Build the tracks list for meta.json from mask_cache + tracks."""
    from mimicanno.object_tracker.track_id import make_track_id

    track_meta: list[dict[str, Any]] = []
    for track in tracks:
        track_id = make_track_id(track.role, track.prompt, track.index)
        color = mask_cache.palette.get(track.prompt)
        hex_color = _rgb_to_hex(color) if color else "#7f7f7f"

        # Determine first_frame / last_frame from samples (not gap_events).
        sample_frames = [s.frame for s in track.samples]
        if sample_frames:
            first_frame = min(sample_frames)
            last_frame = max(sample_frames)
        else:
            # Gap-only or empty track — use sentinel -1.
            first_frame = -1
            last_frame = -1

        track_meta.append(
            {
                "track_id": track_id,
                "prompt": track.prompt,
                "role": track.role,
                "color": hex_color,
                "first_frame": first_frame,
                "last_frame": last_frame,
            }
        )
    return track_meta


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def png_path_for_frame(masks_dir: Path, frame: int) -> Path:
    """Return the expected PNG path for a given frame index."""
    return masks_dir / f"{frame:06d}.png"


def write_masks_sidecar(
    tmp_dir: Path,
    mask_cache: MaskCache,
    tracks: list[Any],
    canonical: str,
) -> None:
    """Persist mask PNGs + meta.json into *tmp_dir* (inside _write_artifacts).

    Creates ``<tmp_dir>/_masks/<frame:06d>.png`` for every frame in
    ``mask_cache.by_frame``, plus ``<tmp_dir>/_masks/meta.json``.

    Parameters
    ----------
    tmp_dir:
        Temporary directory used by publish.py; will be atomically renamed.
    mask_cache:
        MaskCache returned by Propagator.run().
    tracks:
        list[Track] returned alongside mask_cache.
    canonical:
        The canonical run name (episode_id); stored in meta.json for
        informational purposes.
    """
    from PIL import Image

    masks_dir = tmp_dir / "_masks"
    masks_dir.mkdir(parents=True, exist_ok=True)

    # Write per-frame RGBA PNGs.
    for frame in sorted(mask_cache.by_frame.keys()):
        rgba = _composite_frame_png(mask_cache, frame)
        img = Image.fromarray(rgba, mode="RGBA")
        img.save(png_path_for_frame(masks_dir, frame), format="PNG")

    # Build + write meta.json.
    track_meta = _build_track_meta(mask_cache, tracks)
    h, w = mask_cache.shape
    meta: dict[str, Any] = {
        "run_set": "",          # injected at read time from query param
        "canonical": canonical,
        "frame_count": len(mask_cache.by_frame),
        "shape": [h, w],
        "tracks": track_meta,
    }
    (masks_dir / "meta.json").write_text(json.dumps(meta, indent=2))


def read_mask_meta(
    run_dir: Path,
    canonical: str,
    run_set: str,
) -> dict[str, Any]:
    """Read _masks/meta.json and inject run_set from query parameter.

    Returns an empty-meta dict for legacy runs that have no _masks/ sidecar.
    """
    masks_dir = run_dir / "_masks"
    meta_path = masks_dir / "meta.json"
    if not meta_path.exists():
        # Legacy run — return minimal structure with zero frames.
        return {
            "run_set": run_set,
            "canonical": canonical,
            "frame_count": 0,
            "shape": [0, 0],
            "tracks": [],
        }
    meta: dict[str, Any] = json.loads(meta_path.read_text())
    meta["run_set"] = run_set  # overwrite the empty placeholder
    return meta
