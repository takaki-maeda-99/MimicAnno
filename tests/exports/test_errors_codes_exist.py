"""Phase 5 — verify all EXPORT_* error codes are defined on ErrorCode enum."""

from __future__ import annotations

from mimicanno.errors import ErrorCode

EXPECTED_EXPORT_CODES = {
    "EXPORT_PROFILE_INVALID",
    "EXPORT_PROFILE_NOT_FOUND",
    "EXPORT_DATASET_NOT_FOUND",
    "EXPORT_RUNS_ROOT_NOT_FOUND",
    "EXPORT_RUN_NOT_FOUND",
    "EXPORT_RUN_AMBIGUOUS",
    "EXPORT_EPISODE_MISMATCH",
    "EXPORT_PHASE_DOWNGRADE",
    "EXPORT_UNLABELED_PRESENT",
    "EXPORT_NOT_REVIEWED",
    "EXPORT_OUT_EXISTS",
    "EXPORT_OUT_PARENT_MISSING",
    "EXPORT_RAW_ACTION_MISSING",
    "EXPORT_FRAME_COUNT_MISMATCH",
    "EXPORT_INPLACE_NO_CONFIRM",
    "EXPORT_INPLACE_BACKUP_FAILED",
    "EXPORT_SINK_VALIDATION_FAILED",
    "EXPORT_EE_POSE_UNAVAILABLE",
    "EXPORT_INTERNAL_MANIFEST_INVALID",
}


def test_all_export_codes_exist() -> None:
    actual = {m.name for m in ErrorCode if m.name.startswith("EXPORT_")}
    missing = EXPECTED_EXPORT_CODES - actual
    assert not missing, f"missing EXPORT_* codes on ErrorCode enum: {missing}"
