"""RT-1: label round-trip test (Phase 5 Task 26, spec §10.1).

Loads each of the 3 ``mini_runs/`` annotation.json files (representing
different phase 4 segment configurations), runs the full export via
``mimicanno.export(...)`` against the ``mini_so101`` fixture, reads back
``meta/mimicanno_segments.parquet`` + ``meta/subtasks.parquet`` and rebuilds
``SubtaskSegment`` instances via ``SubtaskSegment.from_row``. Asserts every
field of every reconstructed segment equals the original — except the
documented lossy fields per spec §3.3:

- ``start_boundary.per_source_scores`` / ``end_boundary.per_source_scores``
  (the sidecar only stores the aggregated ``boundary_confidence``).
- ``start_boundary.score`` / ``end_boundary.score`` (collapsed to
  ``boundary_confidence`` on round-trip; the per-edge per-source detail
  remains in ``boundaries.json``).
- ``start_boundary.candidate_id`` / ``end_boundary.candidate_id`` (lossy —
  the sidecar reconstructs as ``None``).
- ``start_boundary.time`` / ``end_boundary.time`` are reconstructed from the
  segment's ``start_time`` / ``end_time`` columns; they happen to equal the
  original boundary times for a Phase 4 manifest where each segment
  boundary aligns with its time edges, but we treat them as derived rather
  than asserting structural equality of the boundary refs.

Confidence floats are stored as ``float32`` in the sidecar parquet schema
(``_SIDECAR_SCHEMA``), so the JSON-side ``float64`` values widen on
round-trip (e.g. 0.85 -> 0.8500000238418579). We compare those fields
with float32 tolerance via ``pytest.approx(rel=1e-6)``.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from mimicanno import export
from mimicanno.io import read_annotation_result
from mimicanno.schema import SubtaskSegment

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DATASET_DIR = FIXTURES_DIR / "mini_so101"
RUNS_DIR = FIXTURES_DIR / "mini_runs"


def _assert_segments_round_trip(
    orig: list[SubtaskSegment],
    reconstructed: list[SubtaskSegment],
) -> None:
    """Field-by-field SubtaskSegment equality, modulo documented lossy fields.

    Compared (must equal exactly):
        segment_id, episode_id, start_frame, end_frame, start_time, end_time,
        phase, verb, object, target, failure_flags, label_source,
        object_state_unavailable, object_track_ids, label_version,
        boundary_confidence, vlm_confidence, overall_confidence, evidence,
        reviewed, reviewer_id, smoothing_ops,
        start_boundary.sources, end_boundary.sources.

    Compared structurally (lossy):
        start_boundary.score, end_boundary.score → both equal
        ``boundary_confidence`` post-round-trip (spec §3.3).
        start_boundary.candidate_id, end_boundary.candidate_id → ``None``.
        start_boundary.time, end_boundary.time → equal segment.start_time /
        segment.end_time (the sidecar does not store the original boundary
        times; from_row uses the segment-level times).
    """
    assert len(orig) == len(reconstructed), (
        f"segment count differs: orig={len(orig)} vs got={len(reconstructed)}"
    )
    for i, (o, r) in enumerate(zip(orig, reconstructed, strict=True)):
        ctx = f"segment[{i}] segment_id={o.segment_id!r}"
        # Plain scalar / sequence fields.
        assert o.segment_id == r.segment_id, ctx
        assert o.episode_id == r.episode_id, ctx
        assert o.start_frame == r.start_frame, ctx
        assert o.end_frame == r.end_frame, ctx
        assert o.start_time == r.start_time, ctx
        assert o.end_time == r.end_time, ctx
        assert o.phase == r.phase, ctx
        assert o.verb == r.verb, ctx
        assert o.object == r.object, ctx
        assert o.target == r.target, ctx
        assert list(o.failure_flags) == list(r.failure_flags), ctx
        assert o.label_source == r.label_source, ctx
        assert o.object_state_unavailable == r.object_state_unavailable, ctx
        assert list(o.object_track_ids) == list(r.object_track_ids), ctx
        assert o.label_version == r.label_version, ctx
        # Confidence fields: float32 storage in the sidecar widens the JSON
        # float64 values; compare with float32-tight tolerance.
        assert r.boundary_confidence == pytest.approx(
            o.boundary_confidence, rel=1e-6
        ), ctx
        if o.vlm_confidence is None:
            assert r.vlm_confidence is None, ctx
        else:
            assert r.vlm_confidence == pytest.approx(
                o.vlm_confidence, rel=1e-6
            ), ctx
        assert r.overall_confidence == pytest.approx(
            o.overall_confidence, rel=1e-6
        ), ctx
        assert o.evidence == r.evidence, ctx
        assert o.reviewed == r.reviewed, ctx
        assert o.reviewer_id == r.reviewer_id, ctx
        assert list(o.smoothing_ops) == list(r.smoothing_ops), ctx
        # Boundary refs: sources preserved exactly; score collapsed; candidate_id lost.
        assert list(o.start_boundary.sources) == list(r.start_boundary.sources), (
            f"{ctx} start_boundary.sources"
        )
        assert list(o.end_boundary.sources) == list(r.end_boundary.sources), (
            f"{ctx} end_boundary.sources"
        )
        assert r.start_boundary.candidate_id is None, ctx
        assert r.end_boundary.candidate_id is None, ctx
        # Lossy: edge scores are both reconstructed as boundary_confidence
        # (also float32 round-tripped).
        assert r.start_boundary.score == pytest.approx(
            o.boundary_confidence, rel=1e-6
        ), ctx
        assert r.end_boundary.score == pytest.approx(
            o.boundary_confidence, rel=1e-6
        ), ctx
        # Reconstructed boundary times come from segment.start_time / end_time.
        assert r.start_boundary.time == o.start_time, ctx
        assert r.end_boundary.time == o.end_time, ctx


def _read_sidecar_rows_for_episode(
    out: Path, episode_index: int
) -> list[SubtaskSegment]:
    """Read the sidecar parquet, filter to ``episode_index``, return segments."""
    sidecar_path = out / "meta" / "mimicanno_segments.parquet"
    table = pq.read_table(sidecar_path)  # type: ignore[no-untyped-call]
    rows = table.to_pylist()
    rows = [r for r in rows if r["episode_index"] == episode_index]
    rows.sort(key=lambda r: r["segment_index"])
    # Inject episode_id (not stored on segment-level columns; read from the
    # original annotation context).
    episode_id = f"episode_{episode_index:06d}"
    return [
        SubtaskSegment.from_row({**r, "episode_id": episode_id}) for r in rows
    ]


@pytest.mark.parametrize("episode_index", [0, 1, 2])
def test_label_round_trip_per_episode(
    tmp_path: Path, episode_index: int
) -> None:
    """RT-1: original annotation.json -> sidecar parquet -> SubtaskSegment list.

    Assert reconstructed segments match the originals modulo lossy fields.
    """
    # Find the run dir for this episode.
    run_dirs = [
        d for d in RUNS_DIR.iterdir()
        if d.is_dir() and d.name.startswith(f"episode_{episode_index:06d}__")
    ]
    assert len(run_dirs) == 1, (
        f"expected 1 run dir for episode {episode_index}, got {run_dirs}"
    )
    run_dir = run_dirs[0]
    annotation = read_annotation_result(run_dir / "annotation.json")
    orig_segments = list(annotation.segments)
    assert orig_segments, "test fixture must have at least one segment"

    out = tmp_path / "OUT"
    result = export(
        dataset_root=DATASET_DIR,
        runs_root=RUNS_DIR,
        target_phase=4,
        profile="so101_sarm",
        out=out,
        output_mode="symlink",
    )
    assert result.episode_count == 3
    assert result.reused is False

    reconstructed = _read_sidecar_rows_for_episode(out, episode_index)
    _assert_segments_round_trip(orig_segments, reconstructed)


def test_label_round_trip_all_episodes(tmp_path: Path) -> None:
    """RT-1 across all 3 mini_runs episodes in a single export."""
    out = tmp_path / "OUT"
    export(
        dataset_root=DATASET_DIR,
        runs_root=RUNS_DIR,
        target_phase=4,
        profile="so101_sarm",
        out=out,
        output_mode="symlink",
    )

    for episode_index in range(3):
        run_dirs = [
            d for d in RUNS_DIR.iterdir()
            if d.is_dir() and d.name.startswith(f"episode_{episode_index:06d}__")
        ]
        assert len(run_dirs) == 1
        annotation = read_annotation_result(run_dirs[0] / "annotation.json")
        reconstructed = _read_sidecar_rows_for_episode(out, episode_index)
        _assert_segments_round_trip(list(annotation.segments), reconstructed)


def test_label_round_trip_subtasks_registry_contains_all_phases(
    tmp_path: Path,
) -> None:
    """The subtasks.parquet registry must list every phase that appears in
    any of the 3 annotations (and only those)."""
    out = tmp_path / "OUT"
    export(
        dataset_root=DATASET_DIR,
        runs_root=RUNS_DIR,
        target_phase=4,
        profile="so101_sarm",
        out=out,
        output_mode="symlink",
    )

    expected_phases: set[str] = set()
    for episode_index in range(3):
        run_dirs = [
            d for d in RUNS_DIR.iterdir()
            if d.is_dir() and d.name.startswith(f"episode_{episode_index:06d}__")
        ]
        annotation = read_annotation_result(run_dirs[0] / "annotation.json")
        for seg in annotation.segments:
            expected_phases.add(seg.phase)

    table = pq.read_table(out / "meta" / "subtasks.parquet")  # type: ignore[no-untyped-call]
    registry_phases = set(table.column("subtask").to_pylist())
    # mini_runs has full coverage so 'unlabeled' should not be injected.
    assert registry_phases == expected_phases
