"""--vlm-device CLI flag plumbs through to VLMConfig."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from mimicanno.config import VLMConfig
from mimicanno.preflight import PreflightResult

pytestmark = pytest.mark.integration

runner = CliRunner()


def _build_minimal_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Synthesize a tiny valid parquet + 1×1 mp4 video for argument parsing."""
    import imageio_ffmpeg as iio
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq_path = tmp_path / "ep.parquet"
    pq.write_table(
        pa.table({
            "timestamp": pa.array([0.0, 1 / 30, 2 / 30]),
            "observation.state": pa.array([[0.0] * 6] * 3),
        }),
        pq_path,
    )

    video_path = tmp_path / "ep.mp4"
    writer = iio.write_frames(
        str(video_path), size=(1, 1), fps=30, codec="libx264",
        pix_fmt_out="yuv420p", quality=8,
    )
    writer.send(None)
    for _ in range(3):
        writer.send(np.zeros((1, 1, 3), dtype=np.uint8))
    writer.close()

    return video_path, pq_path


def _run_with_captured_config(
    tmp_path: Path, extra_args: list[str]
) -> tuple[list[VLMConfig], object]:
    """Run the CLI with VLM preflight + pipeline both stubbed; capture the
    VLMConfig that the CLI built."""
    video, parquet = _build_minimal_inputs(tmp_path)
    captured: list[VLMConfig] = []

    def fake_pipeline(req, *args, **kwargs):  # noqa: ARG001
        if req.config.vlm is not None:
            captured.append(req.config.vlm)
        from mimicanno.errors import ErrorCode, MimicAnnoError
        raise MimicAnnoError(ErrorCode.EXPORT_PROFILE_NOT_FOUND, "abort", {})

    fake_resolution = PreflightResult(
        model_id="fake/model",
        resolved_checkpoint="0" * 40,
        fixture_path=None,
    )

    with (
        patch("mimicanno.preflight.resolve_vlm_model", return_value=fake_resolution),
        patch("mimicanno.pipeline.annotate_episode", fake_pipeline),
    ):
        result = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(video),
                "--parquet", str(parquet),
                "--task", "x",
                "--robot", "so100",
                "--target-phase", "2",
                "--vlm-model", "fake/model@" + ("0" * 12),
                "--runs-root", str(tmp_path / "runs"),
                *extra_args,
            ],
        )
    return captured, result


def test_vlm_device_flag_propagates_to_vlm_config(tmp_path: Path) -> None:
    captured, result = _run_with_captured_config(tmp_path, ["--vlm-device", "cpu"])
    assert captured, f"pipeline never reached; output={result.output}"
    assert captured[0].device == "cpu"


def test_vlm_device_default_unchanged(tmp_path: Path) -> None:
    """No --vlm-device → VLMConfig.device == 'cuda' (existing default)."""
    captured, result = _run_with_captured_config(tmp_path, [])
    assert captured, f"pipeline never reached; output={result.output}"
    assert captured[0].device == "cuda"


def test_vlm_timeout_sec_flag_propagates(tmp_path: Path) -> None:
    captured, result = _run_with_captured_config(
        tmp_path, ["--vlm-timeout-sec", "600"]
    )
    assert captured, f"pipeline never reached; output={result.output}"
    assert captured[0].timeout_sec == 600.0


def test_vlm_timeout_sec_default_unchanged(tmp_path: Path) -> None:
    """No --vlm-timeout-sec → VLMConfig.timeout_sec == 30.0 (existing)."""
    captured, result = _run_with_captured_config(tmp_path, [])
    assert captured, f"pipeline never reached; output={result.output}"
    assert captured[0].timeout_sec == 30.0
