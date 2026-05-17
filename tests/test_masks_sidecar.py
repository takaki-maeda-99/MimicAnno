"""U-A4: tests for mimicanno.masks.sidecar (T-S1 – T-S8)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mimicanno.object_tracker.mask_cache import MaskCache, assign_palette, encode_mask


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_bool_mask(h: int, w: int, fill: bool = True) -> np.ndarray:
    arr = np.zeros((h, w), dtype=bool)
    if fill:
        arr[: h // 2, : w // 2] = True
    return arr


@dataclass
class FakeTrackSample:
    frame: int
    time_sec: float = 0.0
    bbox: Any = None
    score: float = 1.0


@dataclass
class FakeTrack:
    track_id: str
    role: str
    prompt: str
    slug: str
    index: int
    primary: bool = True
    samples: list[FakeTrackSample] = field(default_factory=list)
    gap_events: list[Any] = field(default_factory=list)


def _make_cache(frames: dict[int, dict[str, np.ndarray | None]]) -> MaskCache:
    """Build a real MaskCache from frame→prompt→bool-mask dicts."""
    h, w = 4, 4
    all_prompts = sorted({p for fmasks in frames.values() for p in fmasks})
    palette = assign_palette(all_prompts)
    by_frame: dict[int, dict[str, bytes | None]] = {}
    for frame, per_prompt in frames.items():
        by_frame[frame] = {
            p: encode_mask(mask) if mask is not None else None
            for p, mask in per_prompt.items()
        }
    return MaskCache(by_frame=by_frame, shape=(h, w), palette=palette)


# ---------------------------------------------------------------------------
# T-S1: write_masks_sidecar creates _masks/meta.json + one PNG per frame
# ---------------------------------------------------------------------------


def test_write_creates_masks_dir_and_files(tmp_path: Path) -> None:
    """T-S1: _masks/<frame>.png and meta.json are created."""
    from mimicanno.masks.sidecar import write_masks_sidecar

    mask = _make_bool_mask(4, 4)
    cache = _make_cache({0: {"block": mask}, 2: {"block": mask}})
    tracks = [
        FakeTrack(
            track_id="obj:object:block:0",
            role="object",
            prompt="block",
            slug="block",
            index=0,
            samples=[FakeTrackSample(frame=0), FakeTrackSample(frame=2)],
        )
    ]

    write_masks_sidecar(tmp_path, cache, tracks, canonical="ep0")

    masks_dir = tmp_path / "_masks"
    assert masks_dir.is_dir()
    assert (masks_dir / "000000.png").exists()
    assert (masks_dir / "000002.png").exists()
    assert (masks_dir / "meta.json").exists()


# ---------------------------------------------------------------------------
# T-S2: empty MaskCache writes meta.json with frame_count=0, no PNGs
# ---------------------------------------------------------------------------


def test_write_empty_cache(tmp_path: Path) -> None:
    """T-S2: empty by_frame → frame_count=0, no PNG files."""
    from mimicanno.masks.sidecar import write_masks_sidecar

    cache = MaskCache(by_frame={}, shape=(4, 4), palette={})
    write_masks_sidecar(tmp_path, cache, [], canonical="ep_empty")

    masks_dir = tmp_path / "_masks"
    assert (masks_dir / "meta.json").exists()
    meta = json.loads((masks_dir / "meta.json").read_text())
    assert meta["frame_count"] == 0
    assert meta["tracks"] == []
    pngs = list(masks_dir.glob("*.png"))
    assert pngs == []


# ---------------------------------------------------------------------------
# T-S3: hex color encoding is correct
# ---------------------------------------------------------------------------


def test_hex_color_encoding(tmp_path: Path) -> None:
    """T-S3: palette RGB(31,119,180) → '#1f77b4' in meta.json."""
    from mimicanno.masks.sidecar import write_masks_sidecar

    mask = _make_bool_mask(4, 4)
    cache = _make_cache({0: {"block": mask}})
    # The first prompt in sorted order gets BUILTIN_10[0] = (31, 119, 180)
    expected_hex = "#1f77b4"

    tracks = [
        FakeTrack(
            track_id="obj:object:block:0",
            role="object",
            prompt="block",
            slug="block",
            index=0,
            samples=[FakeTrackSample(frame=0)],
        )
    ]
    write_masks_sidecar(tmp_path, cache, tracks, canonical="ep_color")

    meta = json.loads((tmp_path / "_masks" / "meta.json").read_text())
    assert meta["tracks"][0]["color"] == expected_hex


# ---------------------------------------------------------------------------
# T-S4: PNG is RGBA (4 channels) with correct dimensions
# ---------------------------------------------------------------------------


def test_png_rgba_dimensions(tmp_path: Path) -> None:
    """T-S4: PNG dimensions match mask_cache.shape and have 4 channels."""
    from PIL import Image

    from mimicanno.masks.sidecar import write_masks_sidecar

    h, w = 8, 12
    arr = np.zeros((h, w), dtype=bool)
    arr[1, 1] = True
    cache = MaskCache(
        by_frame={0: {"block": encode_mask(arr)}},
        shape=(h, w),
        palette=assign_palette(["block"]),
    )
    tracks: list[Any] = []
    write_masks_sidecar(tmp_path, cache, tracks, canonical="ep_dim")

    png_path = tmp_path / "_masks" / "000000.png"
    img = Image.open(png_path)
    assert img.size == (w, h)
    assert img.mode == "RGBA"


# ---------------------------------------------------------------------------
# T-S5: read_mask_meta returns empty-meta for legacy run (no _masks/)
# ---------------------------------------------------------------------------


def test_read_mask_meta_legacy(tmp_path: Path) -> None:
    """T-S5: no _masks/ dir → frame_count=0, empty tracks list."""
    from mimicanno.masks.sidecar import read_mask_meta

    result = read_mask_meta(tmp_path, "ep_legacy", "rs1")
    assert result["frame_count"] == 0
    assert result["tracks"] == []
    assert result["run_set"] == "rs1"


# ---------------------------------------------------------------------------
# T-S6: read_mask_meta injects run_set from argument
# ---------------------------------------------------------------------------


def test_read_mask_meta_injects_run_set(tmp_path: Path) -> None:
    """T-S6: run_set in file is '' → replaced by argument at read time."""
    from mimicanno.masks.sidecar import read_mask_meta, write_masks_sidecar

    mask = _make_bool_mask(4, 4)
    cache = _make_cache({0: {"obj": mask}})
    tracks = [
        FakeTrack(
            track_id="obj:object:obj:0",
            role="object",
            prompt="obj",
            slug="obj",
            index=0,
            samples=[FakeTrackSample(frame=0)],
        )
    ]
    write_masks_sidecar(tmp_path, cache, tracks, canonical="ep_rs")

    raw = json.loads((tmp_path / "_masks" / "meta.json").read_text())
    assert raw["run_set"] == ""

    result = read_mask_meta(tmp_path, "ep_rs", "my_run_set")
    assert result["run_set"] == "my_run_set"


# ---------------------------------------------------------------------------
# T-S7: png_path_for_frame uses 6-digit zero-padded format
# ---------------------------------------------------------------------------


def test_png_path_format() -> None:
    """T-S7: frame 42 → 000042.png; frame 0 → 000000.png."""
    from mimicanno.masks.sidecar import png_path_for_frame

    p = png_path_for_frame(Path("/tmp/_masks"), 42)
    assert p.name == "000042.png"

    p2 = png_path_for_frame(Path("/tmp/_masks"), 0)
    assert p2.name == "000000.png"


# ---------------------------------------------------------------------------
# T-S8: gap-only track (no samples) gets first_frame = last_frame = -1
# ---------------------------------------------------------------------------


def test_gap_only_track_sentinel(tmp_path: Path) -> None:
    """T-S8: track with no samples → first_frame=-1, last_frame=-1."""
    from mimicanno.masks.sidecar import write_masks_sidecar

    cache = MaskCache(by_frame={}, shape=(4, 4), palette={"obj": (31, 119, 180)})
    gap_track = FakeTrack(
        track_id="obj:object:obj:0",
        role="object",
        prompt="obj",
        slug="obj",
        index=0,
        samples=[],  # no samples
    )
    write_masks_sidecar(tmp_path, cache, [gap_track], canonical="ep_gap")

    meta = json.loads((tmp_path / "_masks" / "meta.json").read_text())
    assert meta["tracks"][0]["first_frame"] == -1
    assert meta["tracks"][0]["last_frame"] == -1
