from __future__ import annotations

from dataclasses import dataclass

from mimicanno.schema import AnnotationResult


@dataclass
class RunMetrics:
    run_name: str
    total_edits: int
    human_edit_time_ms: int
    client_coverage: float
    human_edited_segments: int
    total_segments: int
    human_touched_fraction: float  # was: label_agreement (renamed in D r2 §2.3)


def compute_metrics(annotation: AnnotationResult, run_name: str) -> RunMetrics:
    history = annotation.history
    total_edits = len(history)
    timed = [e for e in history if e.client_edit_duration_ms is not None]
    human_edit_time_ms = sum(
        e.client_edit_duration_ms for e in timed  # type: ignore[misc]
    )
    client_coverage = len(timed) / total_edits if total_edits > 0 else 0.0
    human_segs = sum(
        1 for s in annotation.segments if s.label_source == "human_edit"
    )
    total_segs = len(annotation.segments)
    human_touched_fraction = human_segs / total_segs if total_segs > 0 else 0.0
    return RunMetrics(
        run_name=run_name,
        total_edits=total_edits,
        human_edit_time_ms=human_edit_time_ms,
        client_coverage=client_coverage,
        human_edited_segments=human_segs,
        total_segments=total_segs,
        human_touched_fraction=human_touched_fraction,
    )


def aggregate(runs: list[RunMetrics]) -> RunMetrics:
    if not runs:
        return RunMetrics("**total**", 0, 0, 0.0, 0, 0, 0.0)
    total_edits = sum(r.total_edits for r in runs)
    human_edit_time_ms = sum(r.human_edit_time_ms for r in runs)
    timed_sum = sum(r.total_edits * r.client_coverage for r in runs)
    client_coverage = timed_sum / total_edits if total_edits > 0 else 0.0
    human_segs = sum(r.human_edited_segments for r in runs)
    total_segs = sum(r.total_segments for r in runs)
    human_touched_fraction = human_segs / total_segs if total_segs > 0 else 0.0
    return RunMetrics(
        "**total**",
        total_edits,
        human_edit_time_ms,
        client_coverage,
        human_segs,
        total_segs,
        human_touched_fraction,
    )
