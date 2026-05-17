"""U-A3 — VLM dumps reader (master §2.4 rev3).

Walks the on-disk `_vlm_dumps/` directory tree (run-set-scoped, keyed by
source `episode_id`) and aggregates planner + segment classifier calls
into a flat list of :class:`VlmCall` for the HTTP route to serialize.

See `docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md` and
master spec §2.4 for layout. The writer side lives in
`scripts/batch_annotate_4B.py` / Gemma planner code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


VlmCallKind = Literal["planner", "segment"]


@dataclass(frozen=True)
class VlmCall:
    call_id: str            # "_planner/call_NNN" or "s_NNN/attempt_M"
    kind: VlmCallKind
    phase: str | None       # parsed.phase for segment; None for planner
    segment_id: str | None  # "s_NNN" for segment; None for planner
    prompt: str
    raw_output: str
    parsed: Any             # json.loads(response.txt) or None
    failed: bool
    ms: float | None        # not stored on disk yet (rev3 nullable)
    model_variant: str | None  # ditto


def _read_text_or_empty(path: Path) -> tuple[str, bool]:
    """Return (content, missing_flag). Missing or unreadable → ("", True)."""
    try:
        return path.read_text(), False
    except FileNotFoundError:
        return "", True


def _try_parse_json(raw: str) -> Any | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None


def _planner_calls(planner_root: Path) -> list[VlmCall]:
    if not planner_root.is_dir():
        return []
    out: list[VlmCall] = []
    # Sorted by directory name (call_000 < call_001 < ...)
    for call_dir in sorted(p for p in planner_root.iterdir() if p.is_dir()):
        prompt, _ = _read_text_or_empty(call_dir / "prompt.txt")
        raw, missing = _read_text_or_empty(call_dir / "response.txt")
        parsed = _try_parse_json(raw)
        out.append(VlmCall(
            call_id=f"_planner/{call_dir.name}",
            kind="planner",
            phase=None,
            segment_id=None,
            prompt=prompt,
            raw_output=raw,
            parsed=parsed,
            # Planner calls are not marked failed even on malformed JSON;
            # they're informational. Caller can introspect parsed=None.
            failed=False,
            ms=None,
            model_variant=None,
        ))
    return out


def _segment_attempt_index(attempt_dir_name: str) -> int | None:
    """Parse `attempt_<N>` → N. Returns None for malformed names."""
    if not attempt_dir_name.startswith("attempt_"):
        return None
    try:
        return int(attempt_dir_name[len("attempt_"):])
    except ValueError:
        return None


def _segment_calls(ep_dir: Path) -> list[VlmCall]:
    """One call per segment dir, picking the highest-numbered attempt."""
    out: list[VlmCall] = []
    seg_dirs = sorted(
        p for p in ep_dir.iterdir()
        if p.is_dir() and p.name.startswith("s_")
    )
    for seg_dir in seg_dirs:
        # Pick highest attempt_M
        attempts = [
            (idx, p) for p in seg_dir.iterdir() if p.is_dir()
            if (idx := _segment_attempt_index(p.name)) is not None
        ]
        if not attempts:
            continue
        attempts.sort(key=lambda x: x[0])
        attempt_idx, attempt_dir = attempts[-1]

        prompt, _ = _read_text_or_empty(attempt_dir / "prompt.txt")
        raw, missing = _read_text_or_empty(attempt_dir / "response.txt")
        parsed = _try_parse_json(raw)
        # For segments, a missing or unparseable response = failed.
        failed = missing or parsed is None
        phase: str | None = None
        if isinstance(parsed, dict):
            ph = parsed.get("phase")
            if isinstance(ph, str):
                phase = ph

        out.append(VlmCall(
            call_id=f"{seg_dir.name}/{attempt_dir.name}",
            kind="segment",
            phase=phase,
            segment_id=seg_dir.name,
            prompt=prompt,
            raw_output=raw,
            parsed=parsed,
            failed=failed,
            ms=None,
            model_variant=None,
        ))
    return out


def read_vlm_dumps(run_set_root: Path, episode_id: str) -> list[VlmCall]:
    """Aggregate planner + segment calls for ``episode_id`` under
    ``<run_set_root>/_vlm_dumps/<episode_id>/``.

    Missing dir → empty list (NOT an error; master §2.4 rev3 step 3).
    """
    ep_dir = run_set_root / "_vlm_dumps" / episode_id
    if not ep_dir.is_dir():
        return []
    planner = _planner_calls(ep_dir / "_planner")
    segments = _segment_calls(ep_dir)
    return planner + segments


def resolve_episode_id(run_set_root: Path, canonical: str) -> str | None:
    """Map ``canonical`` → source ``episode_id`` via ``index.json``.

    Returns ``None`` if index.json is missing OR no entry has
    ``manifest_url`` starting with ``<canonical>/``.
    """
    index_path = run_set_root / "index.json"
    try:
        raw = index_path.read_text()
    except FileNotFoundError:
        return None
    try:
        index = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    runs = index.get("runs") if isinstance(index, dict) else None
    if not isinstance(runs, list):
        return None
    needle = f"{canonical}/manifest.json"
    for entry in runs:
        if not isinstance(entry, dict):
            continue
        if entry.get("manifest_url") == needle:
            ep_id = entry.get("episode_id")
            if isinstance(ep_id, str):
                return ep_id
    return None
