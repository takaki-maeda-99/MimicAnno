"""U-A3 — VLM dumps reader (master §2.4 rev3, corrected).

Walks the on-disk ``_vlm_dumps/`` directory tree (run-set-scoped, keyed by
source ``episode_id``) and aggregates planner + labeler calls into a flat
list of :class:`VlmCall` for the HTTP route to serialize.

Rev3 schema fixes relative to what shipped in PR #14 (origin/main ~9cdce19):
  - ``kind`` is ``"planner" | "labeler"`` (PR #14 used ``"segment"``).
  - ``call_id``: planner → ``"call_NNN"`` (no ``_planner/`` prefix);
                 labeler → ``"s_NNN__attempt_M"`` (not ``"s_NNN/attempt_M"``).
  - Added: ``segment_ordinal``, ``attempt``, ``frame_url``, ``keyframe_urls``,
           ``request_json``.
  - Removed: ``ms``, ``model_variant``, ``phase`` (top-level), ``segment_id``.
  - ``failed`` for labeler: True iff a *later* attempt_M+1 exists for the
    same s_NNN dir. All non-final attempts → failed=True. Final attempt may
    also be failed if its response.txt is missing or unparseable.

See ``docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md``
§2.4 (rev3) for the canonical contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


VlmCallKind = Literal["planner", "labeler"]


@dataclass(frozen=True)
class VlmCall:
    """One planner or labeler call as stored in _vlm_dumps/."""

    call_id: str          # "call_NNN" for planner; "s_NNN__attempt_M" for labeler
    kind: VlmCallKind
    attempt: int | None   # 1-based attempt index from dir name; None for planner
    prompt: str
    raw_output: str
    parsed: Any           # json.loads(response.txt) or None on parse error
    failed: bool

    # Planner-only (None / empty for labeler)
    frame_url: str | None

    # Labeler-only (None / empty for planner)
    segment_ordinal: int | None
    request_json: Any
    keyframe_urls: list[str] = field(default_factory=list)


def _read_text_or_empty(path: Path) -> tuple[str, bool]:
    """Return (content, missing_flag). Missing or unreadable → ("", True)."""
    try:
        return path.read_text(), False
    except FileNotFoundError:
        return "", True


def _try_parse_json(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None


def _planner_calls(
    planner_root: Path,
    run_set: str,
    episode_id: str,
) -> list[VlmCall]:
    if not planner_root.is_dir():
        return []
    out: list[VlmCall] = []
    # Sort by directory name: call_000 < call_001 < ...
    for call_dir in sorted(p for p in planner_root.iterdir() if p.is_dir()):
        prompt, _ = _read_text_or_empty(call_dir / "prompt.txt")
        raw, _ = _read_text_or_empty(call_dir / "response.txt")
        parsed = _try_parse_json(raw)
        frame_url = (
            f"/runs/{run_set}/_vlm_dumps/{episode_id}"
            f"/_planner/{call_dir.name}/frame.png"
        )
        out.append(VlmCall(
            call_id=call_dir.name,   # "call_000" — no "_planner/" prefix
            kind="planner",
            attempt=None,
            prompt=prompt,
            raw_output=raw,
            parsed=parsed,
            failed=False,            # planner never has multi-attempt
            frame_url=frame_url,
            segment_ordinal=None,
            request_json=None,
            keyframe_urls=[],
        ))
    return out


def _attempt_index(attempt_dir_name: str) -> int | None:
    """Parse ``attempt_<N>`` → N (non-negative). Returns None on malformed."""
    if not attempt_dir_name.startswith("attempt_"):
        return None
    try:
        idx = int(attempt_dir_name[len("attempt_"):])
    except ValueError:
        return None
    return idx if idx >= 0 else None


def _ordinal_from_seg_dir(seg_dir_name: str) -> int | None:
    """Parse ``s_NNN`` → integer ordinal. Returns None on malformed input."""
    if not seg_dir_name.startswith("s_"):
        return None
    try:
        return int(seg_dir_name[2:])
    except ValueError:
        return None


def _labeler_calls(
    ep_dir: Path,
    run_set: str,
    episode_id: str,
) -> list[VlmCall]:
    """All attempts for every s_NNN segment dir, sorted by (ordinal, attempt).

    Per rev3 §2.4: ``failed=True`` for all but the highest-numbered attempt
    of each s_NNN, PLUS the final attempt if its response.txt is absent /
    unparseable.
    """
    out: list[VlmCall] = []
    seg_dirs = sorted(
        p for p in ep_dir.iterdir()
        if p.is_dir() and p.name.startswith("s_")
    )
    for seg_dir in seg_dirs:
        ordinal = _ordinal_from_seg_dir(seg_dir.name)
        if ordinal is None:
            continue

        # Collect all (attempt_idx, Path) pairs
        attempts: list[tuple[int, Path]] = []
        for p in seg_dir.iterdir():
            if not p.is_dir():
                continue
            idx = _attempt_index(p.name)
            if idx is not None:
                attempts.append((idx, p))
        if not attempts:
            continue
        attempts.sort(key=lambda x: x[0])
        max_attempt_idx = attempts[-1][0]

        for attempt_idx, attempt_dir in attempts:
            is_failed = attempt_idx < max_attempt_idx

            prompt, _ = _read_text_or_empty(attempt_dir / "prompt.txt")
            raw, missing = _read_text_or_empty(attempt_dir / "response.txt")
            parsed = _try_parse_json(raw)
            # Missing or unparseable response on any attempt → still failed
            if missing or parsed is None:
                is_failed = True

            req_raw, _ = _read_text_or_empty(attempt_dir / "request.json")
            request_json = _try_parse_json(req_raw)

            base_url = (
                f"/runs/{run_set}/_vlm_dumps/{episode_id}"
                f"/{seg_dir.name}/{attempt_dir.name}"
            )
            keyframe_urls = [
                f"{base_url}/{kf.name}"
                for kf in sorted(attempt_dir.glob("keyframe_*.png"))
            ]

            out.append(VlmCall(
                call_id=f"{seg_dir.name}__attempt_{attempt_idx}",
                kind="labeler",
                attempt=attempt_idx,
                prompt=prompt,
                raw_output=raw,
                parsed=parsed,
                failed=is_failed,
                frame_url=None,
                segment_ordinal=ordinal,
                request_json=request_json,
                keyframe_urls=keyframe_urls,
            ))
    return out


def read_vlm_dumps(
    run_set_root: Path,
    episode_id: str,
    run_set: str = "",
) -> list[VlmCall]:
    """Aggregate planner + labeler calls for ``episode_id``.

    Reads from ``<run_set_root>/_vlm_dumps/<episode_id>/``.
    Missing dir → empty list (NOT an error; master §2.4 rev3).

    ``run_set`` is used to construct image URL paths for ``frame_url`` /
    ``keyframe_urls``; pass the run-set name (e.g., ``"gem4_open_the_jar_26B"``).
    """
    ep_dir = run_set_root / "_vlm_dumps" / episode_id
    if not ep_dir.is_dir():
        return []
    planner = _planner_calls(ep_dir / "_planner", run_set, episode_id)
    labelers = _labeler_calls(ep_dir, run_set, episode_id)
    return planner + labelers


def resolve_episode_id(run_set_root: Path, canonical: str) -> str | None:
    """Map ``canonical`` → source ``episode_id`` via ``index.json``.

    Returns ``None`` if index.json is missing OR no entry has
    ``manifest_url`` matching ``<canonical>/manifest.json``.
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
