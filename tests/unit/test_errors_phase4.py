"""Phase 4 error code subclasses (spec §7.1)."""
from __future__ import annotations

from mimicanno.errors import (
    SmootherConfigInvalid,
    SmootherSegmentInvariantViolation,
    SmootherUnknownLabelInForbidden,
)


def test_smoother_config_invalid_code_and_message() -> None:
    err = SmootherConfigInvalid(reason="lambda_forbidden must be >= 0",
                                path="/tmp/x.yaml")
    assert err.code == "smoother_config_invalid"
    assert "lambda_forbidden" in err.message
    assert err.context.get("path") == "/tmp/x.yaml"


def test_smoother_unknown_label_in_forbidden_code() -> None:
    err = SmootherUnknownLabelInForbidden(label="not_a_label",
                                          path="/tmp/x.yaml")
    assert err.code == "smoother_unknown_label_in_forbidden"
    assert "not_a_label" in err.message


def test_smoother_segment_invariant_violation_code() -> None:
    err = SmootherSegmentInvariantViolation(reason="gap between segments")
    assert err.code == "smoother_segment_invariant_violation"
    assert "gap" in err.message
