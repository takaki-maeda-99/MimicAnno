"""Layer 3 manual smoke (spec §10.3 / §11 #10).

Real Gemma + real SAM3 against a real LeRobot episode (lerobot/svla_so100_pickplace
ep0 by default — same dataset used in `docs/phase1-real-data-verification.md`).

NOT part of the CI gate — set both env vars to enable.

```bash
export MIMICANNO_RUN_SAM3_SMOKE=1
export MIMICANNO_SAM3_CHECKPOINT=/path/to/sam3.ckpt
# optional: override the episode used (defaults to lerobot/svla_so100_pickplace ep0)
export MIMICANNO_REAL_VIDEO=/path/to/episode_000.mp4
export MIMICANNO_REAL_PARQUET=/path/to/episode_000.parquet
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/test_phase3_real_sam3_smoke.py -v -s
```

Spec §9.3 mask-overlay smokes (mask shape / overlap / centroid) live in
the same file and share a module-scoped fixture. Override prompts per
dataset via ``MIMICANNO_OVERLAY_SMOKE_PROMPTS=tape,robot arm`` (the
default works on SO101; verify with the recorded run command in
``docs/superpowers/notes/2026-05-06-vlm-mask-overlay-smoke-run.md``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_SAM3_SMOKE") != "1"
    or not os.environ.get("MIMICANNO_SAM3_CHECKPOINT"),
    reason=(
        "Set MIMICANNO_RUN_SAM3_SMOKE=1 and MIMICANNO_SAM3_CHECKPOINT to run; "
        "this is a Layer 3 manual smoke that requires a GPU + sam3 weights."
    ),
)

runner = CliRunner()


def _resolve_real_episode() -> tuple[Path, Path]:
    """Pick the real episode to run against. Defaults to a known-good
    extraction location; override via MIMICANNO_REAL_{VIDEO,PARQUET}."""
    video_env = os.environ.get("MIMICANNO_REAL_VIDEO")
    parquet_env = os.environ.get("MIMICANNO_REAL_PARQUET")
    if video_env and parquet_env:
        return Path(video_env), Path(parquet_env)
    pytest.skip(
        "Set MIMICANNO_REAL_VIDEO and MIMICANNO_REAL_PARQUET to point at an "
        "extracted lerobot episode (use tools/extract_lerobot_episode.py)."
    )


def test_phase3_real_sam3_on_lerobot_ep0(tmp_path: Path) -> None:
    """Spec §11 #10: end-to-end Phase 3 against a real episode produces a
    tracks.json with at least one substantive track and
    pipeline_status.object_state_available=True."""
    video, parquet = _resolve_real_episode()
    sam3_ckpt = Path(os.environ["MIMICANNO_SAM3_CHECKPOINT"])
    vlm_model = os.environ.get("MIMICANNO_VLM_MODEL", "google/gemma-4-E2B-it")

    runs_root = tmp_path / "runs"
    result = runner.invoke(app, [
        "annotate",
        "--video", str(video),
        "--parquet", str(parquet),
        "--task", "Pick up the cube and place it in the box.",
        "--robot", "so100",
        "--target-phase", "3",
        "--vlm-model", vlm_model,
        "--sam3-checkpoint", str(sam3_ckpt),
        "--runs-root", str(runs_root),
    ], catch_exceptions=False)
    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [d for d in runs_root.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    tracks = json.loads((run_dir / "tracks.json").read_text())

    assert manifest["pipeline_status"]["object_state_available"] is True
    coverage = manifest["pipeline_status"]["object_state_segment_coverage"]
    assert coverage is not None and coverage >= 0.5, (
        f"object_state_segment_coverage={coverage} below 0.5 threshold"
    )

    long_object_tracks = [
        t for t in tracks["tracks"]
        if t["role"] == "object" and len(t["samples"]) >= 10
    ]
    assert long_object_tracks, (
        "expected ≥1 object track with ≥10 samples in tracks.json"
    )


# ---------------------------------------------------------------------------
# Spec §9.3: real SAM3 + MaskCache smokes — mask shape / overlap / centroid
# ---------------------------------------------------------------------------

_OVERLAY_PROMPTS = [
    p.strip()
    for p in os.environ.get(
        # SO101-tuned default: "bottle" / "robot gripper" don't ground
        # reliably on frame 0 of SO101 ep0 (verified 2026-05-04 in
        # docs/superpowers/notes/2026-05-04-sam3-smoke-results.md), but
        # "tape" + "robot arm" do. Override per dataset via the env var.
        "MIMICANNO_OVERLAY_SMOKE_PROMPTS", "tape,robot arm",
    ).split(",")
    if p.strip()
]
_OVERLAY_IMAGE_SIZE = int(
    os.environ.get("MIMICANNO_OVERLAY_SMOKE_IMAGE_SIZE", "256")
)
_OVERLAY_STRIDE = int(os.environ.get("MIMICANNO_OVERLAY_SMOKE_STRIDE", "5"))


def _load_first_frame(video_path: Path):
    import cv2  # type: ignore
    import numpy as np  # noqa: F401

    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read frame 0 of {video_path}")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


@pytest.fixture(scope="module")
def overlay_smoke_artifacts():
    """Load SAM3 once, ground multiple prompts, and run mask-collecting
    propagation on SO101 ep0 (or whatever MIMICANNO_REAL_VIDEO points at).

    Returns:
        (mask_cache, grounded_prompts, n_frames, image_size_px)
    """
    video, _parquet = _resolve_real_episode()
    sam3_ckpt = Path(os.environ["MIMICANNO_SAM3_CHECKPOINT"])

    from mimicanno.config import TrackingConfig
    from mimicanno.object_tracker.planner import EntityPlan
    from mimicanno.object_tracker.propagator import (
        Propagator,
        ground_initial_detections,
    )
    from mimicanno.object_tracker.sam3_runtime import SAM3Runtime

    runtime = SAM3Runtime.load(
        checkpoint=sam3_ckpt, device="cuda", offload_video_to_cpu=True,
    )
    try:
        first_frame = _load_first_frame(video)
        entities = EntityPlan(
            object_prompts=list(_OVERLAY_PROMPTS),
            target_prompts=[], tool_prompts=[],
        )
        plan = ground_initial_detections(
            runtime=runtime, entities=entities, initial_frame=first_frame,
        )
        if not plan.initial_detections:
            pytest.skip(
                f"none of {_OVERLAY_PROMPTS!r} grounded on frame 0; override "
                "via MIMICANNO_OVERLAY_SMOKE_PROMPTS"
            )
        # Best-effort frame count: read it from cv2 metadata.
        import cv2  # type: ignore
        cap = cv2.VideoCapture(str(video))
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 151
        cap.release()

        config = TrackingConfig(track_stride_frames=_OVERLAY_STRIDE)
        _tracks, mask_cache = Propagator().run(
            runtime=runtime, plan=plan, video_path=video,
            fps=15.0, n_frames=n_frames, stride=_OVERLAY_STRIDE,
            config=config, mask_image_size_px=_OVERLAY_IMAGE_SIZE,
        )
        grounded = sorted(p for (_role, p) in plan.initial_detections)
        return mask_cache, grounded, n_frames, _OVERLAY_IMAGE_SIZE
    finally:
        runtime.close()


def test_mask_shape_matches_image_size_px(overlay_smoke_artifacts) -> None:
    """Spec §9.3 case 1: every cached mask shape == (image_size_px, image_size_px)."""
    mask_cache, grounded, _n_frames, image_size_px = overlay_smoke_artifacts
    assert mask_cache is not None
    assert mask_cache.shape == (image_size_px, image_size_px)

    nonempty = 0
    for fr_idx in mask_cache.by_frame:
        for prompt in grounded:
            decoded = mask_cache.get(fr_idx, prompt)
            if decoded is None:
                continue
            assert decoded.shape == (image_size_px, image_size_px)
            assert decoded.dtype.kind == "b"
            if int(decoded.sum()) > 0:
                nonempty += 1
    assert nonempty > 0, "expected ≥1 non-empty mask across the episode"


def test_pairwise_mask_overlap_under_one_percent(overlay_smoke_artifacts) -> None:
    """Spec §9.3 case 2: per-frame logical AND coverage <1% over total pixels.

    Threshold rationale: SAM3 visible-only segmentation should not paint
    the same pixel for two distinct prompts; only boundary jitter is
    expected. Spec §12.1 will revisit the threshold once §11 logs land.
    """
    import numpy as np

    mask_cache, grounded, _n_frames, image_size_px = overlay_smoke_artifacts
    if len(grounded) < 2:
        pytest.skip(f"need ≥2 grounded prompts, got {grounded!r}")

    total_pixels = image_size_px * image_size_px
    max_overlap_ratio = 0.0
    overlap_frames = 0
    for fr_idx in mask_cache.by_frame:
        decoded = [
            mask_cache.get(fr_idx, p) for p in grounded
        ]
        decoded = [d for d in decoded if d is not None and d.any()]
        if len(decoded) < 2:
            continue
        anded = np.logical_and.reduce(decoded)
        ratio = float(anded.sum()) / total_pixels
        if ratio > 0:
            overlap_frames += 1
            max_overlap_ratio = max(max_overlap_ratio, ratio)
    # Always log so spec §11 has the implementation-truth.
    print(
        f"\n[overlay-smoke] pairwise overlap: max_ratio={max_overlap_ratio:.6f} "
        f"frames_with_overlap={overlap_frames}"
    )
    assert max_overlap_ratio < 0.01, (
        f"max pairwise overlap ratio {max_overlap_ratio:.4%} ≥ 1% — "
        "spec §9.3 threshold breached; investigate per-prompt mask leak"
    )


def test_centroid_distance_distinguishes_prompts(overlay_smoke_artifacts) -> None:
    """Spec §9.3 case 3: at least one frame where two prompts' mask centroids
    are >10px apart. Catches a regression where all prompts collapse to the
    same bbox/mask (e.g. obj_id mix-up at sam3 boundary)."""
    import numpy as np

    mask_cache, grounded, _n_frames, _image_size_px = overlay_smoke_artifacts
    if len(grounded) < 2:
        pytest.skip(f"need ≥2 grounded prompts, got {grounded!r}")

    def _centroid(mask: np.ndarray) -> tuple[float, float] | None:
        ys, xs = np.where(mask)
        if ys.size == 0:
            return None
        return float(ys.mean()), float(xs.mean())

    found_distinct = False
    max_dist = 0.0
    for fr_idx in mask_cache.by_frame:
        centroids: dict[str, tuple[float, float]] = {}
        for p in grounded:
            decoded = mask_cache.get(fr_idx, p)
            if decoded is None:
                continue
            c = _centroid(decoded)
            if c is not None:
                centroids[p] = c
        if len(centroids) < 2:
            continue
        names = sorted(centroids)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                cy_i, cx_i = centroids[names[i]]
                cy_j, cx_j = centroids[names[j]]
                d = ((cy_i - cy_j) ** 2 + (cx_i - cx_j) ** 2) ** 0.5
                max_dist = max(max_dist, d)
                if d > 10.0:
                    found_distinct = True
    print(f"\n[overlay-smoke] max prompt-centroid distance: {max_dist:.2f}px")
    assert found_distinct, (
        f"no frame had two prompt centroids >10px apart "
        f"(max observed {max_dist:.2f}px); prompts may be collapsing "
        "to the same region"
    )
