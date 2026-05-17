from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mimicanno.schema import AnnotationResult, EditEvent


@dataclass(frozen=True)
class AgreementSubBlock:
    agree: int
    disagree: int

    @property
    def rate(self) -> float:
        total = self.agree + self.disagree
        return self.agree / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"agree": self.agree, "disagree": self.disagree, "rate": self.rate}


@dataclass(frozen=True)
class PlannerAgreementBlock:
    overall_rate: float
    agreement_unavailable_count: int
    confusion_matrix: dict[str, dict[str, int]]
    by_source: dict[str, AgreementSubBlock]
    by_confidence_bucket: dict[str, AgreementSubBlock]
    by_phase: dict[str, AgreementSubBlock]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_rate": self.overall_rate,
            "agreement_unavailable_count": self.agreement_unavailable_count,
            "confusion_matrix": self.confusion_matrix,
            "by_source": {k: v.to_dict() for k, v in self.by_source.items()},
            "by_confidence_bucket": {
                k: v.to_dict() for k, v in self.by_confidence_bucket.items()
            },
            "by_phase": {k: v.to_dict() for k, v in self.by_phase.items()},
        }


@dataclass
class RunMetrics:
    run_name: str
    total_edits: int
    human_edit_time_ms: int
    client_coverage: float
    human_edited_segments: int
    total_segments: int
    human_touched_fraction: float  # was: label_agreement (renamed in D r2 §2.3)
    planner_agreement: PlannerAgreementBlock | None = None


def _first_relabel_event(history: list[EditEvent], segment_id: str) -> EditEvent | None:
    matches = [
        e for e in history if e.edit_type == "relabel" and e.segment_id == segment_id
    ]
    if not matches:
        return None
    return min(matches, key=lambda e: e.edited_at)


def _confidence_bucket(confidence: float) -> str:
    if confidence < 0.5:
        return "low"
    if confidence < 0.85:
        return "mid"
    return "high"


def compute_planner_agreement(
    annotation: AnnotationResult,
) -> PlannerAgreementBlock | None:
    # None trigger: pre-0.4.0 runs cannot carry old_value, so agreement is
    # unavailable. Use schema_version as the authoritative signal — heuristics
    # like "no relabel event has old_value" would falsely fire for 0.4.0 runs
    # whose human edits were reviewed/labels only.
    if annotation.schema_version != "0.4.0":
        return None

    confusion: dict[str, dict[str, int]] = {}
    by_source: dict[str, list[bool]] = {}
    by_confidence: dict[str, list[bool]] = {}
    by_phase: dict[str, list[bool]] = {}
    unavailable = 0
    agree = 0
    disagree = 0

    for seg in annotation.segments:
        ev = _first_relabel_event(annotation.history, seg.segment_id)
        if ev is not None:
            if ev.old_value is None:
                # 0.4.0 run with an individual event missing old_value
                # (partial-write recovery scenario, very rare). Surface gap.
                unavailable += 1
                continue
            # Discriminated union narrowing — load-bearing for mypy --strict.
            assert ev.old_value["kind"] == "relabel"
            planner_phase: str = ev.old_value["value"]
            confidence: float | None = ev.pre_edit_overall_confidence
            source = "human_edit"
        else:
            planner_phase = seg.phase
            confidence = seg.overall_confidence
            source = seg.label_source

        final_phase = seg.phase
        agrees = planner_phase == final_phase
        if agrees:
            agree += 1
        else:
            disagree += 1

        confusion.setdefault(planner_phase, {})
        confusion[planner_phase].setdefault(final_phase, 0)
        confusion[planner_phase][final_phase] += 1

        by_source.setdefault(source, []).append(agrees)
        if confidence is not None:
            by_confidence.setdefault(_confidence_bucket(confidence), []).append(agrees)
        else:
            by_confidence.setdefault("unknown", []).append(agrees)
        by_phase.setdefault(planner_phase, []).append(agrees)

    def to_block(bucket: list[bool]) -> AgreementSubBlock:
        a = sum(bucket)
        d = len(bucket) - a
        return AgreementSubBlock(agree=a, disagree=d)

    total = agree + disagree
    return PlannerAgreementBlock(
        overall_rate=agree / total if total > 0 else 0.0,
        agreement_unavailable_count=unavailable,
        confusion_matrix=confusion,
        by_source={k: to_block(v) for k, v in by_source.items()},
        by_confidence_bucket={k: to_block(v) for k, v in by_confidence.items()},
        by_phase={k: to_block(v) for k, v in by_phase.items()},
    )


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
        planner_agreement=compute_planner_agreement(annotation),
    )


def aggregate(runs: list[RunMetrics]) -> RunMetrics:
    if not runs:
        return RunMetrics(
            run_name="**total**",
            total_edits=0,
            human_edit_time_ms=0,
            client_coverage=0.0,
            human_edited_segments=0,
            total_segments=0,
            human_touched_fraction=0.0,
            planner_agreement=None,
        )
    total_edits = sum(r.total_edits for r in runs)
    human_edit_time_ms = sum(r.human_edit_time_ms for r in runs)
    timed_sum = sum(r.total_edits * r.client_coverage for r in runs)
    client_coverage = timed_sum / total_edits if total_edits > 0 else 0.0
    human_segs = sum(r.human_edited_segments for r in runs)
    total_segs = sum(r.total_segments for r in runs)
    human_touched_fraction = human_segs / total_segs if total_segs > 0 else 0.0
    return RunMetrics(
        run_name="**total**",
        total_edits=total_edits,
        human_edit_time_ms=human_edit_time_ms,
        client_coverage=client_coverage,
        human_edited_segments=human_segs,
        total_segments=total_segs,
        human_touched_fraction=human_touched_fraction,
        planner_agreement=None,
    )
