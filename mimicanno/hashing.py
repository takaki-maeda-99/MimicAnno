"""Deterministic JSON + sha256 helpers.

All hashes used in canonical_name (spec §4.1) flow through here.
Determinism rules:
- dict keys sorted ASCII-lexicographically
- no whitespace separators
- non-ASCII strings kept as-is (ensure_ascii=False)
- NaN / Infinity rejected (canonical hashing must not depend on platform float quirks)
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` to a stable, whitespace-free, sort-keys JSON string.

    The result is suitable for hashing: identical inputs produce byte-identical output
    across machines and Python versions.
    """
    # Walk obj first to surface NaN/Infinity with descriptive messages before
    # json.dumps swallows the float identity into a generic error string.
    _validate_no_nan_inf(obj)
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_no_nan_inf(obj: Any) -> None:
    """Recursively reject NaN and Infinity with descriptive ValueError messages."""
    if isinstance(obj, float):
        if math.isnan(obj):
            raise ValueError("NaN is not allowed in canonical JSON")
        if math.isinf(obj):
            raise ValueError("Infinity is not allowed in canonical JSON")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _validate_no_nan_inf(k)
            _validate_no_nan_inf(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _validate_no_nan_inf(item)


def sha256_hex_of_str(s: str) -> str:
    """Return the SHA-256 hex digest of ``s`` encoded as UTF-8."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of the file at ``path`` (streamed in 1 MiB chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()
