"""Structured error type for CLI aborts (spec §11)."""

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
    sink = stream or sys.stderr
    sink.write(
        json.dumps(
            {
                "error_code": err.code,
                "message": err.message,
                "context": err.context,
            }
        )
    )
    sink.write("\n")
    sink.flush()


class VLMModelRequired(MimicAnnoError):
    """`--target-phase >= 2` invoked without `--vlm-model` (spec §4.2)."""

    def __init__(self, target_phase: int) -> None:
        super().__init__(
            code="vlm_model_required",
            message=f"target_phase={target_phase} requires --vlm-model",
            context={"target_phase": target_phase},
        )


class VLMConfigInvalid(MimicAnnoError):
    """VLMConfig has an out-of-range or contradictory field (spec §4.2)."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            code="vlm_config_invalid",
            message=reason,
            context={},
        )


class VLMModelNotFound(MimicAnnoError):
    """Pre-flight could not resolve --vlm-model (HF 404, network, fixture file
    missing, --offline gating). Spec §4.2."""

    def __init__(self, model_id: str, reason: str) -> None:
        super().__init__(
            code="vlm_model_not_found",
            message=f"could not resolve vlm_model={model_id!r}: {reason}",
            context={"model_id": model_id, "reason": reason},
        )
