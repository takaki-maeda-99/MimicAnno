"""U-A2 — Dataset summary reader (spec §2.2).

Aggregates annotation.json files across a chosen run_set to produce:
  - label_distribution: phase → count
  - segment_count_stats: mean/min/max
  - reviewed_rate: reviewed_segments / total_segments
  - per_episode: sorted list of per-ep mini-summaries

Run-set scoping follows master spec §2.0:
  - A run_set is a subdir of runs_root containing index.json.
  - Bare canonical dirs at top level → synthetic ``__legacy__`` bucket.
  - Most recent run_set = latest index.json mtime.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("mimicanno.server")

_EPISODE_IDX_RE = re.compile(r"^episode_(\d+)$")


def _ep_idx_from_id(episode_id: str) -> int | None:
    m = _EPISODE_IDX_RE.match(episode_id)
    return int(m.group(1)) if m else None


def _read_ep_count(data_root: Path, dataset_name: str) -> int:
    info_path = data_root / dataset_name / "meta" / "info.json"
    if not info_path.exists():
        return 0
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
        v = info.get("total_episodes", 0)
        return int(v) if isinstance(v, int) else 0
    except Exception:
        return 0


def _discover_run_sets(runs_root: Path) -> dict[str, Path]:
    """Return {run_set_name: index_json_path} for all run-sets.

    If runs_root/index.json exists → single ``__legacy__`` mode.
    Otherwise scan subdirs for those containing index.json.
    Also includes bare canonical dirs at top level → __legacy__ (but only
    if no top-level index.json is already present).
    """
    result: dict[str, Path] = {}
    if not runs_root.is_dir():
        return result

    legacy_index = runs_root / "index.json"
    if legacy_index.exists():
        result["__legacy__"] = legacy_index
        return result

    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        idx = entry / "index.json"
        if idx.exists():
            result[entry.name] = idx

    return result


def _most_recent_run_set(run_sets: dict[str, Path]) -> str | None:
    """Return the run_set name whose index.json has the latest mtime."""
    if not run_sets:
        return None
    return max(run_sets, key=lambda name: run_sets[name].stat().st_mtime)


def _load_index(index_path: Path) -> list[dict[str, Any]]:
    """Load runs list from index.json; return [] on error."""
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        runs = data.get("runs", [])
        return runs if isinstance(runs, list) else []
    except Exception:
        return []


def _canonical_dir_for_run_set(runs_root: Path, run_set_name: str) -> Path:
    """Return the directory that contains canonical subdirs for this run_set."""
    if run_set_name == "__legacy__":
        return runs_root
    return runs_root / run_set_name


def _read_annotation(can_dir: Path) -> list[dict[str, Any]] | None:
    """Read annotation.json from a canonical dir; return None on error."""
    ann_path = can_dir / "annotation.json"
    if not ann_path.exists():
        return None
    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        segs = data.get("segments", [])
        return segs if isinstance(segs, list) else []
    except Exception:
        return None


def compute_summary(
    dataset_name: str,
    data_root: Path,
    runs_root: Path,
    run_set: str | None = None,
) -> dict[str, Any]:
    """Compute dataset summary for the given run_set (or most recent).

    Returns a dict matching master spec §2.2 shape.
    Returns 404-sentinel (None) if the dataset does not exist.
    """
    ep_count = _read_ep_count(data_root, dataset_name)

    run_sets = _discover_run_sets(runs_root)

    # Resolve run_set
    if run_set is None:
        resolved_rs = _most_recent_run_set(run_sets)
    else:
        resolved_rs = run_set if run_set in run_sets else None

    if resolved_rs is None:
        # No run_sets at all, or unknown run_set → empty summary
        return {
            "run_set": run_set or "",
            "ep_count": ep_count,
            "annotated_ep_count": 0,
            "label_distribution": {},
            "segment_count_stats": {"mean": 0, "min": 0, "max": 0},
            "reviewed_rate": 0.0,
            "per_episode": [],
        }

    index_path = run_sets[resolved_rs]
    runs = _load_index(index_path)
    rs_dir = _canonical_dir_for_run_set(runs_root, resolved_rs)

    # Deduplicate by episode_id (keep latest generated_at)
    ep_best_canonical: dict[str, dict[str, Any]] = {}
    for row in runs:
        ep_id = row.get("episode_id", "")
        if not ep_id:
            continue
        gen = row.get("generated_at", "")
        if ep_id not in ep_best_canonical or gen > ep_best_canonical[ep_id]["generated_at"]:
            canonical = row.get("canonical_name", "")
            if not canonical:
                # Derive from manifest_url
                mu = row.get("manifest_url", "")
                canonical = mu.split("/")[0] if "/" in mu else mu
            ep_best_canonical[ep_id] = {
                "canonical": canonical,
                "generated_at": gen,
            }

    annotated_ep_count = len(ep_best_canonical)

    # Aggregate
    label_distribution: dict[str, int] = {}
    segment_counts: list[int] = []
    total_segments = 0
    total_reviewed = 0
    per_episode: list[dict[str, Any]] = []

    for ep_id, info in ep_best_canonical.items():
        canonical = info["canonical"]
        can_dir = rs_dir / canonical
        segs = _read_annotation(can_dir)

        if segs is None:
            # Malformed / missing annotation — skip from aggregation
            _LOG.debug("Skipping malformed annotation for %s/%s", resolved_rs, canonical)
            continue

        seg_count = len(segs)
        reviewed_count = sum(1 for s in segs if s.get("reviewed", False))
        distinct_phases: set[str] = set()
        for s in segs:
            phase = s.get("phase", "unlabeled") or "unlabeled"
            label_distribution[phase] = label_distribution.get(phase, 0) + 1
            distinct_phases.add(phase)

        segment_counts.append(seg_count)
        total_segments += seg_count
        total_reviewed += reviewed_count

        idx = _ep_idx_from_id(ep_id)
        per_episode.append({
            "idx": idx if idx is not None else -1,
            "canonical": canonical,
            "segment_count": seg_count,
            "reviewed_count": reviewed_count,
            "label_diversity": len(distinct_phases),
        })

    # Sort per_episode by idx
    per_episode.sort(key=lambda ep: ep["idx"])

    # Stats
    if segment_counts:
        mean_count = sum(segment_counts) / len(segment_counts)
        min_count = min(segment_counts)
        max_count = max(segment_counts)
    else:
        mean_count = 0.0
        min_count = 0
        max_count = 0

    reviewed_rate = (total_reviewed / total_segments) if total_segments > 0 else 0.0

    return {
        "run_set": resolved_rs,
        "ep_count": ep_count,
        "annotated_ep_count": annotated_ep_count,
        "label_distribution": label_distribution,
        "segment_count_stats": {
            "mean": mean_count,
            "min": min_count,
            "max": max_count,
        },
        "reviewed_rate": reviewed_rate,
        "per_episode": per_episode,
    }
