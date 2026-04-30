"""Resolve ``canonical_name`` per ``episode_index`` for the bulk exporter.

Reads ``<runs_root>/index.json`` (via :mod:`mimicanno.runindex`) plus each
candidate run's ``manifest.json`` (for the full ``config_hash``) and returns a
``{episode_index: canonical_name}`` mapping.

Filters / errors per spec §1.1 and the Phase 5 plan Task 20:

- ``EXPORT_RUNS_ROOT_NOT_FOUND`` if ``runs_root`` or ``runs_root/index.json``
  does not exist.
- ``EXPORT_RUN_NOT_FOUND`` if no row matches ``target_phase`` (and optional
  ``config_hash`` filter) for an episode. ``skip_missing=True`` suppresses
  this and excludes the episode from the returned mapping.
- ``EXPORT_RUN_AMBIGUOUS`` if multiple rows survive filtering with distinct
  ``config_hash`` values and no ``config_hash`` filter is given. The
  ``candidates`` list is included in the error context for diff.
- Multiple rows with the same ``config_hash`` (re-runs) → newest
  ``generated_at`` wins.

``explicit_runs`` overrides ``target_phase`` / ``config_hash`` filters: each
named canonical_name is validated against the index and mapped back to its
``episode_index`` via ``manifest.json:episode_id``.
"""

from __future__ import annotations

import json
from pathlib import Path

from mimicanno.errors import ErrorCode, MimicAnnoError
from mimicanno.runindex import IndexRow, read_index


def _episode_id_to_index(episode_id: str) -> int:
    """Parse ``episode_NNNNNN`` → ``int(NNNNNN)``."""
    if "_" not in episode_id:
        raise MimicAnnoError(
            ErrorCode.EXPORT_RUN_NOT_FOUND,
            f"cannot parse episode_index from episode_id={episode_id!r}",
            {"episode_id": episode_id},
        )
    suffix = episode_id.rsplit("_", 1)[-1]
    try:
        return int(suffix)
    except ValueError as e:
        raise MimicAnnoError(
            ErrorCode.EXPORT_RUN_NOT_FOUND,
            f"cannot parse episode_index from episode_id={episode_id!r}",
            {"episode_id": episode_id},
        ) from e


def _canonical_from_row(row: IndexRow) -> str:
    """Extract ``canonical_name`` from ``IndexRow.manifest_url``.

    ``manifest_url`` is written as ``"<canonical_name>/manifest.json"`` by
    :mod:`mimicanno.publish`.
    """
    url = row.manifest_url
    if "/" not in url:
        raise MimicAnnoError(
            ErrorCode.EXPORT_RUN_NOT_FOUND,
            f"cannot derive canonical_name from manifest_url={url!r}",
            {"manifest_url": url},
        )
    return url.split("/", 1)[0]


def _read_full_config_hash(runs_root: Path, canonical_name: str) -> str:
    """Load ``runs_root/<canonical>/manifest.json`` and return its config_hash."""
    manifest_path = runs_root / canonical_name / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return str(raw["config_hash"])


def resolve_runs_for_episodes(
    runs_root: Path,
    episode_indices: list[int],
    target_phase: int,
    *,
    config_hash: str | None = None,
    explicit_runs: list[str] | None = None,
    skip_missing: bool = False,
) -> dict[int, str]:
    """Find ``canonical_name`` per ``episode_index`` (spec §1.1)."""
    if not runs_root.exists() or not (runs_root / "index.json").exists():
        raise MimicAnnoError(
            ErrorCode.EXPORT_RUNS_ROOT_NOT_FOUND,
            f"runs root or index.json not found at {runs_root}",
            {"runs_root": str(runs_root)},
        )

    index = read_index(runs_root / "index.json")
    rows_by_canonical: dict[str, IndexRow] = {}
    for r in index.rows:
        rows_by_canonical[_canonical_from_row(r)] = r

    # explicit_runs path: bypass target_phase / config_hash; just validate.
    if explicit_runs is not None:
        result: dict[int, str] = {}
        for canonical in explicit_runs:
            if canonical not in rows_by_canonical:
                raise MimicAnnoError(
                    ErrorCode.EXPORT_RUN_NOT_FOUND,
                    f"canonical_name {canonical!r} not in {runs_root}/index.json",
                    {"canonical_name": canonical, "runs_root": str(runs_root)},
                )
            row = rows_by_canonical[canonical]
            ep_idx = _episode_id_to_index(row.episode_id)
            result[ep_idx] = canonical
        return result

    # Build per-episode candidate lists, filtered by target_phase.
    candidates_by_ep: dict[int, list[IndexRow]] = {}
    for r in index.rows:
        if r.pipeline_phase != target_phase:
            continue
        ep_idx = _episode_id_to_index(r.episode_id)
        candidates_by_ep.setdefault(ep_idx, []).append(r)

    result = {}
    for ep_idx in episode_indices:
        candidates = candidates_by_ep.get(ep_idx, [])
        if config_hash is not None:
            # Filter by full config_hash by reading each candidate's manifest.
            filtered: list[IndexRow] = []
            for r in candidates:
                canonical = _canonical_from_row(r)
                if _read_full_config_hash(runs_root, canonical) == config_hash:
                    filtered.append(r)
            candidates = filtered

        if not candidates:
            if skip_missing:
                continue
            raise MimicAnnoError(
                ErrorCode.EXPORT_RUN_NOT_FOUND,
                (
                    f"no run found for episode_index={ep_idx} with "
                    f"target_phase={target_phase}"
                    + (
                        f", config_hash={config_hash}"
                        if config_hash is not None
                        else ""
                    )
                ),
                {
                    "episode_index": ep_idx,
                    "target_phase": target_phase,
                    "config_hash": config_hash,
                },
            )

        if len(candidates) == 1:
            result[ep_idx] = _canonical_from_row(candidates[0])
            continue

        # Multiple matches. Group by full config_hash.
        if config_hash is None:
            seen_hashes: set[str] = set()
            grouped: dict[str, list[IndexRow]] = {}
            for r in candidates:
                full_hash = _read_full_config_hash(
                    runs_root, _canonical_from_row(r)
                )
                seen_hashes.add(full_hash)
                grouped.setdefault(full_hash, []).append(r)
            if len(seen_hashes) > 1:
                raise MimicAnnoError(
                    ErrorCode.EXPORT_RUN_AMBIGUOUS,
                    (
                        f"multiple runs match episode_index={ep_idx} "
                        f"target_phase={target_phase} with distinct "
                        f"config_hashes; pass --config-hash to disambiguate"
                    ),
                    {
                        "episode_index": ep_idx,
                        "target_phase": target_phase,
                        "candidates": [
                            {
                                "canonical_name": _canonical_from_row(r),
                                "config_hash_short": r.config_hash_short,
                                "generated_at": r.generated_at,
                            }
                            for r in candidates
                        ],
                    },
                )
            # Single config_hash with multiple re-runs — pick newest.
            same_hash_candidates = next(iter(grouped.values()))
            newest = max(same_hash_candidates, key=lambda r: r.generated_at)
            result[ep_idx] = _canonical_from_row(newest)
        else:
            # config_hash filter already applied; pick newest among survivors.
            newest = max(candidates, key=lambda r: r.generated_at)
            result[ep_idx] = _canonical_from_row(newest)

    return result
