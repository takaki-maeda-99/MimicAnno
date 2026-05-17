from __future__ import annotations

import datetime as dt
import json
from typing import Any

from mimicanno.eval.metrics import (
    AgreementSubBlock,
    PlannerAgreementBlock,
    RunMetrics,
)


def _render_confusion_matrix(matrix: dict[str, dict[str, int]]) -> str:
    if not matrix:
        return ""
    cols = sorted({col for row in matrix.values() for col in row})
    rows = sorted(matrix.keys())
    if not cols or not rows:
        return ""
    lines = ["", "#### Confusion matrix (planner phase → final phase)", ""]
    header = "| planner \\\\ final | " + " | ".join(cols) + " |"
    sep = "|" + "---|" * (len(cols) + 1)
    lines += [header, sep]
    for row in rows:
        cells = [str(matrix[row].get(col, 0)) for col in cols]
        lines.append(f"| {row} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _render_breakdown(title: str, blocks: dict[str, AgreementSubBlock]) -> str:
    if not blocks:
        return ""
    lines = ["", f"#### {title}", "", "| key | agree | disagree | rate |", "|---|---|---|---|"]
    for key, block in sorted(blocks.items()):
        lines.append(f"| {key} | {block.agree} | {block.disagree} | {block.rate:.3f} |")
    return "\n".join(lines) + "\n"


def _render_planner_agreement(pa: PlannerAgreementBlock | None) -> str:
    if pa is None:
        return (
            "\n_planner_agreement: **unavailable** "
            "(run schema is pre-0.4.0; upgrade by re-running PATCH or `mimicanno annotate`)._\n"
        )
    lines = [
        "",
        f"**planner_agreement (overall): `{pa.overall_rate:.3f}`** "
        f"(agreement_unavailable_count: {pa.agreement_unavailable_count})",
    ]
    out = "\n".join(lines) + "\n"
    out += _render_confusion_matrix(pa.confusion_matrix)
    out += _render_breakdown("Agreement by source", pa.by_source)
    out += _render_breakdown("Agreement by confidence bucket", pa.by_confidence_bucket)
    out += _render_breakdown("Agreement by planner phase", pa.by_phase)
    return out


def render_markdown(runs: list[RunMetrics], agg: RunMetrics) -> str:
    now = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    header = f"## MimicAnno eval — {now}\n\n"
    cols = "| run | edits | edit_time_ms | client_cov | human_segs | total_segs | human_touched |\n"
    sep = "|-----|-------|-------------|------------|------------|------------|---------------|\n"

    def row(r: RunMetrics) -> str:
        return (
            f"| {r.run_name} | {r.total_edits} | {r.human_edit_time_ms} "
            f"| {r.client_coverage:.2f} | {r.human_edited_segments} "
            f"| {r.total_segments} | {r.human_touched_fraction:.2f} |\n"
        )

    footnote = (
        "\n_`human_touched` = fraction of segments with `label_source='human_edit'`. "
        "This is a **human-workload proxy**, NOT planner-agreement. "
        "True agreement would require comparing the initial planner label to the "
        "final human-confirmed label per field; that requires extending `EditEvent` "
        "with old/new values and is deferred to Phase 6 (eval v2)._\n"
    )

    parts = [header, cols, sep]
    for r in runs:
        parts.append(row(r))
    parts.append(row(agg))
    parts.append(footnote)

    # Per-run planner_agreement sections
    for r in runs:
        parts.append(f"\n### {r.run_name}\n")
        parts.append(_render_planner_agreement(r.planner_agreement))

    return "".join(parts)


def render_json(runs: list[RunMetrics], agg: RunMetrics) -> str:
    def to_dict(r: RunMetrics) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run": r.run_name,
            "total_edits": r.total_edits,
            "human_edit_time_ms": r.human_edit_time_ms,
            "client_coverage": round(r.client_coverage, 4),
            "human_edited_segments": r.human_edited_segments,
            "total_segments": r.total_segments,
            "human_touched_fraction": round(r.human_touched_fraction, 4),
            "planner_agreement": (
                r.planner_agreement.to_dict() if r.planner_agreement is not None else None
            ),
        }
        return d

    now = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    return json.dumps(
        {
            "generated_at": now,
            "runs": [to_dict(r) for r in runs],
            "aggregate": to_dict(agg),
        },
        indent=2,
    )
