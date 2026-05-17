"""Build EditEvent instances for PATCH write transactions."""
from __future__ import annotations

import datetime as dt

from mimicanno.schema import EditEvent, EditValue


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")


# Map edit_type to the expected kind tag of its EditValue payload.
_EXPECTED_KIND: dict[str, str] = {
    "relabel": "relabel",
    "boundary": "boundary",
    "reviewed": "reviewed",
    "labels": "labels",
}


def build_edit_event(
    *,
    edit_type: str,
    segment_id: str,
    client_edit_duration_ms: int | None,
    reviewer: str | None,
    old_value: EditValue | None = None,
    new_value: EditValue | None = None,
    pre_edit_overall_confidence: float | None = None,
) -> EditEvent:
    if old_value is not None:
        expected = _EXPECTED_KIND[edit_type]
        if old_value["kind"] != expected:
            raise ValueError(
                f"old_value.kind={old_value['kind']!r} does not match edit_type={edit_type!r} (expected kind={expected!r})"
            )
    if new_value is not None:
        expected = _EXPECTED_KIND[edit_type]
        if new_value["kind"] != expected:
            raise ValueError(
                f"new_value.kind={new_value['kind']!r} does not match edit_type={edit_type!r}"
            )
    return EditEvent(
        edit_type=edit_type,
        segment_id=segment_id,
        edited_at=_now_iso(),
        client_edit_duration_ms=client_edit_duration_ms,
        reviewer=reviewer,
        old_value=old_value,
        new_value=new_value,
        pre_edit_overall_confidence=pre_edit_overall_confidence,
    )
