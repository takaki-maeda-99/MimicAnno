"""Phase 5 — verify shipped JSON schemas load and are Draft 2020-12 valid."""

from __future__ import annotations

import json
from importlib import resources

import jsonschema


def _load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads(
        resources.files("mimicanno.jsonschemas").joinpath(name).read_text()
    )


def test_export_profile_schema_is_draft_2020() -> None:
    sch = _load("export_profile.schema.json")
    jsonschema.Draft202012Validator.check_schema(sch)
    assert sch["$id"].endswith("export_profile.schema.json")


def test_export_manifest_schema_is_draft_2020() -> None:
    sch = _load("export_manifest.schema.json")
    jsonschema.Draft202012Validator.check_schema(sch)
    assert sch["$id"].endswith("export_manifest.schema.json")


def test_mimicanno_segments_schema_documents_columns() -> None:
    sch = _load("mimicanno_segments.schema.json")
    cols = sch["required_columns"]
    expected = {
        "episode_index",
        "segment_index",
        "segment_id",
        "phase",
        "verb",
        "object",
        "target",
        "failure_flags",
        "start_frame",
        "end_frame",
        "start_time",
        "end_time",
        "label_source",
        "object_state_unavailable",
        "object_track_ids",
        "label_version",
        "boundary_confidence",
        "vlm_confidence",
        "overall_confidence",
        "evidence",
        "reviewed",
        "reviewer_id",
        "smoothing_ops",
        "boundary_source_start",
        "boundary_source_end",
        "run_hash",
        "config_hash",
        "input_hash",
        "pipeline_phase",
        "mimicanno_version",
        "generated_at",
    }
    assert set(cols.keys()) == expected
