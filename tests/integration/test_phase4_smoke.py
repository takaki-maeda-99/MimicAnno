"""Phase 4 happy-path smoke (spec §8.2 #1).

End-to-end Phase 4 invocation through `mimicanno.cli.app` against the
synthetic Aloha episode, with `LocalGemmaVLMLabeler` /
`LocalGemmaTrackingPlanner` / `SAM3Runtime` substituted by the test
doubles in `mimicanno.object_tracker.fixtures`. No GPU.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mimicanno.cli import app
from tests.fixtures.synthesize import synthesize_aloha_episode
from tests.integration._phase3_harness import (
    FIXTURE_VLM_OK_FIRST_TRY,
    BBox,
    EntityPlan,
    FixtureSAM3Tracker,
    build_full_propagation,
    patch_phase3,
)

runner = CliRunner()


@pytest.fixture
def episode(tmp_path: Path):
    return synthesize_aloha_episode(out_dir=tmp_path / "data")


@pytest.fixture
def sam3_ckpt(tmp_path: Path) -> Path:
    p = tmp_path / "sam3.pt"
    p.write_bytes(b"\x00" * 64)
    return p


def _phase4_cli_args(
    *, episode, runs_root: Path, sam3_ckpt: Path,
    extra: list[str] | None = None,
) -> list[str]:
    args = [
        "annotate",
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick the red block and place in white bin",
        "--robot", "aloha",
        "--target-phase", "4",
        "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
        "--offline",
        "--sam3-checkpoint", str(sam3_ckpt),
        "--runs-root", str(runs_root),
        "--score-threshold", "0.10",  # produce >1 segment for smoothing to bite
    ]
    if extra:
        args.extend(extra)
    return args


def _phase4_fixtures():
    """Default Phase 3 fixtures (red block + white bin)."""
    entities = EntityPlan(
        object_prompts=["red block"],
        target_prompts=["white bin"],
        tool_prompts=[],
    )
    bbox = BBox(x=0.4, y=0.4, w=0.1, h=0.1)
    sam3 = FixtureSAM3Tracker(
        initial_detections={
            "red block": [(bbox, 0.95)],
            "white bin": [(bbox, 0.95)],
        },
        propagation_results=build_full_propagation(
            prompts=["red block", "white bin"], bbox=bbox, score=0.9,
        ),
    )
    return entities, sam3


def test_phase4_happy_path_emits_smoothing_summary(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """Spec §8.2 #1: --target-phase 4 produces a run dir with
    pipeline_phase=4, smoothing_summary present, segment count <= Phase 3 raw."""
    runs_root = tmp_path / "runs"
    entities, sam3 = _phase4_fixtures()

    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
            ),
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output + result.stderr

    [run_dir] = [
        d for d in runs_root.iterdir()
        if d.is_dir() and d.name.startswith("ep")
    ]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["generator"]["pipeline_phase"] == 4
    # Spec §4.3: smoothing_summary present on Phase 4 manifests.
    assert "smoothing_summary" in manifest
    summary = manifest["smoothing_summary"]
    assert "initial_segment_count" in summary
    assert "final_segment_count" in summary
    assert summary["final_segment_count"] <= summary["initial_segment_count"]

    annotation = json.loads((run_dir / "annotation.json").read_text())
    # Spec §4.4: annotation schema bumped to 0.2.0 for Phase 4; Phase 6
    # further bumped to 0.4.0 (EditEvent gains old_value/new_value fields).
    assert annotation["schema_version"] == "0.4.0"
    # Every segment carries smoothing_ops (possibly empty).
    for seg in annotation["segments"]:
        assert "smoothing_ops" in seg
        assert isinstance(seg["smoothing_ops"], list)


def test_phase4_no_forbidden_high_conf_pair(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """Spec exit criterion §10 #3: no adjacent pair (s_i, s_{i+1}) is in
    forbidden_transitions AND both have overall_confidence > 0.5."""
    runs_root = tmp_path / "runs"
    entities, sam3 = _phase4_fixtures()
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
            ),
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output + result.stderr
    [run_dir] = [
        d for d in runs_root.iterdir()
        if d.is_dir() and d.name.startswith("ep")
    ]
    annotation = json.loads((run_dir / "annotation.json").read_text())
    import itertools
    forbidden = {("grasp_object", "approach_object"),
                 ("release_object", "grasp_object"),
                 ("lift_object", "idle")}
    segs = annotation["segments"]
    for a, b in itertools.pairwise(segs):
        if (a["phase"], b["phase"]) in forbidden:
            min_oc = min(a["overall_confidence"], b["overall_confidence"])
            assert min_oc <= 0.5, (
                f"forbidden pair {a['phase']!r}->{b['phase']!r} survived "
                f"with min overall_confidence={min_oc}"
            )


def test_phase4_no_viterbi_summary_reflects_skipped(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """`--no-viterbi` produces smoothing_summary with viterbi_skipped=true."""
    runs_root = tmp_path / "runs"
    entities, sam3 = _phase4_fixtures()
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
                extra=["--no-viterbi"],
            ),
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output + result.stderr
    [run_dir] = [
        d for d in runs_root.iterdir()
        if d.is_dir() and d.name.startswith("ep")
    ]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = manifest["smoothing_summary"]
    assert summary["viterbi_skipped"] is True
    assert summary["viterbi_relabels"] == 0


def test_phase4_malformed_smoother_config_aborts_with_error_code(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """`--smoother-config` with a bad value (negative lambda) aborts the CLI
    with the structured `smoother_config_invalid` error_code on stderr,
    exit code 2 (spec §7.1)."""
    runs_root = tmp_path / "runs"
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("lambda_forbidden: -1.0\n")
    entities, sam3 = _phase4_fixtures()
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
                extra=["--smoother-config", str(bad_yaml)],
            ),
            catch_exceptions=False,
        )
    assert result.exit_code == 2, result.output + result.stderr
    # Structured error JSON on stderr (per write_error_json contract)
    combined = (result.output or "") + (result.stderr or "")
    assert "smoother_config_invalid" in combined


def test_phase4_unknown_label_in_forbidden_aborts_with_error_code(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """`--smoother-config` referencing an unknown label aborts with
    `smoother_unknown_label_in_forbidden` (spec §7.1)."""
    runs_root = tmp_path / "runs"
    bad_yaml = tmp_path / "unknown_label.yaml"
    bad_yaml.write_text(
        "forbidden_transitions:\n  - [grasp_object, no_such_label]\n",
    )
    entities, sam3 = _phase4_fixtures()
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        result = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
                extra=["--smoother-config", str(bad_yaml)],
            ),
            catch_exceptions=False,
        )
    assert result.exit_code == 2, result.output + result.stderr
    combined = (result.output or "") + (result.stderr or "")
    assert "smoother_unknown_label_in_forbidden" in combined


def test_phase4_distinct_run_hash_from_phase3(
    episode, sam3_ckpt: Path, tmp_path: Path,
) -> None:
    """Phase 4's target_phase=4 + smoother in config_hash → distinct run_hash
    from a Phase 3 run on the same inputs."""
    runs_root = tmp_path / "runs"
    entities, sam3 = _phase4_fixtures()
    # Phase 3 run
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        r3 = runner.invoke(
            app,
            [
                "annotate",
                "--video", str(episode.video),
                "--parquet", str(episode.parquet),
                "--task", "pick the red block and place in white bin",
                "--robot", "aloha",
                "--target-phase", "3",
                "--vlm-model", f"fixture://{FIXTURE_VLM_OK_FIRST_TRY}",
                "--offline",
                "--sam3-checkpoint", str(sam3_ckpt),
                "--runs-root", str(runs_root),
                "--score-threshold", "0.10",
            ],
            catch_exceptions=False,
        )
    assert r3.exit_code == 0, r3.output + r3.stderr

    # Phase 4 run
    with patch_phase3(entities=entities, sam3_tracker=sam3):
        r4 = runner.invoke(
            app,
            _phase4_cli_args(
                episode=episode, runs_root=runs_root, sam3_ckpt=sam3_ckpt,
            ),
            catch_exceptions=False,
        )
    assert r4.exit_code == 0, r4.output + r4.stderr

    run_dirs = [
        d for d in runs_root.iterdir()
        if d.is_dir() and d.name.startswith("ep")
    ]
    assert len(run_dirs) == 2, (
        f"expected distinct Phase 3 and Phase 4 run dirs, got {len(run_dirs)}"
    )
    manifests = [json.loads((d / "manifest.json").read_text()) for d in run_dirs]
    phases = sorted(m["generator"]["pipeline_phase"] for m in manifests)
    assert phases == [3, 4]
    hashes = sorted(m["config_hash"] for m in manifests)
    assert hashes[0] != hashes[1], (
        "Phase 3 and Phase 4 must have distinct config_hash on same inputs"
    )
