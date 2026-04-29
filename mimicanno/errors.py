"""Structured error type for CLI aborts (spec §11)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Literal, TextIO


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


MissingDependencyField = Literal["--sam3-checkpoint"]


class MissingDependencyError(MimicAnnoError):
    """A required CLI argument was not provided (spec §8 abort guard).

    Tier-1 abort, exits non-zero. The `field` context is the missing flag name.
    Currently only fired for `--sam3-checkpoint` (Phase 3); `--vlm-model` has
    its own dedicated `VLMModelRequired` for Phase 2 backwards-compat. Extend
    `MissingDependencyField` Literal when a new Tier-1 missing-flag abort lands.
    """

    def __init__(self, field: MissingDependencyField) -> None:
        super().__init__(
            code="missing_dependency",
            message=f"required argument missing: {field}",
            context={"field": field},
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


class SAM3CheckpointNotFound(MimicAnnoError):
    """`--sam3-checkpoint` path missing / unreadable / sha256 cannot be
    computed (spec §8). Tier-1 abort, exits non-zero."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(
            code="sam3_checkpoint_not_found",
            message=f"sam3 checkpoint missing or unreadable at {path}: {reason}",
            context={"path": path, "reason": reason},
        )


class SAM3ExtrasMissing(MimicAnnoError):
    """`import sam3` raises ModuleNotFoundError under `--target-phase 3`
    (spec §8). Tier-1 abort, exits non-zero."""

    def __init__(self) -> None:
        super().__init__(
            code="sam3_extras_missing",
            message=(
                "the sam3 package is not installed; "
                "install with `pip install '.[sam3]'`"
            ),
            context={},
        )


class SAM3RuntimeFailed(MimicAnnoError):
    """`SAM3Runtime.propagate(...)` raises mid-episode (spec §8).
    Aborts with non-zero exit; in-flight tmp dir is rm -rf'd best-effort."""

    def __init__(self, frame_index: int, reason: str) -> None:
        super().__init__(
            code="sam3_runtime_failed",
            message=f"sam3 propagation failed at frame {frame_index}: {reason}",
            context={"frame_index": frame_index, "reason": reason},
        )


class SAM3InitFailed(MimicAnnoError):
    """`SAM3Runtime.load(...)` raises (CUDA OOM, incompatible weights, etc.)
    after preflight passed (spec §8). DEGRADE reason — never written to stderr
    structured JSON; the underlying repr() is logged to stderr as a WARN line.
    The `underlying` context field exists for the WARN log only; it is NEVER
    written to annotation.notes (PII rule, spec §7.2 / §8)."""

    def __init__(self, underlying: str) -> None:
        super().__init__(
            code="sam3_init_failed",
            message="sam3 model load failed",
            context={"underlying": underlying},
        )


class GemmaNoObjectPrompts(MimicAnnoError):
    """Gemma planner Step A returned `object_prompts == []` (or all parses
    failed across `planner_max_retries`). DEGRADE reason — Phase-3-objectless
    run (spec §7.2)."""

    def __init__(self) -> None:
        super().__init__(
            code="gemma_no_object_prompts",
            message="gemma planner returned no object prompts",
            context={},
        )


class SAM3NoInitialDetection(MimicAnnoError):
    """SAM3 Step B grounding returned no bbox for any object prompt
    (spec §7.2). DEGRADE reason — Phase-3-objectless run."""

    def __init__(self, failed: list[tuple[str, str]]) -> None:
        super().__init__(
            code="sam3_no_initial_detection",
            message="sam3 grounded no bbox for any object prompt",
            context={
                "failed_prompts": [
                    {"role": role, "prompt": prompt} for role, prompt in failed
                ]
            },
        )


class ArtifactIntegrityError(MimicAnnoError):
    """tracks.json cross-artifact integrity mismatch (spec §3.3).

    Raised by ``read_tracks_json`` when ``episode_id``, ``fps``, or
    ``n_frames`` in the file does not match the expected values from
    ``manifest.json``.
    """

    def __init__(self, field: str, expected: object, actual: object) -> None:
        super().__init__(
            code="tracks_json_integrity_violation",
            message=(
                f"tracks.json integrity violation: {field} mismatch "
                f"(expected={expected!r}, actual={actual!r})"
            ),
            context={"field": field, "expected": expected, "actual": actual},
        )
