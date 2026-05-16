from __future__ import annotations

import datetime as dt
import json

from mimicanno.eval.metrics import RunMetrics


def render_markdown(runs: list[RunMetrics], agg: RunMetrics) -> str:
    now = dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")
    header = f"## MimicAnno eval — {now}\n\n"
    cols = "| run | edits | edit_time_ms | client_cov | human_segs | total_segs | label_agr |\n"
    sep = "|-----|-------|-------------|------------|------------|------------|----------|\n"

    def row(r: RunMetrics) -> str:
        return (
            f"| {r.run_name} | {r.total_edits} | {r.human_edit_time_ms} "
            f"| {r.client_coverage:.2f} | {r.human_edited_segments} "
            f"| {r.total_segments} | {r.label_agreement:.2f} |\n"
        )

    return header + cols + sep + "".join(row(r) for r in runs) + row(agg)


def render_json(runs: list[RunMetrics], agg: RunMetrics) -> str:
    def to_dict(r: RunMetrics) -> dict[str, object]:
        return {
            "run": r.run_name,
            "total_edits": r.total_edits,
            "human_edit_time_ms": r.human_edit_time_ms,
            "client_coverage": round(r.client_coverage, 4),
            "human_edited_segments": r.human_edited_segments,
            "total_segments": r.total_segments,
            "label_agreement": round(r.label_agreement, 4),
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
