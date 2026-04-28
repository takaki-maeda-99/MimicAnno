"""Track-id slugify + make_track_id (spec §2.1, parent §9.5)."""

from __future__ import annotations

import pytest

from mimicanno.object_tracker.track_id import make_track_id, slugify


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Red Block", "red_block"),
        ("red block", "red_block"),
        ("RED  BLOCK", "red_block"),       # collapse runs of whitespace
        ("bin A!!", "bin_a"),               # strip punctuation
        ("bin-A_2", "bin_a_2"),             # hyphen and existing _ both collapse
        ("__under__score__", "under_score"),# strip leading/trailing underscores
        ("café", "caf"),                    # ASCII fold (drop non-alnum)
        ("   ", "unnamed"),                 # whitespace-only -> sentinel
        ("", "unnamed"),                    # empty -> sentinel
        ("123", "123"),                     # digits preserved
        ("ALL_CAPS", "all_caps"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_make_track_id_format() -> None:
    """spec §9.5: obj:<role>:<slug>:<index> — colon-separated, parseable by split."""
    tid = make_track_id("object", "Red Block", 0)
    assert tid == "obj:object:red_block:0"
    parts = tid.split(":")
    assert parts == ["obj", "object", "red_block", "0"]


def test_make_track_id_role_validation() -> None:
    """Only the 3 spec-defined roles are accepted."""
    for role in ("object", "target", "tool"):
        make_track_id(role, "x", 0)        # type: ignore[arg-type]  # OK
    with pytest.raises(ValueError):
        make_track_id("invalid", "x", 0)   # type: ignore[arg-type]


def test_make_track_id_index_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        make_track_id("object", "x", -1)


def test_make_track_id_uses_slugified_prompt() -> None:
    assert make_track_id("target", "Bin A!!", 0) == "obj:target:bin_a:0"
