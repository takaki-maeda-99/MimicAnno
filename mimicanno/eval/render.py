from __future__ import annotations

import datetime as dt
import json

from mimicanno.eval.metrics import RunMetrics


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

    return header + cols + sep + "".join(row(r) for r in runs) + row(agg) + footnote


def render_json(runs: list[RunMetrics], agg: RunMetrics) -> str:
    def to_dict(r: RunMetrics) -> dict[str, object]:
        return {
            "run": r.run_name,
            "total_edits": r.total_edits,
            "human_edit_time_ms": r.human_edit_time_ms,
            "client_coverage": round(r.client_coverage, 4),
            "human_edited_segments": r.human_edited_segments,
            "total_segments": r.total_segments,
            "human_touched_fraction": round(r.human_touched_fraction, 4),
        }

    now = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    return json.dumps(
        {
            "generated_at": now,
            "runs": [to_dict(r) for r in runs],
            "aggregate": to_dict(agg),
        },
        indent=2,
    )
