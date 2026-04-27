"""Pre-flight VLM model resolution (spec §2.5).

Single responsibility: parse `--vlm-model` argument, route to one of three
resolution cases, return a frozen (model_id, resolved_checkpoint) tuple that
the rest of the system trusts.

This module is the ONLY caller of huggingface_hub. Everything else accepts
the resolved string verbatim.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mimicanno.errors import VLMModelNotFound

SHA40_REGEX = re.compile(r"^[0-9a-f]{40}$")
FIXTURE_URI_PREFIX = "fixture://"


@dataclass(slots=True, frozen=True)
class PreflightResult:
    model_id: str
    resolved_checkpoint: str
    fixture_path: Path | None = None  # populated only for fixture:// URIs


def _hf_model_info(model_id: str, revision: Optional[str]) -> str:
    """Resolve a HuggingFace model_id+revision to a commit sha.
    Isolated for monkeypatching in tests; production import guarded so that
    test environments without `huggingface_hub` installed still pass."""
    from huggingface_hub import HfApi  # local import — only loaded on real path
    info = HfApi().model_info(model_id, revision=revision)
    sha = getattr(info, "sha", None) or getattr(info, "commit_hash", None)
    if not sha or not SHA40_REGEX.match(sha):
        raise OSError(f"HF returned non-sha revision: {sha!r}")
    return sha


def _split_model_at_revision(arg: str) -> tuple[str, Optional[str]]:
    if "@" in arg:
        model_id, _, revision = arg.partition("@")
        return model_id, revision
    return arg, None


def _resolve_fixture(path_str: str) -> PreflightResult:
    p = Path(path_str).resolve()
    if not p.is_file():
        raise VLMModelNotFound(
            model_id="fixture",
            reason=f"fixture file does not exist: {p}",
        )
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    return PreflightResult(
        model_id="fixture", resolved_checkpoint=sha, fixture_path=p,
    )


def resolve_vlm_model(arg: str, *, offline: bool) -> PreflightResult:
    """Resolve a CLI --vlm-model argument to a stable (model_id, sha) tuple.

    Cases (spec §2.5):
      A. <id>@<40-hex-sha>  → accept directly, no HF lookup. Offline-safe.
      B. <id> or <id>@<branch_or_tag> → HF lookup. Forbidden when offline=True.
      C. fixture://<path>   → sha = sha256(file content).

    Raises VLMModelNotFound on any resolution failure (Tier 1 abort, spec §4.2).
    """
    if arg.startswith(FIXTURE_URI_PREFIX):
        return _resolve_fixture(arg[len(FIXTURE_URI_PREFIX):])

    model_id, revision = _split_model_at_revision(arg)

    # Case A: explicit 40-hex sha.
    if revision is not None and SHA40_REGEX.match(revision):
        return PreflightResult(model_id=model_id, resolved_checkpoint=revision)

    # Case B: needs HF API lookup.
    if offline:
        raise VLMModelNotFound(
            model_id=arg,
            reason=(
                "explicit 40-hex commit sha required after '@' for --offline runs "
                "(use '<id>@<40-hex-sha>')"
            ),
        )

    try:
        sha = _hf_model_info(model_id, revision)
    except Exception as e:  # network, 404, auth — all collapse into Tier 1.
        raise VLMModelNotFound(model_id=arg, reason=str(e)) from e
    return PreflightResult(model_id=model_id, resolved_checkpoint=sha)
