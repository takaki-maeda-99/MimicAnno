"""parse_and_validate (spec §3.4)."""
from __future__ import annotations

import pytest

from mimicanno.vlm_labeler import (
    EVIDENCE_DISPLAY_HINT_CHARS,
    LabelerError,
    parse_and_validate,
)

ALLOWED = {"idle", "approach_object", "grasp_object"}


def _ok(extra: str = "") -> str:
    return (
        '{"phase": "grasp_object", "verb": "grasp", "object": "block", '
        '"target": null, "vlm_confidence": 0.7, "evidence": "g closing"' + extra + "}"
    )


def test_happy_path() -> None:
    r = parse_and_validate(_ok(), ALLOWED)
    assert r["phase"] == "grasp_object"
    assert r["verb"] == "grasp"
    assert r["target"] is None
    assert r["vlm_confidence"] == pytest.approx(0.7)
    assert r["evidence"] == "g closing"


def test_strips_markdown_fences() -> None:
    raw = "```json\n" + _ok() + "\n```"
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "grasp_object"


def test_unknown_phase_accepted() -> None:
    raw = '{"phase": "unknown", "vlm_confidence": 0.0}'
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "unknown"


def test_extra_fields_ignored() -> None:
    raw = '{"phase": "idle", "vlm_confidence": 0.5, "extra_future_field": 42}'
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "idle"


# ---- reject paths ---------------------------------------------------------

def test_json_parse_error() -> None:
    with pytest.raises(LabelerError) as ei:
        parse_and_validate("not json", ALLOWED)
    assert ei.value.reject_reason == "json_parse_error"


def test_schema_violation_missing_phase() -> None:
    raw = '{"vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_schema_violation_phase_wrong_type() -> None:
    raw = '{"phase": 42, "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_schema_violation_verb_wrong_type() -> None:
    raw = '{"phase": "idle", "verb": 42, "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_invalid_label() -> None:
    raw = '{"phase": "made_up", "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "invalid_label"


def test_unlabeled_is_invalid() -> None:
    """Reserved 'unlabeled' MUST never be a valid Phase 2 VLM output."""
    raw = '{"phase": "unlabeled", "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "invalid_label"


def test_out_of_range_confidence_high() -> None:
    raw = '{"phase": "idle", "vlm_confidence": 1.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "out_of_range_confidence"


def test_out_of_range_confidence_low() -> None:
    raw = '{"phase": "idle", "vlm_confidence": -0.01}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "out_of_range_confidence"


# ---- soft truncation ------------------------------------------------------

def test_evidence_over_length_truncated_not_rejected() -> None:
    long = "x" * (EVIDENCE_DISPLAY_HINT_CHARS + 50)
    raw = (
        '{"phase": "idle", "vlm_confidence": 0.5, "evidence": "' + long + '"}'
    )
    r = parse_and_validate(raw, ALLOWED)
    assert r["evidence"] is not None
    assert len(r["evidence"]) == EVIDENCE_DISPLAY_HINT_CHARS
