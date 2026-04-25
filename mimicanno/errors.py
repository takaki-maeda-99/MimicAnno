"""Structured error type for MimicAno."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO


@dataclass
class MimicAnnoError(Exception):
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def write_error_json(err: MimicAnnoError, *, stream: TextIO | None = None) -> None:
    """Serialise *err* as JSON to *stream* (default: ``sys.stderr``)."""
    if stream is None:
        stream = sys.stderr
    payload = {"code": err.code, "message": err.message, "context": err.context}
    json.dump(payload, stream)
