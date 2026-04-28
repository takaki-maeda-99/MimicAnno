# tests/unit/test_io_video.py
from pathlib import Path

import numpy as np
import pytest

from mimicanno.io_video import (
    VideoProbe,
    copy_video,
    materialize_video,
    probe_video,
)


@pytest.fixture
def tiny_mp4(tmp_path: Path) -> Path:
    """Generate a 30-frame 64x64 video at 30 fps via imageio_ffmpeg."""
    import imageio_ffmpeg

    out = tmp_path / "tiny.mp4"
    writer = imageio_ffmpeg.write_frames(
        str(out),
        size=(64, 64),
        fps=30,
        codec="libx264",
        macro_block_size=1,
        quality=8,
    )
    writer.send(None)  # init
    rng = np.random.default_rng(0)
    for _ in range(30):
        frame = rng.integers(0, 255, size=(64, 64, 3), dtype=np.uint8)
        writer.send(frame.tobytes())
    writer.close()
    return out


class TestProbe:
    def test_returns_duration_and_fps(self, tiny_mp4: Path):
        probe = probe_video(tiny_mp4)
        assert isinstance(probe, VideoProbe)
        assert probe.fps == pytest.approx(30.0, abs=0.5)
        assert probe.duration_sec == pytest.approx(1.0, abs=0.1)
        assert probe.sha256.startswith("sha256:")
        assert probe.width == 64 and probe.height == 64


class TestMaterialize:
    def test_copy_default(self, tiny_mp4: Path, tmp_path: Path):
        run_dir = tmp_path / "run.tmp.123"
        run_dir.mkdir()
        out = materialize_video(tiny_mp4, run_dir, link=False)
        assert out == run_dir / "video.mp4"
        assert out.exists() and not out.is_symlink()
        assert out.stat().st_size == tiny_mp4.stat().st_size

    def test_symlink_when_requested(self, tiny_mp4: Path, tmp_path: Path):
        run_dir = tmp_path / "run.tmp.456"
        run_dir.mkdir()
        out = materialize_video(tiny_mp4, run_dir, link=True)
        assert out == run_dir / "video.mp4"
        assert out.is_symlink()

    def test_copy_helper_returns_destination(self, tiny_mp4: Path, tmp_path: Path):
        dest = copy_video(tiny_mp4, tmp_path / "out.mp4")
        assert dest == tmp_path / "out.mp4"
        assert dest.read_bytes() == tiny_mp4.read_bytes()


def test_extract_frames_at_indices_returns_correct_count(tmp_path: Path) -> None:
    """Smoke: synthesize a 30-frame video, request frames [0, 10, 29]."""
    from mimicanno.io_video import extract_frames_at_indices
    from tests.fixtures.synthesize import synthesize_minimal_mp4
    video = synthesize_minimal_mp4(tmp_path, n_frames=30, width=64, height=48)
    frames = extract_frames_at_indices(video, [0, 10, 29])
    assert len(frames) == 3
    assert all(f.shape == (48, 64, 3) for f in frames)
    assert all(f.dtype == np.uint8 for f in frames)


def test_extract_frames_with_long_edge_resize(tmp_path: Path) -> None:
    from mimicanno.io_video import extract_frames_at_indices
    from tests.fixtures.synthesize import synthesize_minimal_mp4
    video = synthesize_minimal_mp4(tmp_path, n_frames=10, width=128, height=96)
    frames = extract_frames_at_indices(video, [0, 5], long_edge_px=64)
    assert len(frames) == 2
    # Long edge 128 → resized to 64; short edge 96 → 48.
    for f in frames:
        assert max(f.shape[:2]) == 64
