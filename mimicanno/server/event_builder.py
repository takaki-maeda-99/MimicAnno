"""Build EditEvent instances for PATCH write transactions."""
from __future__ import annotations

import datetime as dt

from mimicanno.schema import EditEvent


def _now_iso() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat().replace("+00:00", "Z")


def build_edit_event(
    *,
    edit_type: str,
    segment_id: str,
    client_edit_duration_ms: int | None,
    reviewer: str | None,
) -> EditEvent:
    return EditEvent(
        edit_type=edit_type,
        segment_id=segment_id,
        edited_at=_now_iso(),
        client_edit_duration_ms=client_edit_duration_ms,
        reviewer=reviewer,
    )
