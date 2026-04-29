"""Track-id construction (spec §2.1, parent §9.5).

The single source of truth for the `obj:<role>:<slug>:<index>` form.
Downstream code parses by `track_id.split(":")` and trusts the 4-tuple
shape — do not change without coordinating with viewer / annotation /
test code that consumes it.
"""

from __future__ import annotations

import re
from typing import Literal

ROLE = Literal["object", "target", "tool"]
_VALID_ROLES = frozenset({"object", "target", "tool"})

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_RUNS_OF_UNDERSCORE = re.compile(r"_+")


def slugify(prompt: str) -> str:
    """Lowercase + ASCII-fold + replace non-alnum runs with single underscore +
    strip leading/trailing underscores. Empty input returns the sentinel
    "unnamed" (so a downstream track_id is always shaped 4-tuple-by-colons).

    Examples (see test_track_id.py for full table):
      "Red Block" -> "red_block"
      "bin A!!"   -> "bin_a"
      ""          -> "unnamed"
    """
    if not prompt:
        return "unnamed"
    # Lowercase + drop non-ASCII characters
    lowered = prompt.lower()
    ascii_only = lowered.encode("ascii", "ignore").decode("ascii")
    # Replace non-alnum runs with underscore
    collapsed = _SLUG_NON_ALNUM.sub("_", ascii_only)
    # Collapse runs of underscores and strip leading/trailing
    collapsed = _SLUG_RUNS_OF_UNDERSCORE.sub("_", collapsed).strip("_")
    return collapsed if collapsed else "unnamed"


def make_track_id(role: ROLE, prompt: str, index: int) -> str:
    """Construct the canonical track-id string.

    Args:
        role:   one of "object" / "target" / "tool" (parent §9.5).
        prompt: original natural-language prompt; will be slugified.
        index:  per-(role, slug) 0-based occurrence (parent §9.5);
                incremented across re-acquisition splits within the same
                (role, prompt) (spec §2.4 step 6).

    Raises:
        ValueError: if role is not one of the 3 allowed values, or if
                    index is negative.
    """
    if role not in _VALID_ROLES:
        raise ValueError(
            f"role must be one of {sorted(_VALID_ROLES)}, got {role!r}"
        )
    if index < 0:
        raise ValueError(f"index must be non-negative, got {index}")
    return f"obj:{role}:{slugify(prompt)}:{index}"
